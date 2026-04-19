"""LLM token and cost tracking with per-call ledger persistence."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.observability.context import get_active_run, get_active_step
from app.observability.persistence import insert_llm_call_cost

logger = logging.getLogger(__name__)

# USD per 1k input/output tokens
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.010, 0.030),
    "gpt-4": (0.030, 0.060),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "deepseek-chat": (0.00014, 0.00028),
    "deepseek-reasoner": (0.00055, 0.00219),
}

_DEFAULT_PRICING = (0.002, 0.002)


def _pricing_for(model_name: str | None) -> tuple[float, float]:
    if not model_name:
        return _DEFAULT_PRICING
    key = model_name.lower()
    for name, rates in _PRICING.items():
        if key.startswith(name):
            return rates
    return _DEFAULT_PRICING


def estimate_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    model_name: str | None,
) -> float:
    input_rate, output_rate = _pricing_for(model_name)
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1000.0


def estimate_cost_breakdown_usd(
    prompt_tokens: int,
    completion_tokens: int,
    model_name: str | None,
) -> tuple[float, float, float]:
    input_rate, output_rate = _pricing_for(model_name)
    input_cost = (prompt_tokens * input_rate) / 1000.0
    output_cost = (completion_tokens * output_rate) / 1000.0
    return input_cost, output_cost, input_cost + output_cost


def _provider_for(model_name: str | None) -> str | None:
    if not model_name:
        return None
    key = model_name.lower()
    if key.startswith("gpt-"):
        return "openai"
    if key.startswith("deepseek"):
        return "deepseek"
    return None


def _coerce_uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _extract_usage(response: LLMResult) -> tuple[int, int]:
    llm_output = response.llm_output or {}
    usage = llm_output.get("token_usage", {}) or {}

    prompt_tokens = usage.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = usage.get("input_tokens")

    completion_tokens = usage.get("completion_tokens")
    if completion_tokens is None:
        completion_tokens = usage.get("output_tokens")

    if (prompt_tokens is None or completion_tokens is None) and response.generations:
        try:
            msg = response.generations[0][0].message
            meta = getattr(msg, "usage_metadata", None) or {}
            if prompt_tokens is None:
                prompt_tokens = meta.get("input_tokens")
            if completion_tokens is None:
                completion_tokens = meta.get("output_tokens")
        except Exception:
            pass

    return int(prompt_tokens or 0), int(completion_tokens or 0)


def _extract_model_name(
    response: LLMResult,
    *,
    serialized: dict[str, Any] | None = None,
    invocation_params: dict[str, Any] | None = None,
) -> str | None:
    llm_output = response.llm_output or {}
    for candidate in (
        llm_output.get("model_name"),
        (invocation_params or {}).get("model"),
        (serialized or {}).get("kwargs", {}).get("model"),
        (serialized or {}).get("name"),
    ):
        if candidate:
            return str(candidate)
    return None


@dataclass
class _PendingCall:
    started_at: datetime
    serialized: dict[str, Any] | None
    invocation_params: dict[str, Any] | None


class TokenCostCallback(BaseCallbackHandler):
    """Track run totals and persist each call as an atomic ledger record."""

    def __init__(self) -> None:
        super().__init__()
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.llm_call_count: int = 0
        self._last_model: str | None = None
        self._pending_calls: dict[str, _PendingCall] = {}

    def _remember_call(
        self,
        *,
        run_id: Any,
        serialized: dict[str, Any] | None = None,
        invocation_params: dict[str, Any] | None = None,
    ) -> None:
        key = _coerce_uuid(run_id) or uuid.uuid4().hex
        self._pending_calls[key] = _PendingCall(
            started_at=datetime.utcnow(),
            serialized=serialized,
            invocation_params=invocation_params,
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._remember_call(
            run_id=run_id,
            serialized=serialized,
            invocation_params=kwargs.get("invocation_params"),
        )

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        key = _coerce_uuid(run_id)
        if key and key in self._pending_calls:
            return
        self._remember_call(
            run_id=run_id,
            serialized=serialized,
            invocation_params=kwargs.get("invocation_params"),
        )

    def on_llm_end(self, response: LLMResult, *, run_id: Any, **kwargs: Any) -> None:
        prompt_tokens, completion_tokens = _extract_usage(response)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.llm_call_count += 1

        key = _coerce_uuid(run_id)
        pending = self._pending_calls.pop(key, None) if key else None
        model_name = _extract_model_name(
            response,
            serialized=pending.serialized if pending else None,
            invocation_params=pending.invocation_params if pending else None,
        )
        if model_name:
            self._last_model = model_name

        input_cost, output_cost, total_cost = estimate_cost_breakdown_usd(
            prompt_tokens,
            completion_tokens,
            model_name,
        )

        active_run = get_active_run()
        active_step = get_active_step()
        if active_run is None:
            return

        started_at = pending.started_at if pending else datetime.utcnow()
        ended_at = datetime.utcnow()
        latency_ms = max((ended_at - started_at).total_seconds() * 1000.0, 0.0)
        provider = _provider_for(model_name)

        try:
            insert_llm_call_cost(
                run_id=active_run.run_id,
                case_id=active_run.case_id,
                sequence_number=active_step.sequence_number if active_step else None,
                agent_name=active_step.node_name if active_step else None,
                langsmith_run_id=key,
                provider=provider,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                input_cost_usd=input_cost,
                output_cost_usd=output_cost,
                total_cost_usd=total_cost,
                latency_ms=latency_ms,
                status="success",
                retry_number=active_step.retry_number if active_step else 0,
                started_at=started_at,
                ended_at=ended_at,
                metadata={
                    "trace_id": active_run.trace_id,
                    "provider": provider,
                    "model_name": model_name,
                },
            )
        except Exception:
            logger.exception("Failed to persist llm_call_costs entry")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_usd(self, model_name: str | None = None) -> float:
        return estimate_cost_usd(
            self.prompt_tokens,
            self.completion_tokens,
            model_name or self._last_model,
        )
