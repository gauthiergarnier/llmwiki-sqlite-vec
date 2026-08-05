"""Configuration for the standalone memory MCP server.

Kept separate from mcp/config.py so the memory back-end is fully decoupled
from the wiki server. All values are overridable via environment variables
(prefix-free, matching pydantic-settings) or the repo-root .env file.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    WORKSPACE_PATH: str = "."
    APP_URL: str = "http://localhost:3000"

    # --- Background consolidation ("sleep-time agent") ---
    # OFF by default: day-1 footprint stays at the embedder only. Turning this on
    # enables the Ollama-backed distillation / contradiction sweep.
    CONSOLIDATION_ENABLED: bool = False
    # auto: apply confident decisions automatically, escalate uncertain ones as clarifications.
    CONSOLIDATION_MODE: str = "auto"  # "auto" | "review"
    CONSOLIDATION_BATCH: int = 64

    # Uncertainty gate: decisions at/above this confidence auto-apply (append-only);
    # below it, the conflicting claims are left untouched and a clarification is raised.
    AUTO_APPLY_THRESHOLD: float = 0.85
    # Cosine-similarity floor used by the no-LLM fallback assessor to flag a likely
    # duplicate/contradiction worth a clarification.
    DUPLICATE_SIMILARITY_FLOOR: float = 0.88
    # During consolidation, pairs at/above this similarity are worth asking the LLM about.
    CONSOLIDATION_CONSIDER_FLOOR: float = 0.5

    # --- Ollama (local LLM) ---
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b-instruct"
    OLLAMA_TIMEOUT_S: float = 120.0


settings = MemorySettings()
