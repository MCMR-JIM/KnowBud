# ASR/TTS Docker Stack

This compose file starts local ASR and TTS services used by `VoiceIOSkill`.

## Start

```bash
docker compose -f docker/asr_tts/docker-compose.yml up -d
```

## Stop

```bash
docker compose -f docker/asr_tts/docker-compose.yml down
```

## Endpoints

- TTS: `http://127.0.0.1:5501`
  - `GET /health`
  - `POST /tts`
- ASR: `http://127.0.0.1:9000`
  - `POST /asr`
  - `POST /detect-language`

## Project env suggestion

Use the following in `.env`:

```env
VOICE_BACKEND_MODE=docker
ASR_SERVICE_URL=http://127.0.0.1:9000
TTS_SERVICE_URL=http://127.0.0.1:5501
```

If you want automatic fallback to local libraries, set `VOICE_BACKEND_MODE=auto`.
