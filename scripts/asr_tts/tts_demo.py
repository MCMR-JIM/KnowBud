import argparse
import asyncio
from pathlib import Path

import edge_tts
import httpx


async def run_tts(text: str, output: Path, voice: str) -> None:
    payload = f"<speak>{text}</speak>"
    tts = edge_tts.Communicate(payload, voice)
    await tts.save(str(output))


def run_tts_docker(text: str, output: Path, voice: str, service_url: str) -> None:
    endpoint = f"{service_url.rstrip('/')}/tts"
    with httpx.Client(timeout=60.0) as client:
        response = client.post(endpoint, json={"text": text, "voice": voice})
        response.raise_for_status()
    output.write_bytes(response.content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge TTS demo")
    parser.add_argument("--text", default="你好，这是默认语音", help="要转换的文字")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural", help="语音角色")
    parser.add_argument("--backend", choices=["auto", "local", "docker"], default="auto", help="TTS 后端")
    parser.add_argument("--service-url", default="http://127.0.0.1:5501", help="Docker TTS 服务地址")
    parser.add_argument("--output", default="artifacts/audio/tts_demo.mp3", help="输出 mp3 路径")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        if args.backend in {"auto", "docker"} and args.service_url:
            try:
                run_tts_docker(args.text, output, args.voice, args.service_url)
                print(f"TTS success (docker): {output}")
                return
            except Exception as exc:
                if args.backend == "docker":
                    print(f"TTS docker failed, fallback local: {exc}")

        asyncio.run(run_tts(args.text, output, args.voice))
        print(f"TTS success: {output}")
    except Exception as exc:
        print(f"TTS failed: {exc}")


if __name__ == "__main__":
    main()
