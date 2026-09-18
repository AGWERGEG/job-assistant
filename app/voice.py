"""Cloud-first speech I/O with an optional whisper.cpp fallback.

Raw recordings are accepted as bounded in-memory request data and only written
inside TemporaryDirectory when a local decoder is used. They are never stored
in SQLite, uploads, task snapshots, or logs.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .store import Problem, require_object, text_field


MIME_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
}
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _local_tools():
    whisper = os.environ.get("JOB_ASSISTANT_WHISPER_BIN", "").strip() or shutil.which("whisper-cli") or shutil.which("main")
    model = os.environ.get("JOB_ASSISTANT_WHISPER_MODEL", "").strip()
    ffmpeg = os.environ.get("JOB_ASSISTANT_FFMPEG_BIN", "").strip() or shutil.which("ffmpeg")
    ready = bool(whisper and Path(whisper).is_file() and model and Path(model).is_file() and ffmpeg and Path(ffmpeg).is_file())
    return {"ready": ready, "whisper": whisper, "model": model, "ffmpeg": ffmpeg}


def status(settings):
    local = _local_tools()
    return {
        "voice_enabled": settings.get("voice_enabled", True),
        "voice_cloud_ready": bool(settings.get("voice_api_key")),
        "voice_local_stt_ready": local["ready"],
        "voice_browser_tts_ready": True,
        "voice_stt_model": settings.get("voice_stt_model", "gpt-transcribe"),
        "voice_tts_model": settings.get("voice_tts_model", "gpt-4o-mini-tts"),
        "voice_name": settings.get("voice_name", "marin"),
        "voice_policy": "cloud_first_local_fallback",
        "voice_privacy_note": "原始录音默认不保存；云端转写会把本次录音发送给已配置的语音服务。只在你核对并发送后保存文字。",
    }


def _decode_audio(value):
    require_object(value)
    mime = text_field(value.get("mime_type", ""), "音频格式", 100, True).split(";", 1)[0].lower()
    if mime not in MIME_EXTENSIONS:
        raise Problem("录音格式不支持，请使用 WebM、WAV、MP3、MP4 或 M4A")
    encoded = value.get("audio_base64", "")
    if not isinstance(encoded, str) or len(encoded) > MAX_AUDIO_BYTES * 2:
        raise Problem("录音过大，请缩短后重试", 413)
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise Problem("录音数据无效") from None
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise Problem("录音为空或超过 8 MB，请缩短后重试", 413)
    return audio, mime, MIME_EXTENSIONS[mime]


def _cloud(action, settings, **payload):
    request = {"action": action, "settings": settings, **payload}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.voice_transport"],
            cwd=Path(__file__).resolve().parent.parent,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=75,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Problem("云端语音请求超时或连接进程无法启动") from None
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise Problem("云端语音服务未返回有效结果") from None
    if proc.returncode or not result.get("ok"):
        raise Problem(result.get("error") or "云端语音服务调用失败")
    return result


def _local_transcribe(audio, extension):
    tools = _local_tools()
    if not tools["ready"]:
        raise Problem("本地语音兜底尚未配置")
    with tempfile.TemporaryDirectory(prefix="job_assistant_voice_") as directory:
        root = Path(directory)
        source, wave, output = root / f"input.{extension}", root / "input.wav", root / "transcript"
        source.write_bytes(audio)
        try:
            converted = subprocess.run(
                [tools["ffmpeg"], "-nostdin", "-loglevel", "error", "-i", str(source), "-ar", "16000", "-ac", "1", str(wave)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False,
            )
            if converted.returncode:
                raise Problem("本地音频转换失败")
            transcribed = subprocess.run(
                [tools["whisper"], "-m", tools["model"], "-f", str(wave), "-l", "zh", "-otxt", "-of", str(output)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False,
            )
            target = output.with_suffix(".txt")
            if transcribed.returncode or not target.is_file():
                raise Problem("本地语音转写失败")
            text = target.read_text(encoding="utf-8", errors="replace").strip()
        except subprocess.TimeoutExpired:
            raise Problem("本地语音转写超时") from None
    if not text:
        raise Problem("没有识别到可用文字")
    return text


def transcribe(settings, value):
    if not settings.get("voice_enabled", True):
        raise Problem("语音功能已关闭", 409)
    audio, mime, extension = _decode_audio(value)
    cloud_error = None
    if settings.get("voice_api_key"):
        try:
            result = _cloud("transcribe", settings, audio_base64=base64.b64encode(audio).decode(), mime_type=mime, extension=extension)
            text = text_field(result.get("text", ""), "转写文字", 12000, True)
            return {"text": text, "source": "cloud", "model": settings.get("voice_stt_model", "gpt-transcribe"), "audio_saved": False}
        except Problem as exc:
            cloud_error = str(exc)
    try:
        text = _local_transcribe(audio, extension)
        return {"text": text, "source": "local", "model": "whisper.cpp", "audio_saved": False,
                "fallback": bool(cloud_error), "note": "云端转写不可用，已自动使用本地模型。" if cloud_error else "已使用本地模型。"}
    except Problem:
        if cloud_error:
            raise Problem(cloud_error + "；本地语音兜底也尚不可用，请编辑文字或检查设置") from None
        raise Problem("请先配置云端语音密钥，或安装 whisper.cpp 本地兜底；文字输入仍可使用", 409) from None


def speech(settings, value):
    if not settings.get("voice_enabled", True):
        raise Problem("语音功能已关闭", 409)
    text = text_field(value.get("text", ""), "朗读文字", 4000, True)
    if not settings.get("voice_api_key"):
        raise Problem("云端语音播放未配置，请使用浏览器本地朗读", 409)
    result = _cloud("speech", settings, text=text)
    try:
        audio = base64.b64decode(result.get("audio_base64", ""), validate=True)
    except (ValueError, TypeError):
        raise Problem("云端语音服务返回了无效音频") from None
    if not audio or len(audio) > 12 * 1024 * 1024:
        raise Problem("云端语音结果为空或过大")
    return audio, result.get("content_type", "audio/mpeg")
