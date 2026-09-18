"""Short-lived cloud audio transport. Credentials arrive on stdin only."""
import base64
import json
import sys
import urllib.error
import urllib.request
import uuid

from .companion import validate_url
from .providers import NoRedirect
from .store import Problem


def endpoint(settings, suffix):
    base = validate_url(settings.get("voice_base_url", "https://api.openai.com/v1"))
    return base.rstrip("/") + suffix


def request(url, data, content_type, key, limit):
    headers = {"Content-Type": content_type, "Authorization": "Bearer " + key}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as response:
            raw = response.read(limit + 1)
            response_type = response.headers.get("Content-Type", "")
        if len(raw) > limit:
            raise Problem("云端语音返回内容过大")
        return raw, response_type
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise Problem("云端语音密钥无效或无权使用音频模型") from None
        if exc.code == 413:
            raise Problem("云端语音服务拒绝了过大的录音") from None
        raise Problem(f"云端语音接口返回 HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise Problem("云端语音服务连接失败或超时") from None


def multipart(fields, file_field, filename, mime, content):
    boundary = "----JobAssistant" + uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
    chunks.extend((content, b"\r\n", f"--{boundary}--\r\n".encode()))
    return b"".join(chunks), "multipart/form-data; boundary=" + boundary


def main():
    try:
        value = json.load(sys.stdin)
        settings = value["settings"]
        key = settings.get("voice_api_key", "")
        if not key:
            raise Problem("尚未保存云端语音密钥")
        if value["action"] == "transcribe":
            audio = base64.b64decode(value["audio_base64"], validate=True)
            body, kind = multipart(
                {"model": settings.get("voice_stt_model", "gpt-transcribe"),
                 "prompt": "求职与模拟面试对话。保持原意、中文标点和专有名词，不补写说话人没有表达的内容。"},
                "file", "recording." + value["extension"], value["mime_type"], audio,
            )
            raw, _ = request(endpoint(settings, "/audio/transcriptions"), body, kind, key, 1024 * 1024)
            result = json.loads(raw)
            text = result.get("text", "")
            if not isinstance(text, str) or not text.strip():
                raise Problem("云端没有识别到可用文字")
            output = {"ok": True, "text": text.strip()}
        elif value["action"] == "speech":
            body = json.dumps({
                "model": settings.get("voice_tts_model", "gpt-4o-mini-tts"),
                "voice": settings.get("voice_name", "marin"),
                "input": value["text"],
                "instructions": "自然、清楚、有陪伴感地说普通话。用于求职辅导，不冒充真人。",
                "response_format": "mp3",
            }, ensure_ascii=False).encode()
            raw, kind = request(endpoint(settings, "/audio/speech"), body, "application/json", key, 12 * 1024 * 1024)
            output = {"ok": True, "audio_base64": base64.b64encode(raw).decode(), "content_type": kind.split(";", 1)[0] or "audio/mpeg"}
        else:
            raise Problem("未知语音动作")
        print(json.dumps(output, ensure_ascii=False))
    except Problem as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
    except Exception:
        print(json.dumps({"ok": False, "error": "云端语音服务未返回有效内容"}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
