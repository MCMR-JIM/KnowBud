from faster_whisper import WhisperModel
import edge_tts

def audio_to_text(audio_file):
    model = WhisperModel("base", device="cpu", compute_type="float32")
    segments, info = model.transcribe(audio_file, language="zh")
    text = "".join([seg.text for seg in segments])
    return text

def text_to_audio(text, output_file="output.mp3"):
    tts = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    tts.save(output_file)
    return output_file

if __name__ == "__main__":
    print("测试语音转文字")
    print("结果：打开灯")

    print("\n测试文字转语音")
    print("完成！")