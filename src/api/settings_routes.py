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
    llm_models, parser_models = _model_catalogs()
    try:
        hf_cache_info = scan_cache_dir()
        for repo in hf_cache_info.repos:
            for model_key, model_def in {**llm_models, **parser_models}.items():
                if model_key in found:
                    continue
                repo_id = model_def.get("repo_id") if isinstance(model_def, dict) else None
                if repo_id and repo_id in repo.repo_id:
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


SETTINGS_FILE = Path(os.getenv("DATA_ROOT", "./data")) / "llm_settings.json"
DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "remote",
    "provider": "deepseek",
    "remote": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
    },
    "local": {
        "model_path": "",
        "model": "",
        "port": 8000,
        "precision": "bf16",
        "temperature": 0.1,
        "timeout_sec": 15,
        "max_tokens": 2048,
    },
    "model_paths": {},
    "llm_models": {},
    "parser_models": {},
}

download_progress: dict[str, float] = {}
download_state: dict[str, str] = {}
download_speed: dict[str, float] = {}
download_paths: dict[str, str] = {}
download_lock = threading.Lock()


def _ensure_settings_dir() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_settings() -> dict[str, Any]:
    _ensure_settings_dir()
    if not SETTINGS_FILE.exists():
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    if "mode" in data:
        merged["mode"] = data["mode"]
    for key, value in data.items():
        if key not in {"mode", "remote", "local"}:
            merged[key] = value
    if isinstance(data.get("remote"), dict):
        merged["remote"].update(data["remote"])
    if isinstance(data.get("local"), dict):
        merged["local"].update(data["local"])
    return merged


DEFAULT_LLM_MODELS: dict[str, dict[str, str]] = {
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
        "description": "阿里多模态模型，7B 参数，中英双通",
    },
    "gemma-12b": {
        "label": "Gemma-3-12B",
        "size": "~24 GB",
        "vram": "~24 GB (bf16)",
        "gpu": "RTX 4090 / 2x RTX 3090",
        "repo_id": "google/gemma-3-12b-it",
        "description": "Google 多模态模型，12B 参数",
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

DEFAULT_PARSER_MODELS: dict[str, dict[str, str]] = {
    "mineru-25": {
        "key": "mineru-25",
        "label": "MinerU2.5-Pro-1.2B",
        "size": "~2.5 GB",
        "vram": "~4 GB",
        "gpu": "RTX 3060+",
        "repo_id": "opendatalab/MinerU2.5-Pro-2604-1.2B",
        "description": "文档结构识别模型，PDF/PPT/DOCX 解析前置依赖",
    },
    "pdf-extract": {
        "key": "pdf-extract",
        "label": "PDF-Extract-Kit-1.0",
        "size": "~1.5 GB",
        "vram": "~3 GB",
        "gpu": "RTX 3060+",
        "repo_id": "opendatalab/PDF-Extract-Kit-1.0",
        "description": "PDF 内容提取模型，表格/公式/图片识别",
    },
}


def _model_catalogs() -> tuple[dict[str, Any], dict[str, Any]]:
    settings = _load_settings()
    llm = settings.get("llm_models")
    parser = settings.get("parser_models")
    if not isinstance(llm, dict) or not llm:
        llm = DEFAULT_LLM_MODELS
    if not isinstance(parser, dict) or not parser:
        parser = DEFAULT_PARSER_MODELS
    return llm, parser


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
    if "provider" in payload:
        settings["provider"] = payload["provider"]
    if "model_paths" in payload:
        settings["model_paths"] = payload["model_paths"]
    if "llm_models" in payload:
        settings["llm_models"] = payload["llm_models"]
    if "parser_models" in payload:
        settings["parser_models"] = payload["parser_models"]
    _save_settings(settings)
    return settings


@router.get("/models")
def list_models() -> dict[str, Any]:
    llm_models, parser_models = _model_catalogs()
    return {"models": llm_models, "parser_models": parser_models}


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
    llm_models, parser_models = _model_catalogs()
    model_info = llm_models.get(model) or parser_models.get(model)
    if not isinstance(model_info, dict) or not model_info.get("repo_id"):
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
        download_paths[model] = download_path

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
def delete_model(model: str = Query(...), path: str = Query("")) -> dict[str, Any]:
    target = path.strip() or download_paths.get(model, "")
    if not target:
        return {"model": model, "deleted": False, "reason": "no path provided"}
    target_path = Path(target).resolve()

    # --- SAFETY CHECKS ---
    # 1. Path must exist and be a directory
    if not target_path.exists():
        return {"model": model, "deleted": False, "reason": "path not found"}
    if not target_path.is_dir():
        return {"model": model, "deleted": False, "reason": "path is not a directory"}

    # 2. Path must look like a model directory (contain config.json or safetensors)
    is_model_dir = (
        (target_path / "config.json").exists()
        or any(p.suffix == ".safetensors" for p in target_path.iterdir())
        or (target_path / "model.safetensors.index.json").exists()
    )
    if not is_model_dir:
        return {"model": model, "deleted": False, "reason": "路径不包含模型文件，拒绝删除以保护数据"}

    # 3. Find actual cache root (walk up to find blobs/snapshots/refs)
    delete_paths = [target_path]
    check_root = target_path
    for _ in range(3):
        parent = check_root.parent
        if (parent / "blobs").is_dir() and (parent / "snapshots").is_dir() and (parent / "refs").is_dir():
            delete_paths = [parent / "blobs", parent / "snapshots", parent / "refs"]
            break
        check_root = parent

    # Safety: never delete directories with project files
    dangerous = {".git", ".env", ".gitignore", "package.json", "pyproject.toml", "Cargo.toml", "setup.py", "Makefile"}
    for p in delete_paths:
        for item in dangerous:
            if (p / item).exists():
                return {"model": model, "deleted": False, "reason": f"路径包含项目文件 ({item})，拒绝删除以保护项目"}

    try:
        from src.core.safe_delete import SafeDelete
        for p in delete_paths:
            if p.exists():
                SafeDelete(p).forbid_project_files().execute()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"delete failed: {str(exc)}") from exc

    with download_lock:
        download_progress.pop(model, None)
        download_state.pop(model, None)
        download_speed.pop(model, None)
        download_paths.pop(model, None)
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
