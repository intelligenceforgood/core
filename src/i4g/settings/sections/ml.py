"""Vector/LLM/crypto/PII/secrets settings models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from i4g.settings.sections._paths import PROJECT_ROOT


class VectorSettings(BaseSettings):
    """Vector store configuration supporting multiple backends."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    backend: Literal["chroma", "faiss", "pgvector", "vertex_ai"] = Field(
        default="chroma",
        validation_alias=AliasChoices("VECTOR_BACKEND", "VECTOR__BACKEND"),
    )
    collection: str = Field(
        default="i4g_vectors",
        validation_alias=AliasChoices("VECTOR_COLLECTION", "VECTOR__COLLECTION"),
    )
    embedding_model: str = Field(
        default="nomic-embed-text",
        validation_alias=AliasChoices("EMBED_MODEL", "VECTOR__EMBED_MODEL"),
    )
    chroma_dir: Path = Field(default=PROJECT_ROOT / "data" / "chroma_store")
    faiss_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "faiss_store",
        validation_alias=AliasChoices("VECTOR_FAISS_DIR", "VECTOR__FAISS_DIR"),
    )
    pgvector_dsn: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VECTOR_PGVECTOR_DSN", "VECTOR__PGVECTOR__DSN"),
    )
    vertex_ai_index: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VECTOR_VERTEX_AI_INDEX", "VECTOR__VERTEX_AI__INDEX"),
    )
    vertex_ai_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VECTOR_VERTEX_AI_PROJECT",
            "VECTOR__VERTEX_AI__PROJECT",
            "I4G_VERTEX_SEARCH_PROJECT",
        ),
    )
    vertex_ai_location: str | None = Field(
        default="us-central1",
        validation_alias=AliasChoices(
            "VECTOR_VERTEX_AI_LOCATION",
            "VECTOR__VERTEX_AI__LOCATION",
            "I4G_VERTEX_SEARCH_LOCATION",
        ),
    )
    vertex_ai_data_store: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VECTOR_VERTEX_AI_DATA_STORE",
            "VECTOR__VERTEX_AI__DATA_STORE",
            "I4G_VERTEX_SEARCH_DATA_STORE",
        ),
    )
    vertex_ai_branch: str = Field(
        default="default_branch",
        validation_alias=AliasChoices(
            "VECTOR_VERTEX_AI_BRANCH",
            "VECTOR__VERTEX_AI__BRANCH",
            "I4G_VERTEX_SEARCH_BRANCH",
        ),
    )
    vertex_ai_serving_config: str = Field(
        default="default_search",
        validation_alias=AliasChoices(
            "VECTOR_VERTEX_AI_SERVING_CONFIG",
            "VECTOR__VERTEX_AI__SERVING_CONFIG",
            "I4G_VERTEX_SEARCH_SERVING_CONFIG",
        ),
        description="Vertex AI Search serving config ID.",
    )


class LLMSettings(BaseSettings):
    """Large language model provider settings."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    provider: Literal["ollama", "vertex_ai", "gemini", "mock"] = Field(
        default="ollama",
        validation_alias=AliasChoices("LLM_PROVIDER", "LLM__PROVIDER"),
        description="LLM backend: 'vertex_ai'/'gemini' (synonyms) use Vertex AI via google-genai, 'ollama' uses local Ollama, 'mock' for tests.",  # noqa: E501
    )
    chat_model: str = Field(
        default="llama3",
        validation_alias=AliasChoices("LLM_CHAT_MODEL", "LLM__CHAT_MODEL"),
        description="Primary model identifier (e.g. 'llama3', 'gemini-3-flash-preview'). Used for all providers.",
    )
    temperature: float = Field(
        default=0.1,
        validation_alias=AliasChoices("LLM_TEMPERATURE", "LLM__TEMPERATURE"),
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "LLM__OLLAMA_BASE_URL"),
    )
    vertex_ai_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_VERTEX_AI_PROJECT", "LLM__VERTEX_AI__PROJECT"),
    )
    vertex_ai_location: str | None = Field(
        default="us-central1",
        validation_alias=AliasChoices("LLM_VERTEX_AI_LOCATION", "LLM__VERTEX_AI__LOCATION"),
    )


class CryptoSettings(BaseSettings):
    """Application-level cryptographic material used by vault/tokenization flows."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    pii_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CRYPTO_PII_KEY", "CRYPTO__PII_KEY"),
    )


class SecretsSettings(BaseSettings):
    """Secret resolution strategy (local vs Secret Manager)."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    use_secret_manager: bool = Field(
        default=False,
        validation_alias=AliasChoices("SECRETS_USE_SECRET_MANAGER", "SECRETS__USE_SECRET_MANAGER"),
    )
    project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SECRETS_PROJECT", "SECRETS__PROJECT"),
    )
    local_env_file: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("SECRETS_LOCAL_ENV_FILE", "SECRETS__LOCAL_ENV_FILE"),
    )


class MlPlatformSettings(BaseSettings):
    """ML Platform inference routing settings."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    inference_backend: Literal["llm", "ml_platform"] = Field(
        default="llm",
        validation_alias=AliasChoices("ML_INFERENCE_BACKEND", "ML__INFERENCE_BACKEND"),
        description=(
            "Which inference backend to use: 'llm' (existing LLM classifier)"
            " or 'ml_platform' (dedicated ML service)."
        ),
    )
    platform_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("ML_PLATFORM_BASE_URL", "ML__PLATFORM_BASE_URL"),
    )
    platform_auth_method: Literal["iam", "api_key", "none"] = Field(
        default="iam",
        validation_alias=AliasChoices("ML_PLATFORM_AUTH_METHOD", "ML__PLATFORM_AUTH_METHOD"),
    )
    fallback_to_llm: bool = Field(
        default=True,
        validation_alias=AliasChoices("ML_FALLBACK_TO_LLM", "ML__FALLBACK_TO_LLM"),
    )
    entity_extraction_backend: Literal["llm", "ml_platform"] = Field(
        default="llm",
        validation_alias=AliasChoices("ML_ENTITY_EXTRACTION_BACKEND", "ML__ENTITY_EXTRACTION_BACKEND"),
        description=(
            "Which backend to use for entity extraction: 'llm' (existing LLM NER)"
            " or 'ml_platform' (dedicated ML NER model)."
        ),
    )
    risk_scoring_backend: Literal["llm", "ml_platform"] = Field(
        default="llm",
        validation_alias=AliasChoices("ML_RISK_SCORING_BACKEND", "ML__RISK_SCORING_BACKEND"),
        description=(
            "Which backend to use for risk scoring: 'llm' (existing LLM)" " or 'ml_platform' (dedicated ML risk model)."
        ),
    )
    similarity_backend: Literal["llm", "ml_platform"] = Field(
        default="llm",
        validation_alias=AliasChoices("ML_SIMILARITY_BACKEND", "ML__SIMILARITY_BACKEND"),
        description=(
            "Which backend to use for document similarity: 'llm' (existing LLM)"
            " or 'ml_platform' (FAISS-based embedding search)."
        ),
    )
