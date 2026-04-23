# ASR/TTS 部署与使用指南

本指南将原有 Word 文档内容整理为可维护的 Markdown，并对脚本路径与命名做了统一。

## 1. 目标与链路

- ASR：语音转文字
- TTS：文字转语音
- 业务链路：`录音 -> ASR -> 回答生成 -> TTS -> 播放`

对应后端入口见：`src/services/session_backend.py`。

## 2. 环境准备

安装依赖：

```bash
pip install -r requirements.txt
```

复制环境变量模板：

```bash
copy .env.example .env
```

## 3. 本地部署（Local）

适用场景：不依赖容器，直接用本机 Python 环境。

`.env` 建议：

```env
VOICE_BACKEND_MODE=local
WHISPER_MODEL_SIZE=base
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

脚本验证：

```bash
python scripts/asr_tts/tts_demo.py --backend local --text "打开灯" --output artifacts/audio/tts_local_demo.mp3
python scripts/asr_tts/asr_demo.py artifacts/audio/tts_local_demo.mp3 --backend local --model base
```

## 4. Docker 部署（Recommended）

适用场景：与应用隔离运行，便于统一环境。

启动服务：

```bash
docker compose -f docker/asr_tts/docker-compose.yml up -d
```

停止服务：

```bash
docker compose -f docker/asr_tts/docker-compose.yml down
```

`.env` 建议：

```env
VOICE_BACKEND_MODE=docker
ASR_SERVICE_URL=http://127.0.0.1:9000
TTS_SERVICE_URL=http://127.0.0.1:5501
```

接口健康检查：

```bash
curl http://127.0.0.1:5501/health
curl http://127.0.0.1:9000/openapi.json
```

脚本验证：

```bash
python scripts/asr_tts/tts_demo.py --backend docker --service-url http://127.0.0.1:5501 --text "打开灯" --output artifacts/audio/tts_docker_demo.mp3
python scripts/asr_tts/asr_demo.py artifacts/audio/tts_docker_demo.mp3 --backend docker --service-url http://127.0.0.1:9000 --language zh
```

## 5. 自动模式（Auto）

`VOICE_BACKEND_MODE=auto` 时：

- 若配置了 `ASR_SERVICE_URL` / `TTS_SERVICE_URL`，优先走 Docker 服务
- 服务异常时自动回退本地实现

该逻辑见：`src/skills/voice_io_skill.py`。

## 6. ASR 输入规范（前端建议）

- 格式：`WAV` / `MP3`
- 采样率：`16000 Hz`
- 声道：`Mono`
- 单条语音时长：建议不超过 `30s`
- 分段策略：基于静音自动切分

## 7. 产物与日志

- 入站音频：`artifacts/audio/incoming/`
- 出站音频：`artifacts/audio/outgoing/`
- 推理日志：`logs/`

以上目录均为运行产物，已在 `.gitignore` 中处理。

## 8. 命名与迁移说明

- 原 `w1_whisper_transcribe_demo.py`、`w1_edge_tts_demo.py` 已迁移到：
  - `scripts/asr_tts/asr_demo.py`
  - `scripts/asr_tts/tts_demo.py`
- 原文档已规范命名为：`docs/asr_tts/asr_tts_deployment_guide.docx`
