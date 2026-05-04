FROM python:3.9-slim
WORKDIR /app

# 安装必要的 Python 依赖库
RUN pip install fastapi uvicorn edge-tts pydantic

# 把我们刚刚写的 server.py 复制进容器
COPY server.py .

# 暴露 5501 端口
EXPOSE 5501

# 启动服务
CMD ["python", "server.py"]