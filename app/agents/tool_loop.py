"""Reusable tool-calling loop for specialist agents.

Provides a simple ReAct-style loop: call LLM with tools bound, execute any
tool calls, feed results back, repeat until the LLM produces a final text
response (no more tool calls).
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.agents.llm_json import parse_llm_json

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def _evidence_flags(tools_called: set[str]) -> dict[str, bool]:
    """Convert the set of invoked tool names into an audit flag dict.

    Returns a mapping of ``{tool_name: True}`` for every tool that was called
    at least once during the agent loop.  Used by callers that pass
    ``return_evidence=True`` to build an :class:`~app.schemas.evidence.EvidenceTrace`.
    """
    return {name: True for name in tools_called}


def run_agent_with_tools(
    llm: ChatOpenAI,
    system_prompt: str,
    user_message: str,
    tools: list[BaseTool],
    max_rounds: int = MAX_TOOL_ROUNDS,
    return_evidence: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, bool]]:
    """Run an LLM agent with tools in a ReAct-style loop.

    The agent calls tools zero or more times, then produces a final text
    response containing JSON. The JSON is parsed and returned.

    Parameters
    ----------
    llm : ChatOpenAI
        The base LLM instance (tools will be bound to it).
    system_prompt : str
        System prompt for the agent.
    user_message : str
        User message describing the task.
    tools : list[BaseTool]
        Available tools the agent can call.
    max_rounds : int
        Maximum number of tool-calling rounds before forcing a final response.
    return_evidence : bool
        When True, return ``(parsed_json, evidence_flags)`` where flags record
        which tool names were invoked (for audit).

    Returns
    -------
    dict | tuple[dict, dict[str, bool]]
        Parsed JSON from the agent's final text response, optionally with evidence.
    """
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)
    tools_called: set[str] = set()

    messages: list = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    for round_num in range(max_rounds):
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        # If no tool calls, this is the final response
        if not response.tool_calls:
            parsed = parse_llm_json(response.content)
            if return_evidence:
                return parsed, _evidence_flags(tools_called)
            return parsed

        # Execute each tool call
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tools_called.add(tool_name)
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            logger.debug("Agent calling tool: %s(%s)", tool_name, tool_args)

            if tool_name not in tool_map:
                tool_result = f"Error: Unknown tool '{tool_name}'"
            else:
                try:
                    tool_result = tool_map[tool_name].invoke(tool_args)
                except Exception as exc:
                    tool_result = f"Error calling {tool_name}: {exc}"
                    logger.warning("Tool %s failed: %s", tool_name, exc)

            messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tool_id)
            )

    # If we exhausted rounds, force a response without tools
    logger.warning("Agent exhausted %d tool rounds, forcing final response", max_rounds)
    final = llm.invoke(messages)  # no tools bound — forces text response
    try:
        parsed = parse_llm_json(final.content)
        if return_evidence:
            return parsed, _evidence_flags(tools_called)
        return parsed
    except Exception as first_error:
        logger.warning("Final response was not valid JSON; requesting JSON repair")
        repair_prompt = (
            "Return ONLY a valid JSON object for the previously requested schema. "
            "Do not call tools, do not include markdown, prose, or tags."
        )
        repaired = llm.invoke([*messages, AIMessage(content=final.content), HumanMessage(content=repair_prompt)])
        try:
            parsed = parse_llm_json(repaired.content)
            if return_evidence:
                return parsed, _evidence_flags(tools_called)
            return parsed
        except Exception:
            raise first_error

