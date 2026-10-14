"""Line-oriented subprocess boundary for the dialogue agent."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from urllib.parse import urlparse

import httpx2
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .dialogue_core import run_turn


def _write(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


async def _read_line() -> str:
    return await asyncio.to_thread(sys.stdin.readline)


async def _main() -> None:
    line = await _read_line()
    if not line:
        _write({"type": "error", "message": "invalid_input"})
        return
    try:
        payload = json.loads(line)
        settings = payload["settings"]
        base_url = settings["base_url"]
        api_model = settings["api_model"]
        api_key = settings["api_key"]
        if not all(isinstance(x, str) and x for x in (base_url, api_model, api_key)):
            raise ValueError("invalid settings")
        if not isinstance(payload["user_text"], str) or not isinstance(payload["context"], dict) or not isinstance(payload["history"], list):
            raise ValueError("invalid turn")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _write({"type": "error", "message": "invalid_input"})
        return

    async def create_task(instruction: str) -> dict[str, Any]:
        _write({"type": "action", "instruction": instruction})
        response_line = await _read_line()
        if not response_line:
            return {"ok": False, "reason": "action_result_missing"}
        try:
            response = json.loads(response_line)
            receipt = response["action_result"]
            if not isinstance(receipt, dict):
                raise ValueError("invalid action result")
            return receipt
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {"ok": False, "reason": "invalid_action_result"}

    diagnostics = {}

    def emit(event: dict[str, Any]) -> None:
        if event.get("type") == "text":
            _write({"type": "delta", "text": event.get("text", "")})
        elif event.get("type") == "diagnostic":
            diagnostics.update({k: v for k, v in event.items() if k != "type"})

    try:
        # Local test/model endpoints must not be sent through macOS system proxies.
        local = urlparse(base_url).hostname in {"localhost", "127.0.0.1", "::1"}
        http_client = httpx2.AsyncClient(trust_env=not local, follow_redirects=False, timeout=45)
        async with AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0,
                               timeout=45, http_client=http_client) as client:
            # Only this isolated conversational layer uses non-thinking mode.
            # The existing background report worker is not changed. This bounds
            # ordinary replies/review without enlarging the shared token cap.
            model_settings = {"extra_body": {"thinking": {"type": "disabled"}}} if (
                urlparse(base_url).hostname == "api.deepseek.com" and api_model.startswith("deepseek-")
            ) else None
            model = OpenAIChatModel(api_model, provider=OpenAIProvider(openai_client=client), settings=model_settings)
            result = await run_turn(
                model=model,
                user_text=payload["user_text"],
                context=payload["context"],
                history=payload["history"],
                create_task=create_task,
                emit=emit,
                allow_task_creation=payload.get('allow_task_creation') is True,
            )
        _write({"type": "result", **result})
    except Exception as exc:
        # Provider exceptions can contain URLs, request bodies, or credentials.
        if isinstance(getattr(exc, "status_code", None), int):
            diagnostics["http_status"] = exc.status_code
        _write({"type": "error", "message": "agent_run_failed", "code": type(exc).__name__,
                "diagnostics": diagnostics})


if __name__ == "__main__":
    asyncio.run(_main())
