import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger


LOCAL_LLM_PORT = 8000


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "gemma-3-4b-it"
    messages: list[ChatMessage]
    temperature: float = 0.6
    max_tokens: int = 2048
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = "chatcmpl-local"
    object: str = "chat.completion"
    created: int = 0
    model: str = "gemma-3-4b-it"
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


class LocalLLMServer:
    def __init__(self, settings: dict | None = None):
        self._settings = settings or {}
        self._model = None
        self._tokenizer = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._loaded = threading.Event()
        self._server_thread: threading.Thread | None = None

    def load(self) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        local = self._settings.get("local", {})
        model_path = local.get("model_path", "")
        if not model_path or not Path(model_path).exists():
            logger.warning(f"Local model path not found: {model_path}, using google/gemma-3-4b-it")
            model_path = "google/gemma-3-4b-it"

        precision = local.get("precision", "bf16")
        dtype = torch.bfloat16 if precision == "bf16" else torch.float16
        load_kwargs: dict[str, Any] = {"torch_dtype": dtype}

        gpu_mem_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3 if self._device == "cuda" else 0
        use_4bit = local.get("quantization") == "4bit" or (gpu_mem_gb > 0 and gpu_mem_gb < 10)

        if use_4bit and self._device == "cuda":
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            load_kwargs["quantization_config"] = bnb_config
        elif self._device == "cuda":
            load_kwargs["device_map"] = "auto"

        logger.info(f"Loading model from {model_path} on {self._device} ({precision})")
        start = time.time()
        self._tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True, **load_kwargs)
        if self._device == "cpu":
            self._model = self._model.to(self._device)
        elapsed = time.time() - start
        logger.info(f"Model loaded in {elapsed:.1f}s on {self._device}")
        self._loaded.set()

    @property
    def is_ready(self) -> bool:
        return self._loaded.is_set()

    def generate(self, messages: list[dict], temperature: float = 0.6, max_tokens: int = 2048) -> str:
        if not self.is_ready:
            raise RuntimeError("Model not loaded yet")
        self._loaded.wait()

        tokenizer = self._tokenizer
        model = self._model

        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=8192)
        if self._device == "cuda":
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                top_p=0.95,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )

        generated = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return generated.strip()


_global_server: LocalLLMServer | None = None


def _build_app() -> FastAPI:
    app = FastAPI(title="LoopTutor Local LLM")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        if _global_server is None:
            raise HTTPException(status_code=503, detail="server not started")
        return {"status": "ready" if _global_server.is_ready else "loading"}

    @app.get("/v1/models")
    def list_models():
        return {"object": "list", "data": [{"id": "gemma-3-4b-it", "object": "model"}]}

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    def chat_completions(req: ChatCompletionRequest):
        if _global_server is None or not _global_server.is_ready:
            raise HTTPException(status_code=503, detail="model not ready")
        msgs = [{"role": m.role, "content": m.content} for m in req.messages]
        content = _global_server.generate(msgs, temperature=req.temperature, max_tokens=req.max_tokens)
        return ChatCompletionResponse(
            id="chatcmpl-local",
            created=int(time.time()),
            model=req.model,
            choices=[ChatCompletionChoice(message=ChatMessage(role="assistant", content=content))],
            usage=ChatCompletionUsage(),
        )

    return app


def start_local_llm_server(settings: dict, *, blocking: bool = False) -> None:
    global _global_server
    if _global_server is not None:
        return

    _global_server = LocalLLMServer(settings)

    def _run() -> None:
        _global_server.load()
        app = _build_app()
        uvicorn.run(app, host="127.0.0.1", port=LOCAL_LLM_PORT, log_level="warning")

    if blocking:
        _run()
    else:
        _global_server._server_thread = threading.Thread(target=_run, name="local-llm", daemon=True)
        _global_server._server_thread.start()
