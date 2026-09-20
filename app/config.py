import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class AppConfig(BaseModel):
    # App Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    uploads_dir: Path = BASE_DIR / "data" / "uploads"
    okf_export_dir: Path = BASE_DIR / "data" / "okf_exports"
    vector_db_dir: Path = BASE_DIR / "data" / "vector_db"
    mongo_fallback_dir: Path = BASE_DIR / "data" / "mongo_store"

    # LLM Settings
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    extraction_model: str = os.getenv("EXTRACTION_MODEL", "qwen/qwen3.8-27b")

    # MongoDB Settings
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
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

    def update_settings(self, **kwargs):
        """Update runtime settings."""
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
                os.environ[k.upper()] = str(v)

config = AppConfig()
config.ensure_directories()
