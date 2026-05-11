import argparse
import time
import uuid
from pathlib import Path
from typing import Any


def _torch_dtype_from_precision(precision: str) -> Any:
    import torch
    normalized = precision.strip().lower()
    if normalized in {"bf16", "bfloat16"}:
        return torch.bfloat16
    if normalized in {"fp16", "float16", "half"}:
        return torch.float16
    if normalized in {"fp32", "float32", "full"}:
        return torch.float32
    if normalized == "auto":
        return "auto"
    raise ValueError(f"unsupported precision: {precision}")


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _render_chat_prompt(tokenizer: Any, messages: list[Any]) -> str:
    payload = [
        {"role": message.role, "content": _normalize_content(message.content)}
        for message in messages
    ]
    try:
        return tokenizer.apply_chat_template(
            payload,
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception:
        return "\n".join(f"{item['role']}: {item['content']}" for item in payload)


def _model_input_device(model: Any) -> Any:
    import torch

    try:
        return next(model.parameters()).device
    except StopIteration:
        return torch.device("cpu")


def _build_app(
    *,
    model_path: str,
    default_temperature: float,
    default_max_tokens: int,
    tokenizer: Any,
    model: Any,
) -> Any:
    import torch
    from fastapi import FastAPI, HTTPException
    from starlette.requests import Request

    app = FastAPI(title="LoopTutor Local LLM")
    served_model_id = Path(model_path).resolve().name
    created_at = int(time.time())

    if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
        tokenizer.pad_token = tokenizer.eos_token

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": served_model_id,
                    "object": "model",
                    "created": created_at,
                    "owned_by": "local",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> dict[str, Any]:
        body = await request.json()
        messages = body.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="messages must not be empty")
        temperature = body.get("temperature", default_temperature)
        max_tokens = body.get("max_tokens", default_max_tokens)

        prompt = _render_chat_prompt(tokenizer, [type('M',(),{'role':m.get('role',''),'content':m.get('content','')})() for m in messages])
        inputs = tokenizer(prompt, return_tensors="pt")
        input_device = _model_input_device(model)
        inputs = {key: value.to(input_device) for key, value in inputs.items()}
        input_token_count = int(inputs["input_ids"].shape[-1])

        generation_args: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "do_sample": temperature > 0,
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
        }
        if temperature > 0:
            generation_args["temperature"] = temperature
            generation_args["top_p"] = 0.95

        with torch.no_grad():
            outputs = model.generate(**inputs, **generation_args)

        generated_tokens = outputs[0][input_token_count:]
        content = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
        completion_token_count = int(generated_tokens.shape[-1])
        response_model = body.get("model") or served_model_id

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": input_token_count,
                "completion_tokens": completion_token_count,
                "total_tokens": input_token_count + completion_token_count,
            },
        }

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local OpenAI-compatible LLM server.")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--precision", default="bf16")
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--max-tokens", type=int, default=2048)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    import torch
    import uvicorn
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_path = Path(args.model_path).expanduser()
    dtype = _torch_dtype_from_precision(args.precision)

    print(f"[local-llm] loading tokenizer from {model_path}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), trust_remote_code=True)

    print(f"[local-llm] loading model from {model_path} with precision={args.precision}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        trust_remote_code=True,
        torch_dtype=dtype,
    )
    model.eval()
    print(f"[local-llm] model loaded; serving on 127.0.0.1:{args.port}", flush=True)

    app = _build_app(
        model_path=str(model_path),
        default_temperature=args.temperature,
        default_max_tokens=args.max_tokens,
        tokenizer=tokenizer,
        model=model,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
