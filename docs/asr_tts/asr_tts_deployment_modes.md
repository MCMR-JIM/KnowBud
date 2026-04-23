# ASR/TTS Deployment Modes

## Backend switch

`src/skills/voice_io_skill.py` uses `VOICE_BACKEND_MODE`:

- `local`: use local libraries only
- `docker`: try HTTP services first (`ASR_SERVICE_URL`, `TTS_SERVICE_URL`), fallback local
- `auto`: same as docker when URL exists, otherwise local

## Runtime call chain

1. `pages/1_Kids_Learning.py` captures voice/text input.
2. `SessionBackend.transcribe_audio()` saves incoming audio then calls ASR.
3. `SessionBackend.evaluate_student_answer()` computes reply + points.
4. `SessionBackend.synthesize_reply_audio()` generates TTS audio and stores artifact.
5. `SessionBackend.evaluate_and_speak()` returns `(reply, points, audio_bytes)` to UI.

## Artifact paths

- Incoming audio: `${AUDIO_ARTIFACT_ROOT}/incoming/`
- Outgoing audio: `${AUDIO_ARTIFACT_ROOT}/outgoing/`

These folders are ignored by git.
