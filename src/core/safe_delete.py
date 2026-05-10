import shutil
import tempfile
from pathlib import Path


class SafeDelete:
    """Filesystem deletion with layered protection.

    Usage:
        SafeDelete(path).require_temp_dir().require_name_starts_with("mineru_").execute()
        SafeDelete(hf_path).forbid_project_files().require_model_files().execute()
    """

    PROJECT_MARKERS = {
        ".git", ".gitignore", ".env", ".editorconfig",
        "package.json", "pyproject.toml", "Cargo.toml",
        "setup.py", "setup.cfg", "Makefile", "Dockerfile",
        "requirements.txt", "pytest.ini",
    }

    def __init__(self, path: str | Path):
        self._path = Path(path).resolve()
        self._checks: list[str] = []
        self._errors: list[str] = []

    @property
    def path(self) -> Path:
        return self._path

    def require_exists(self) -> "SafeDelete":
        if not self._path.exists():
            self._errors.append("path does not exist")
        return self

    def require_in_temp_dir(self) -> "SafeDelete":
        tp = tempfile.gettempdir()
        if not str(self._path).startswith(tp):
            self._errors.append(f"path not in temp dir ({tp})")
        return self

    def require_name_starts_with(self, prefix: str) -> "SafeDelete":
        if not self._path.name.startswith(prefix):
            self._errors.append(f"name does not start with '{prefix}': {self._path.name}")
        return self

    def require_parent_name_starts_with(self, prefix: str) -> "SafeDelete":
        if not self._path.parent.name.startswith(prefix):
            self._errors.append(f"parent name does not start with '{prefix}': {self._path.parent.name}")
        return self

    def require_model_files(self) -> "SafeDelete":
        has_config = (self._path / "config.json").exists()
        has_safetensors = (
            (self._path / "model.safetensors.index.json").exists()
            or any(p.suffix == ".safetensors" for p in self._path.iterdir())
        )
        if not (has_config and has_safetensors):
            self._errors.append("path does not contain model files (config.json + safetensors)")
        return self

    def forbid_project_files(self, *, walk_up: int = 3) -> "SafeDelete":
        for p in self._scoped_walk(self._path, walk_up):
            for marker in self.PROJECT_MARKERS:
                if (p / marker).exists():
                    self._errors.append(f"project file detected ({marker}) under {p}")
                    return self
        return self

    def forbid_in_project_root(self, project_root: str | Path) -> "SafeDelete":
        root = Path(project_root).resolve()
        if str(self._path).startswith(str(root)):
            self._errors.append(f"path is inside project root: {root}")
        return self

    def is_safe(self) -> bool:
        return len(self._errors) == 0

    def errors(self) -> list[str]:
        return list(self._errors)

    def execute(self, ignore_errors: bool = False) -> bool:
        if self._errors:
            return False
        if not self._path.exists():
            return bool(ignore_errors)
        shutil.rmtree(str(self._path), ignore_errors=ignore_errors)
        return True

    @staticmethod
    def _scoped_walk(start: Path, walk_up: int):
        yield start
        current = start.parent
        for _ in range(walk_up):
            yield current
            current = current.parent
