from __future__ import annotations

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import tkinter.filedialog
import tkinter as tk
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Form, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/settings", tags=["settings"])


@router.get("/scan-models")
def scan_existing_models():
    """Scan HF cache and return which models are already downloaded."""
    from huggingface_hub import scan_cache_dir

    found: dict[str, str] = {}
    try:
        hf_cache_info = scan_cache_dir()
        for repo in hf_cache_info.repos:
            for model_key, model_def in LLM_MODELS.items():
                if model_def["repo_id"] in repo.repo_id:
                    snapshots = list(repo.repo_path.glob("snapshots/*"))
                    if snapshots:
                        found[model_key] = str(snapshots[0])
                        break
    except Exception:
        pass

    return {"models": found}


@router.get("/browse-folder")
def browse_folder():
    """Open native file dialog and return absolute path of selected folder."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = tkinter.filedialog.askdirectory(title="选择模型文件夹")
    root.destroy()
    if not path:
        raise HTTPException(status_code=400, detail="未选择文件夹")
    return {"path": os.path.normpath(path)}


LLM_MODELS: dict[str, dict[str, str]] = {
    "gemma-4b": {
        "label": "Gemma-3-4B",
        "size": "~8 GB",
        "vram": "~8 GB (bf16)",
        "gpu": "RTX 3060+",
        "repo_id": "google/gemma-3-4b-it",
        "description": "Google 多模态模型，支持图文输入",
    },
    "qwen-7b": {
        "label": "Qwen2.5-VL-7B",
        "size": "~14 GB",
        "vram": "~14 GB (bf16)",
        "gpu": "RTX 4080+",
        "repo_id": "Qwen/Qwen2.5-VL-7B-Instruct",
        "description": "阿里多模态模型，7B 参数，中英双语",
    },
    "gemma-12b": {
        "label": "Gemma-3-12B",
        "size": "~24 GB",
        "vram": "~24 GB (bf16)",
        "gpu": "RTX 4090 / 2x RTX 3090",
        "repo_id": "google/gemma-3-12b-it",
        "description": "Google 多模态模型，12B 参数，更强推理",
    },
    "qwen-27b": {
        "label": "Qwen3.6-27B",
        "size": "~54 GB",
        "vram": "~54 GB (bf16)",
        "gpu": "2x RTX 4090 / A100",
        "repo_id": "Qwen/Qwen3-27B",
        "description": "阿里旗舰大模型，27B 参数",
    },
}

SETTINGS_FILE = Path(os.getenv("DATA_ROOT", "./data")) / "llm_settings.json"
DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "remote",
    "remote": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
    },
    "local": {
        "model_path": "",
        "precision": "bf16",
        "temperature": 0.1,
        "timeout_sec": 15,
        "max_tokens": 2048,
    },
}

download_progress: dict[str, float] = {}
download_state: dict[str, str] = {}
download_speed: dict[str, float] = {}
download_lock = threading.Lock()


def _ensure_settings_dir() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_settings() -> dict[str, Any]:
    _ensure_settings_dir()
    if not SETTINGS_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_SETTINGS.copy()
    merged = DEFAULT_SETTINGS.copy()
    merged.update(data)
    return merged


def _save_settings(data: dict[str, Any]) -> None:
    _ensure_settings_dir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def _detect_gpu() -> dict[str, Any]:
    info: dict[str, Any] = {"cuda_available": False, "gpu_name": "", "vram_total_gb": 0, "vram_free_gb": 0}

    try:
        import torch

        if torch.cuda.is_available():
            info["cuda_available"] = True
            info["gpu_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            info["vram_total_gb"] = round(props.total_memory / (1024**3), 1)
            reserved = torch.cuda.memory_reserved(0) if torch.cuda.is_initialized() else 0
            info["vram_free_gb"] = round((props.total_memory - reserved) / (1024**3), 1)
            return info
    except ImportError:
        pass

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 3:
                info["cuda_available"] = True
                info["gpu_name"] = parts[0].strip()
                info["vram_total_gb"] = round(float(parts[1].strip()) / 1024, 1)
                info["vram_free_gb"] = round(float(parts[2].strip()) / 1024, 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return info


@router.get("/gpu")
def get_gpu_info() -> dict[str, Any]:
    return _detect_gpu()


@router.get("")
def get_settings() -> dict[str, Any]:
    return _load_settings()


@router.post("")
def save_settings(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if payload is None:
        raise HTTPException(status_code=400, detail="request body required")
    settings = _load_settings()
    if "mode" in payload:
        settings["mode"] = payload["mode"]
    if "remote" in payload:
        settings["remote"].update(payload["remote"] or {})
    if "local" in payload:
        settings["local"].update(payload["local"] or {})
    _save_settings(settings)
    logger.info("settings saved", extra={"mode": settings["mode"]})
    return settings


@router.get("/models")
def list_models() -> dict[str, Any]:
    return {"models": LLM_MODELS}


def _hf_download_worker(model_key: str, repo_id: str, download_path: str) -> None:
    """Custom HF downloader with pause/resume/cancel via traffic monitoring."""
    import time as _time
    import httpx
    from huggingface_hub import HfApi, hf_hub_url

    try:
        api = HfApi()
        repo_info = api.repo_info(repo_id=repo_id, repo_type="model")
        files = repo_info.siblings

        total_size = sum(f.size or 0 for f in files)
        if total_size == 0:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                for f in files:
                    try:
                        url = hf_hub_url(repo_id=repo_id, filename=f.rfilename, repo_type="model")
                        resp = client.head(url)
                        if "Content-Length" in resp.headers:
                            f.size = int(resp.headers["Content-Length"])
                            total_size += f.size
                    except Exception:
                        pass

        downloaded_size = 0
        target_dir = Path(download_path)
        target_dir.mkdir(parents=True, exist_ok=True)

        for file_info in files:
            if download_state.get(model_key) == "cancelled":
                raise Exception("Download cancelled by user")

            while download_state.get(model_key) == "paused":
                _time.sleep(0.5)
                if download_state.get(model_key) == "cancelled":
                    raise Exception("Download cancelled by user")

            filename = file_info.rfilename
            file_size = file_info.size or 0
            target_path = target_dir / filename
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if target_path.exists() and target_path.stat().st_size == file_size:
                downloaded_size += file_size
                if total_size > 0:
                    with download_lock:
                        download_progress[model_key] = min(int((downloaded_size / total_size) * 100), 99)
                continue

            url = hf_hub_url(repo_id=repo_id, filename=filename, repo_type="model")
            file_downloaded = target_path.stat().st_size if target_path.exists() else 0
            if file_downloaded > 0:
                downloaded_size += file_downloaded

            headers = {"Range": f"bytes={file_downloaded}-"} if file_downloaded > 0 else {}
            mode = "ab" if file_downloaded > 0 else "wb"

            with httpx.Client(timeout=None, follow_redirects=True) as client:
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code == 416:
                        continue
                    last_log = _time.time()
                    last_bytes = 0
                    with open(target_path, mode) as f:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            if download_state.get(model_key) == "cancelled":
                                raise Exception("Download cancelled by user")
                            while download_state.get(model_key) == "paused":
                                _time.sleep(0.5)
                                if download_state.get(model_key) == "cancelled":
                                    raise Exception("Download cancelled by user")
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            now = _time.time()
                            delta = now - last_log
                            if delta > 0.5 and total_size > 0:
                                with download_lock:
                                    download_progress[model_key] = min(int((downloaded_size / total_size) * 100), 99)
                                speed_bytes = (downloaded_size - last_bytes) / delta if delta > 0 else 0
                                with download_lock:
                                    download_speed[model_key] = speed_bytes / (1024 * 1024)  # MB/s
                                last_log = now
                                last_bytes = downloaded_size

        if download_state.get(model_key) == "cancelled":
            raise Exception("Download cancelled by user")

        with download_lock:
            download_progress[model_key] = 100
            download_state[model_key] = "completed"

    except Exception as exc:
        with download_lock:
            if download_state.get(model_key) == "cancelled":
                download_progress[model_key] = -2
            else:
                download_state[model_key] = "failed"
                download_progress[model_key] = -1
            download_state[model_key] = "failed" if download_state.get(model_key) != "cancelled" else "cancelled"


@router.post("/model/download")
def start_download(model: str = Form(...), path: str = Form(...)) -> dict[str, Any]:
    model_info = LLM_MODELS.get(model)
    if model_info is None:
        raise HTTPException(status_code=404, detail=f"unknown model: {model}")

    existing_state = download_state.get(model)
    if existing_state == "downloading":
        raise HTTPException(status_code=409, detail=f"model '{model}' is already downloading")

    download_path = path.strip()
    if not download_path:
        raise HTTPException(status_code=400, detail="download path is required")

    thread = threading.Thread(
        target=_hf_download_worker,
        args=(model, model_info["repo_id"], download_path),
        daemon=True,
    )
    thread.start()

    with download_lock:
        download_state[model] = "downloading"
        download_progress[model] = 0

    return {"model": model, "status": "downloading", "path": download_path}


@router.get("/model/download/status")
def get_download_status(model: str = Query(...)) -> dict[str, Any]:
    with download_lock:
        progress = download_progress.get(model)
        state = download_state.get(model)
        speed = download_speed.get(model, 0)

    if progress is None and state is None:
        return {"model": model, "progress": None, "status": "not_started", "speed_mbps": 0}

    return {"model": model, "progress": progress, "status": state or "unknown", "speed_mbps": round(speed, 1)}


@router.post("/model/download/cancel")
def cancel_download(model: str = Form(...)) -> dict[str, Any]:
    with download_lock:
        current_state = download_state.get(model)

    if current_state not in ("downloading", "paused"):
        raise HTTPException(status_code=404, detail=f"no active download for model: {model}")

    with download_lock:
        download_state[model] = "cancelled"

    return {"model": model, "status": "cancelled"}


@router.post("/model/download/pause")
def pause_download(model: str = Form(...)) -> dict[str, Any]:
    with download_lock:
        current_state = download_state.get(model)

    if current_state == "paused":
        return {"model": model, "status": "paused"}
    if current_state != "downloading":
        return {"model": model, "status": current_state or "not_started"}

    with download_lock:
        download_state[model] = "paused"

    return {"model": model, "status": "paused"}


@router.delete("/model/download")
def delete_model(model: str = Query(...), path: str = Query(...)) -> dict[str, Any]:
    target_path = Path(path.strip())
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"path not found: {path}")

    try:
        import shutil

        shutil.rmtree(target_path, ignore_errors=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"delete failed: {str(exc)}") from exc

    with download_lock:
        download_progress.pop(model, None)
        download_state.pop(model, None)
        download_speed.pop(model, None)

    return {"model": model, "deleted": True}


@router.post("/model/validate")
def validate_model_path(model: str = Form(...), path: str = Form(...)):
    """Check if given directory contains valid model files (config.json etc)."""
    model_path = Path(path)
    if not model_path.exists():
        return {"valid": False, "error": "路径不存在"}
    if not model_path.is_dir():
        return {"valid": False, "error": "路径不是文件夹"}
    required = ["config.json", "tokenizer_config.json"]
    missing = [f for f in required if not (model_path / f).exists()]
    if missing:
        return {"valid": False, "error": f"缺少必要文件: {', '.join(missing)}。请确认路径指向模型快照目录。"}
    has_weights = (model_path / "model.safetensors.index.json").exists() or any(p.suffix == ".safetensors" for p in model_path.iterdir())
    if not has_weights:
        return {"valid": False, "error": "未找到模型权重文件 (.safetensors 或 model.safetensors.index.json)"}
    return {"valid": True, "files": sorted(p.name for p in model_path.iterdir() if p.is_file())[:20]}
