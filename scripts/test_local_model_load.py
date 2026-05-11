import json
import traceback
from pathlib import Path


def _load_settings() -> dict:
    root = Path(__file__).resolve().parents[1]
    settings_path = root / "data" / "llm_settings.json"
    with settings_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    try:
        settings = _load_settings()
        local_settings = settings.get("local") or {}
        model_path = str(local_settings.get("model_path") or "").strip()
        if not model_path:
            raise RuntimeError("local.model_path is empty in data/llm_settings.json")

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        print("tokenizer load OK")

        dtype_name = str(local_settings.get("precision") or "bf16").lower()
        torch_dtype = {
            "bf16": torch.bfloat16,
            "bfloat16": torch.bfloat16,
            "fp16": torch.float16,
            "float16": torch.float16,
            "fp32": torch.float32,
            "float32": torch.float32,
        }.get(dtype_name)

        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
            device_map="auto",
        )
        model.eval()
        print("model load OK")

        prompt = "Say hello in one short sentence."
        inputs = tokenizer(prompt, return_tensors="pt")
        target_device = next(model.parameters()).device
        inputs = {key: value.to(target_device) for key, value in inputs.items()}
        pad_token_id = tokenizer.pad_token_id
        if pad_token_id is None:
            pad_token_id = tokenizer.eos_token_id
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=24,
                do_sample=False,
                pad_token_id=pad_token_id,
            )
        _text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        print("one completion OK")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
