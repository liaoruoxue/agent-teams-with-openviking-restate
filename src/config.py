"""Configuration loaded from .env file."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


@dataclass(frozen=True)
class Config:
    # Restate
    restate_url: str = os.getenv("RESTATE_URL", "http://localhost:8080")

    # LLM
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model_name: str = os.getenv("LLM_MODEL_NAME", "")

    # OpenViking local storage
    ov_data_path: str = os.getenv("OV_DATA_PATH", "./data/ov_store")

    # Embedding / VLM service
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_api_base: str = os.getenv("EMBEDDING_API_BASE", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "2048"))
    vlm_model: str = os.getenv("VLM_MODEL", "")


cfg = Config()
