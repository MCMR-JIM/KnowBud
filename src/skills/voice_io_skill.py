import io
import asyncio
from xml.sax.saxutils import escape
from faster_whisper import WhisperModel
import edge_tts

from src.skills.base_skill import BaseSkill, SkillContext

class VoiceIOSkill(BaseSkill):
    """语音 IO 技能：负责语音识别 (ASR) 和语音合成 (TTS)"""
    
    name = "VoiceIOSkill"
    version = "1.0.0"

    def __init__(self, ctx: SkillContext, *, whisper_model_size: str) -> None:
        self.ctx = ctx
        self.whisper_model_size = whisper_model_size
        
        # 加载 Whisper 模型。
        # 为了保证在你目前的电脑上绝对能跑起来不报错，我们默认使用 cpu 和 int8 模式。
        # 第一次运行可能会在后台悄悄下载模型权重，稍等即可。
        self.asr_model = WhisperModel(
            self.whisper_model_size, 
            device="cpu", 
            compute_type="int8"
        )

    def transcribe(self, audio_bytes: bytes, *, mime: str | None = None) -> str:
        """耳朵：将录音字节流转换成文本"""
        if not audio_bytes:
            return ""
            
        try:
            # faster-whisper 支持直接读取类似文件的内存对象
            audio_file = io.BytesIO(audio_bytes)
            # beam_size 设为 5 能提高识别准确率
            segments, info = self.asr_model.transcribe(audio_file, beam_size=5)
            
            # 把所有识别出来的片段拼成完整的一句话
            text = "".join([segment.text for segment in segments])
            return text.strip()
        except Exception as e:
            # 规格书要求：失败抛出异常或返回空串，这里选择安全的降级返回空串
            print(f"[VoiceIOSkill] ASR 识别失败: {e}")
            return ""

    def synthesize_plain(self, text: str, *, voice: str) -> bytes:
        """嘴巴：把普通文本合成语音字节流 (mp3格式)"""
        if not text:
            return b""
        # 因为 edge-tts 是异步的，而我们的函数是同步的，所以用 asyncio.run 包装一下
        return asyncio.run(self._async_synthesize(text, voice))

    def synthesize_ssml(self, ssml: str, *, voice: str) -> bytes:
        """嘴巴：带感情/停顿的 SSML 语音合成"""
        if not ssml:
            return b""
        # Edge-TTS 的 Communicate 接口可以直接处理包含简单 XML 标签的文本
        return asyncio.run(self._async_synthesize(ssml, voice))

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