from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts
import tempfile
import uvicorn
import os

app = FastAPI()

# 允许跨域请求，防止前端报 Network Error
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
    # 调用微软 Edge TTS 引擎
    communicate = edge_tts.Communicate(req.text, req.voice)
    # 创建临时音频文件
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.close()
    # 将生成的语音保存到临时文件
    await communicate.save(temp_file.name)
    # 返回音频流给前端
    return FileResponse(temp_file.name, media_type="audio/mpeg")

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5501)