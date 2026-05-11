from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts
import tempfile
import uvicorn
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"

@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    # ================= 🌟 真人化核心配置 =================
    # 语速：-10% = 更慢更温柔（儿童专属）
    # 音调：+5Hz = 更可爱，无机械感
    # 音量：100%
    RATE = "-10%"
    PITCH = "+5Hz"
    VOLUME = "+100%"

    # 生成语音（带真人参数）
    communicate = edge_tts.Communicate(
        text=req.text,
        voice=req.voice,
        rate=RATE,
        pitch=PITCH,
        volume=VOLUME
    )
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.close()
    
    await communicate.save(temp_file.name)
    return FileResponse(temp_file.name, media_type="audio/mpeg")

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5501)