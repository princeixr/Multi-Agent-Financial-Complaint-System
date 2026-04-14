"""Session debug NDJSON logger (voice/TTS). Do not log secrets."""

from __future__ import annotations

import json
import time
from pathlib import Path

_DEBUG_LOG = Path("/Users/nandanprince/Desktop/AI Agent for Complaint Classification/.cursor/debug-220b77.log")


def dbg_voice(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    try:
        payload = {
            "sessionId": "220b77",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
