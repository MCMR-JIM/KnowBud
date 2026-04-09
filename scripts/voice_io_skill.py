from faster_whisper import WhisperModel
import edge_tts

def audio_to_text(audio_file):
    model = WhisperModel("base", device="cpu", compute_type="float32")
    segments, info = model.transcribe(audio_file, language="zh")
    text = "".join([seg.text for seg in segments])
    return text

def text_to_audio(text, output_file="output.mp3"):
    text = text.replace("。", "。<break time='500ms'/>")
    tts = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    tts.save(output_file)
    return output_file

if __name__ == "__main__":
    print("语音B模块运行成功")
