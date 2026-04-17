import time
import logging
from faster_whisper import WhisperModel

logging.basicConfig(
    filename='asr_run.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

_model_instance = None

def get_asr_model():
    global _model_instance
    if _model_instance is None:
        _model_instance = WhisperModel("base", device="cpu", compute_type="float32")
    return _model_instance

def speech_to_text(audio_file):
    try:
        start = time.time()
        model = get_asr_model()
        
        segments, info = model.transcribe(
            audio_file,
            language="zh",
            vad_filter=True,
            word_timestamps=True
        )
        
        text = "".join([seg.text for seg in segments])
        cost = time.time() - start
        
        logging.info(f"识别成功，耗时：{cost:.2f}s，结果：{text}")
        return text
    except Exception as e:
        logging.error(f"识别失败：{str(e)}")
        return ""

if __name__ == "__main__":
    text = speech_to_text("打开灯.wav")
    print("识别结果：", text)