"""Small helpers for explicitly configured compatible API connections."""
import json
import subprocess
import sys
import time
from pathlib import Path

from .companion import validate_url
from .store import Problem

INTENTS = ("intent_judgment", "daily_chat", "deep_analysis", "resume", "interview", "hr")
MAX_MODEL_RESPONSE = 256 * 1024


def public_connections(settings):
    """Return connection configuration safe for the workbench response."""
    secrets = [settings.get("api_key", "")] + [c.get("api_key", "") for c in settings.get("connections", [])]
    result = []
    for item in settings.get("connections", []):
        secret = item.get("api_key", "")
        safe = lambda value: "（已隐藏）" if any(key and key in str(value) for key in secrets) else value
        result.append({key: safe(item.get(key, "")) for key in ("id", "name", "base_url", "api_model")}
                      | {"has_api_key": bool(secret)})
    return result


def public_task_models(settings):
    secrets = [settings.get("api_key", "")] + [c.get("api_key", "") for c in settings.get("connections", [])]
    result = {}
    for intent, assignment in settings.get("task_models", {}).items():
        if not isinstance(assignment, dict):
            continue
        model = assignment.get("model", "")
        result[intent] = {"connection_id": assignment.get("connection_id", ""),
                          "model": "（已隐藏）" if any(key and key in str(model) for key in secrets) else model}
    return result


def resolve_task_model(settings, intent):
    """Resolve a user's explicit model assignment; otherwise preserve legacy defaults."""
    if intent not in INTENTS:
        raise Problem("任务模型用途无效")
    assignment = settings.get("task_models", {}).get(intent) or {}
    if not assignment:
        return dict(settings)
    connection = next((c for c in settings.get("connections", []) if c.get("id") == assignment.get("connection_id")), None)
    if not connection:
        raise Problem("当前任务指派的连接已不存在；请在工作台重新选择连接")
    model = assignment.get("model") or connection.get("api_model", "")
    if not model or not connection.get("base_url") or not connection.get("api_key"):
        raise Problem("当前任务指派的连接缺少地址、密钥或模型；请在工作台补全后重试")
    resolved = dict(settings)
    for key in ("provider", "base_url", "api_key", "json_mode", "stream", "stream_verified"):
        if key in connection:
            resolved[key] = connection[key]
    resolved.update(provider="api", api_model=model)
    return resolved


def list_models(connection, timeout=6):
    """Fetch bounded model IDs from one already-saved compatible API connection."""
    validate_url(connection.get("base_url", ""))
    budget = max(.1, min(float(timeout), 6.0))
    began = time.monotonic()
    proc = None
    try:
        proc = subprocess.Popen([sys.executable, "-m", "app.model_catalog_transport"],
                                cwd=Path(__file__).resolve().parent.parent,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        request = json.dumps({"connection": connection, "timeout": budget}, ensure_ascii=False)
        out, _ = proc.communicate(request, timeout=min(8.0, budget + 1.5))
        if time.monotonic() - began > min(8.0, budget + 1.5):
            raise Problem("获取模型列表超时，请手动填写模型名")
        if proc.returncode != 0 or not out or len(out.encode("utf-8")) > MAX_MODEL_RESPONSE:
            raise Problem("获取模型列表失败，请检查连接；也可以手动填写模型名")
        result = json.loads(out)
        if result.get("error"):
            raise Problem(result["error"])
        models = result.get("models")
        if not isinstance(models, list) or any(not isinstance(m, str) for m in models):
            raise Problem("模型列表格式不兼容，可手动填写模型名")
        secret = connection.get("api_key", "")
        if secret:
            models = [model for model in models if secret not in model]
        return models
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            try: proc.communicate(timeout=.5)
            except (OSError, subprocess.TimeoutExpired): pass
        raise Problem("获取模型列表超时，请手动填写模型名") from None
    except Problem:
        raise
    except (OSError, ValueError, TypeError):
        raise Problem("获取模型列表失败，请检查连接；也可以手动填写模型名") from None
