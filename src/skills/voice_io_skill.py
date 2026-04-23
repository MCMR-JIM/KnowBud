from __future__ import annotations

import io
import os
import asyncio
from xml.sax.saxutils import escape
from faster_whisper import WhisperModel
import edge_tts
import httpx

from src.skills.base_skill import BaseSkill, SkillContext

class VoiceIOSkill(BaseSkill):
    """语音 IO 技能：负责语音识别 (ASR) 和语音合成 (TTS)"""
    
    name = "VoiceIOSkill"
    version = "1.0.0"

    def __init__(self, ctx: SkillContext, *, whisper_model_size: str) -> None:
        self.ctx = ctx
        self.whisper_model_size = whisper_model_size
        mode = os.getenv("VOICE_BACKEND_MODE", "auto").strip().lower()
        self.voice_backend_mode = mode if mode in {"auto", "local", "docker"} else "auto"
        self.asr_service_url = os.getenv("ASR_SERVICE_URL", "").rstrip("/")
        self.tts_service_url = os.getenv("TTS_SERVICE_URL", "").rstrip("/")
        self.default_voice = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
        self.asr_model: WhisperModel | None = None

    def _create_local_asr_model(self) -> WhisperModel:
        # 仅在未配置 Docker ASR 服务时加载本地 Whisper，避免无谓的模型初始化开销。
        return WhisperModel(
            self.whisper_model_size,
            device="cpu",
            compute_type="int8"
        )

    def transcribe(self, audio_bytes: bytes, *, mime: str | None = None) -> str:
        """耳朵：将录音字节流转换成文本"""
        if not audio_bytes:
            return ""

        if self._should_try_asr_service():
            try:
                return self._transcribe_via_service(audio_bytes, mime=mime)
            except Exception as exc:
                print(f"[VoiceIOSkill] ASR 服务不可用，回退本地模型: {exc}")
        elif self.voice_backend_mode == "docker":
            print("[VoiceIOSkill] ASR_SERVICE_URL 未配置，回退本地模型")

        try:
            return self._transcribe_via_local(audio_bytes)
        except Exception as e:
            # 规格书要求：失败抛出异常或返回空串，这里选择安全的降级返回空串
            print(f"[VoiceIOSkill] ASR 识别失败: {e}")
            return ""

    def synthesize_plain(self, text: str, *, voice: str) -> bytes:
        """嘴巴：把普通文本合成语音字节流 (mp3格式)"""
        if not text:
            return b""
        if self._should_try_tts_service():
            try:
                return self._synthesize_via_service(text, voice=voice)
            except Exception as exc:
                print(f"[VoiceIOSkill] TTS 服务不可用，回退 edge-tts: {exc}")
        elif self.voice_backend_mode == "docker":
            print("[VoiceIOSkill] TTS_SERVICE_URL 未配置，回退 edge-tts")
        # 因为 edge-tts 是异步的，而我们的函数是同步的，所以用 asyncio.run 包装一下
        return asyncio.run(self._async_synthesize(text, voice))

    def synthesize_ssml(self, ssml: str, *, voice: str) -> bytes:
        """嘴巴：带感情/停顿的 SSML 语音合成"""
        if not ssml:
            return b""
        if self._should_try_tts_service():
            try:
                return self._synthesize_via_service(ssml, voice=voice)
            except Exception as exc:
                print(f"[VoiceIOSkill] TTS 服务不可用，回退 edge-tts: {exc}")
        elif self.voice_backend_mode == "docker":
            print("[VoiceIOSkill] TTS_SERVICE_URL 未配置，回退 edge-tts")
        # Edge-TTS 的 Communicate 接口可以直接处理包含简单 XML 标签的文本
        return asyncio.run(self._async_synthesize(ssml, voice))

    def _should_try_asr_service(self) -> bool:
        return self.voice_backend_mode in {"auto", "docker"} and bool(self.asr_service_url)

    def _should_try_tts_service(self) -> bool:
        return self.voice_backend_mode in {"auto", "docker"} and bool(self.tts_service_url)

    def _transcribe_via_local(self, audio_bytes: bytes) -> str:
        audio_file = io.BytesIO(audio_bytes)
        model = self.asr_model or self._create_local_asr_model()
        self.asr_model = model
        segments, _ = model.transcribe(audio_file, beam_size=5)
        text = "".join(segment.text for segment in segments)
        return text.strip()

    def _transcribe_via_service(self, audio_bytes: bytes, *, mime: str | None = None) -> str:
        filename = "audio.wav"
        content_type = mime or "audio/wav"
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self.asr_service_url}/asr",
                params={"task": "transcribe", "language": "zh", "output": "json"},
                files={"audio_file": (filename, audio_bytes, content_type)},
            )
            response.raise_for_status()

        payload = response.json()
        if isinstance(payload, dict):
            text = payload.get("text", "")
            if isinstance(text, str):
                return text.strip()
        return ""

    def _synthesize_via_service(self, text: str, *, voice: str) -> bytes:
        payload = {"text": text, "voice": voice or self.default_voice}
        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{self.tts_service_url}/tts", json=payload)
            response.raise_for_status()
            return response.content

    async def _async_synthesize(self, text: str, voice: str) -> bytes:
        """内部异步工作马：真正去调用 edge-tts 下载音频的地方"""
        communicate = edge_tts.Communicate(text, voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    @staticmethod
    def inject_breaks(text: str, seconds: float = 1.0) -> str:
        """给长句子加停顿：在句号后插入 <break time='Xs'/>"""
        # 第一步：把特殊的 XML 字符转义，防止破坏 SSML 结构
        escaped_text = escape(text)
        
        break_tag = f"<break time='{seconds}s'/>"
        # 替换中文和英文句号，加上停顿标签
        escaped_text = escaped_text.replace("。", f"。{break_tag}")
        escaped_text = escaped_text.replace(". ", f". {break_tag}")
        
        # 我们可以用 <speak> 标签把整个文本包起来，符合 SSML 规范
        return f"<speak>{escaped_text}</speak>"
