import json
import os
import stat
from pathlib import Path
from typing import Any, Dict
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Settings the user edits from the UI live here rather than in .env, so secrets
# never sit in a tracked-adjacent config file. The file is gitignored and
# written 0600. Keys present here take precedence over the environment.
RUNTIME_SETTINGS_FILE = BASE_DIR / "data" / ".runtime_settings.json"
PERSISTED_KEYS = ("groq_api_key", "groq_model", "extraction_model", "mongodb_uri")


def _read_runtime_settings() -> Dict[str, Any]:
    """Load user settings saved from the UI. Never raises."""
    try:
        if RUNTIME_SETTINGS_FILE.exists():
            data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cleaned = {k: v for k, v in data.items() if k in PERSISTED_KEYS and isinstance(v, str)}
                # Heal any legacy/non-existent model defaults
                if cleaned.get("groq_model") in ("groq/compound", ""):
                    cleaned["groq_model"] = "llama-3.3-70b-versatile"
                if cleaned.get("extraction_model") in ("groq/compound", ""):
                    cleaned["extraction_model"] = "llama-3.1-8b-instant"
                return cleaned
    except (json.JSONDecodeError, OSError):
        pass
    return {}


_RUNTIME_SETTINGS = _read_runtime_settings()


def _initial(name: str, env_var: str, default: str = "") -> str:
    """Saved UI value wins, then the environment, then the default."""
    saved = _RUNTIME_SETTINGS.get(name)
    if saved and saved != "groq/compound":
        return saved
    val = os.getenv(env_var, default)
    if val == "groq/compound":
        return default
    return val or default

class AppConfig(BaseModel):
    # App Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    uploads_dir: Path = BASE_DIR / "data" / "uploads"
    okf_export_dir: Path = BASE_DIR / "data" / "okf_exports"
    vector_db_dir: Path = BASE_DIR / "data" / "vector_db"
    mongo_fallback_dir: Path = BASE_DIR / "data" / "mongo_store"

    # LLM Settings — the API key is supplied from the UI (Engine Configuration),
    # falling back to GROQ_API_KEY in the environment for headless deployments.
    groq_api_key: str = _initial("groq_api_key", "GROQ_API_KEY", "")
    groq_model: str = _initial("groq_model", "GROQ_MODEL", "llama-3.3-70b-versatile")
    extraction_model: str = _initial("extraction_model", "EXTRACTION_MODEL", "llama-3.1-8b-instant")

    # MongoDB Settings
    mongodb_uri: str = _initial("mongodb_uri", "MONGODB_URI", "")
    database_name: str = os.getenv("DATABASE_NAME", "research_knowledge_engine")

    # Vector / Embedding Settings
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))

    # Server Settings
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    def ensure_directories(self):
        """Create necessary directories if they don't exist."""
        for path in [self.data_dir, self.uploads_dir, self.okf_export_dir, self.vector_db_dir, self.mongo_fallback_dir]:
            path.mkdir(parents=True, exist_ok=True)

    def update_settings(self, persist: bool = True, **kwargs):
        """Apply settings at runtime and, by default, remember them on this machine."""
        changed = False
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
                os.environ[k.upper()] = str(v)
                changed = True
        if changed and persist:
            self.save_runtime_settings()

    def save_runtime_settings(self):
        """Write user-editable settings to the gitignored 0600 store."""
        payload = {k: getattr(self, k, "") for k in PERSISTED_KEYS}
        payload = {k: v for k, v in payload.items() if v}
        try:
            RUNTIME_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = RUNTIME_SETTINGS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # owner read/write only
            tmp.replace(RUNTIME_SETTINGS_FILE)
            return True
        except OSError:
            return False

    def clear_groq_api_key(self):
        """Forget the stored Groq key, in memory and on disk."""
        self.groq_api_key = ""
        os.environ.pop("GROQ_API_KEY", None)
        return self.save_runtime_settings()

    @property
    def groq_api_key_source(self) -> str:
        """Where the active key came from, for display in the UI."""
        if not self.groq_api_key:
            return "none"
        if _RUNTIME_SETTINGS.get("groq_api_key") == self.groq_api_key:
            return "stored"
        if os.getenv("GROQ_API_KEY") == self.groq_api_key:
            return "environment"
        return "session"

config = AppConfig()
config.ensure_directories()
