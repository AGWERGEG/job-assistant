"""Short-lived model catalog request; credentials arrive only through stdin."""
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .companion import validate_url
from .model_connections import MAX_MODEL_RESPONSE


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    try:
        request = json.loads(sys.stdin.readline())
        connection = request["connection"]
        timeout = max(.1, min(float(request.get("timeout", 6)), 6.0))
        base = validate_url(connection.get("base_url", ""))
        parsed = urlparse(base)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            path = path[:-len("/chat/completions")]
        endpoint = parsed._replace(path=path + "/models", query="", fragment="").geturl()
        headers = {"Accept": "application/json"}
        if connection.get("api_key"):
            headers["Authorization"] = "Bearer " + connection["api_key"]
        req = urllib.request.Request(endpoint, headers=headers, method="GET")
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            raw = response.read(MAX_MODEL_RESPONSE + 1)
        if len(raw) > MAX_MODEL_RESPONSE:
            emit({"error": "模型列表响应过大，请手动填写模型名"})
            return
        payload = json.loads(raw)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            emit({"error": "服务商模型列表格式不兼容，可手动填写模型名"})
            return
        models = []
        api_key = connection.get("api_key", "")
        for entry in data[:200]:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                model_id = entry["id"].strip()
                if model_id and len(model_id) <= 200 and not (api_key and api_key in model_id) and model_id not in models:
                    models.append(model_id)
        emit({"models": models})
    except urllib.error.HTTPError as exc:
        # Never echo the body, Location header, or request URL.
        emit({"error": "获取模型列表失败（HTTP " + str(exc.code) + "），请手动填写模型名"})
    except Exception:
        # Exception strings may contain the endpoint, key, or remote response.
        emit({"error": "获取模型列表失败，请检查连接；也可以手动填写模型名"})


if __name__ == "__main__":
    main()
