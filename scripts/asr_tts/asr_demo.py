import argparse
import time
from pathlib import Path

from faster_whisper import WhisperModel
import httpx


_model_instance = None


def get_asr_model(model_size: str) -> WhisperModel:
    global _model_instance
    if _model_instance is None:
        _model_instance = WhisperModel(model_size, device="cpu", compute_type="float32")
    return _model_instance


def speech_to_text(audio_file: str, model_size: str) -> str:
    start = time.time()
    model = get_asr_model(model_size)
    segments, _ = model.transcribe(
        audio_file,
        language="zh",
        vad_filter=True,
        word_timestamps=True,
    )
    text = "".join(seg.text for seg in segments).strip()
    cost = time.time() - start
    print(f"ASR success in {cost:.2f}s")
    return text


def speech_to_text_docker(audio_path: Path, service_url: str, language: str) -> str:
    endpoint = f"{service_url.rstrip('/')}/asr"
    content_type = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }.get(audio_path.suffix.lower(), "application/octet-stream")
    with audio_path.open("rb") as f:
        files = {"audio_file": (audio_path.name, f, content_type)}
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                endpoint,
                params={"task": "transcribe", "language": language, "output": "json"},
                files=files,
            )
            response.raise_for_status()

    payload = response.json()
    if isinstance(payload, dict):
        text = payload.get("text", "")
        if isinstance(text, str):
            return text.strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Whisper ASR demo")
    parser.add_argument("audio", help="输入音频文件路径")
    parser.add_argument("--model", default="base", help="Whisper 模型大小")
    parser.add_argument("--backend", choices=["auto", "local", "docker"], default="auto", help="ASR 后端")
    parser.add_argument("--service-url", default="http://127.0.0.1:9000", help="Docker ASR 服务地址")
    parser.add_argument("--language", default="zh", help="ASR 语言代码")
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if args.backend in {"auto", "docker"} and args.service_url:
        try:
            text = speech_to_text_docker(audio_path, args.service_url, args.language)
            print(f"ASR text (docker): {text}")
            return
        except Exception as exc:
            if args.backend == "docker":
                print(f"ASR docker failed, fallback local: {exc}")

    text = speech_to_text(str(audio_path), args.model)
    print(f"ASR text: {text}")


if __name__ == "__main__":
    main()
