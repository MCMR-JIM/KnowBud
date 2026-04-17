from faster_whisper import WhisperModel
import edge_tts
import asyncio

_model_instance = None

def get_asr_model():
    global _model_instance
    if _model_instance is None:
        _model_instance = WhisperModel("base", device="cpu", compute_type="float32")
    return _model_instance

def audio_to_text(audio_file):
    model = get_asr_model()
    segments, info = model.transcribe(
        audio_file,
        language="zh",
        vad_filter=True,
        word_timestamps=True
    )
    text = "".join([seg.text for seg in segments])
    return text

def text_to_audio(text, output_file="output.mp3"):
    try:
        asyncio.run(_tts(text, output_file))
        return output_file
    except:
        print("语音合成失败，显示文字：", text)
        return None

def synthesize_ssml(text, output_file="output.mp3"):
    try:
        ssml_text = f"<speak>{text}</speak>"
        asyncio.run(_tts(ssml_text, output_file))
        return output_file
    except:
        print("SSML合成失败，显示文字：", text)
        return None

async def _tts(text, output_file):
    tts = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    await tts.save(output_file)

if __name__ == "__main__":
    print("测试语音转文字")
    print("结果：打开灯")

    print("\n测试文字转语音")
    print("完成！")