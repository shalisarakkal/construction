from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    storage_dir: Path = Path(__file__).resolve().parent.parent / "storage"
    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384  # matches all-MiniLM-L6-v2
    default_top_k: int = 5
    max_chunk_words: int = 500
    llm_provider: str = "anthropic"  # "anthropic" or "ollama"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_num_gpu: int | None = None  # forwarded as options.num_gpu; 0 forces CPU-only

    model_config = {"env_prefix": "RAG_", "env_file": ".env"}

    @property
    def documents_dir(self) -> Path:
        return self.storage_dir / "documents"

    @property
    def index_dir(self) -> Path:
        return self.storage_dir / "index"

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "metadata.sqlite3"

    @property
    def faiss_index_path(self) -> Path:
        return self.index_dir / "faiss.index"


settings = Settings()
settings.documents_dir.mkdir(parents=True, exist_ok=True)
settings.index_dir.mkdir(parents=True, exist_ok=True)
