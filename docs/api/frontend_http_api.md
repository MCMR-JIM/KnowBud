# Frontend HTTP API (Reserved)

本文件定义了前后端分离时可直接接入的后端 HTTP 接口。

## 运行方式

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8090 --reload
```

启动后可访问：

- Swagger UI: `http://127.0.0.1:8090/docs`
- OpenAPI JSON: `http://127.0.0.1:8090/openapi.json`

## 设计原则

- 语音对话接口优先低延迟：一轮请求返回文本答复与可播放音频（Base64）。
- 奖励时间窗是后端状态，不依赖前端控制。
- 图谱扩展与提案生命周期全部由后端状态维护。

## 接口清单

### 1) 健康检查

- `GET /health`

响应示例：

```json
{
  "ok": true,
  "service": "looptutor-frontend-api",
  "version": "0.1.0",
  "arch_mode": "agent"
}
```

### 2) 获取会话状态

- `GET /v1/session/state`

返回内容包含：

- `profile`: 学生信息
- `learning`: 当前主题、阶段、积分、探索时间窗
- `topics`: 当前知识网节点列表
- `proposals`: 图谱提案生命周期记录
- `mastery`: 节点掌握度（深度/稳定）

### 3) 文本输入一轮对话

- `POST /v1/session/input/text`
- Body:

```json
{
  "text": "恐龙为什么会灭绝？"
}
```

响应示例：

```json
{
  "user_text": "恐龙为什么会灭绝？",
  "reply_text": "...",
  "earned_points": 20,
  "reply_audio_base64": "...",
  "reply_audio_mime": "audio/mpeg",
  "current_topic_id": "demo_01",
  "current_phase": "LEARNING",
  "total_score": 120,
  "explore_window_until": null
}
```

### 4) 语音输入一轮对话

- `POST /v1/session/input/audio`
- Form-Data:
  - `file`: 音频文件（wav/mp3 等）

响应会多一个 `recognized_text` 字段，用于前端展示 ASR 结果。

### 5) 家长端推送复习主题

- `POST /v1/session/review/push`
- Body:

```json
{
  "topic_id": "demo_01"
}
```

### 6) 获取知识网视图

- `GET /v1/knowledge/graph`

返回：

- `topics`
- `proposals`
- `mastery`

## 前端对接建议

- 聊天主循环统一用 `/v1/session/input/text` 或 `/v1/session/input/audio`。
- 前端本地播放语音时，用 `reply_audio_mime + reply_audio_base64` 解码为音频资源。
- 页面初始化时先拉 `/v1/session/state`，用于恢复当前主题、积分和探索窗口状态。
