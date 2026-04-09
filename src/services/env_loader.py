from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_ENV_LOADED = False


def load_project_env() -> None:
    """Load .env once, preferring the repository root .env file."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    repo_root = Path(__file__).resolve().parents[2]
    root_env = repo_root / ".env"

    if root_env.exists():
        load_dotenv(dotenv_path=root_env, override=False)
    else:
        detected = find_dotenv(filename=".env", usecwd=True)
        if detected:
            load_dotenv(dotenv_path=detected, override=False)

    _ENV_LOADED = True

