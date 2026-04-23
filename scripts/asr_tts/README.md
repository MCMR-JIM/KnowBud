# ASR / TTS Demo Scripts

- `tts_demo.py`: text to mp3, supports `local` / `docker` / `auto`
- `asr_demo.py`: audio to text, supports `local` / `docker` / `auto`

Examples:

```bash
python scripts/asr_tts/tts_demo.py --text "你好，这是试听" --output artifacts/audio/tts_demo.mp3
python scripts/asr_tts/asr_demo.py artifacts/audio/tts_demo.mp3 --model base
```

Use Docker backend explicitly:

```bash
python scripts/asr_tts/tts_demo.py --backend docker --service-url http://127.0.0.1:5501 --text "你好"
python scripts/asr_tts/asr_demo.py artifacts/audio/tts_demo.mp3 --backend docker --service-url http://127.0.0.1:9000
```
