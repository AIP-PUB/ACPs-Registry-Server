from pydantic_settings import BaseSettings
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "Agent Internet Backend API"

    # Database settings
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/agent_registry",
    )

    # JWT settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080")
    )
    # Qdrant settings
    QDRANT_ENABLED: bool = os.getenv("QDRANT_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "agents")

    # Redis settings
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # OpenAI settings
    OPENAI_API_KEY: str = os.getenv(
        "OPENAI_API_KEY", "c99c6d03-7a1d-445a-a906-848c515f94b4"
    )
    OPENAI_API_BASE_URL: str = os.getenv(
        "OPENAI_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/"
    )
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "doubao-embedding-text-240515")

    # SMS service settings
    SMS_API_KEY: str = os.getenv("SMS_API_KEY", "")
    SMS_TEMPLATE_ID: str = os.getenv("SMS_TEMPLATE_ID", "")

    # File storage settings
    UPLOAD_BASE_PATH: str = os.getenv("UPLOAD_BASE_PATH", "/path/to/storage")

    # CA certificate service settings
    CA_CERT_URL: str = os.getenv(
        "CA_CERT_URL", "https://ca-cert-service.example.com/api/v1/certificates"
    )

    # CA Server settings for ATR protocol
    CA_SERVER_BASE_URL: str = os.getenv(
        "CA_SERVER_BASE_URL", "http://ca-server:8003/acps-atr-v1"
    )

    # ATR (Agent Trusted Registration) settings
    ATR_BASE_PATH: str = os.getenv("ATR_BASE_PATH", "/acps-atr-v1")
    ATR_ALLOW_IP_LIST: str = os.getenv(
        "ATR_ALLOW_IP_LIST", "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )  # DRC (Data Replication & Consistency) settings
    DRC_BASE_PATH: str = os.getenv("DRC_BASE_PATH", "/acps-drc-v1")
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "agent-registry")
    PROJECT_VERSION: str = os.getenv("PROJECT_VERSION", "1.0.0")

    # DRC Data retention settings
    DRC_RETENTION_WINDOW_HOURS: int = int(
        os.getenv("DRC_RETENTION_WINDOW_HOURS", "168")
    )  # 7 days
    DRC_RETENTION_MAX_RECORDS: int = int(
        os.getenv("DRC_RETENTION_MAX_RECORDS", "100000")
    )  # Maximum records to keep

    # DRC Snapshot settings
    DRC_SNAPSHOT_ACCESS_TIMEOUT_HOURS: int = int(
        os.getenv("DRC_SNAPSHOT_ACCESS_TIMEOUT_HOURS", "2")
    )
    DRC_SNAPSHOT_MAX_LIFETIME_HOURS: int = int(
        os.getenv("DRC_SNAPSHOT_MAX_LIFETIME_HOURS", "24")
    )
    DRC_SNAPSHOT_CLEANUP_INTERVAL_HOURS: int = int(
        os.getenv("DRC_SNAPSHOT_CLEANUP_INTERVAL_HOURS", "1")
    )

    # DRC Changes settings
    DRC_CHANGES_MAX_LIMIT: int = int(os.getenv("DRC_CHANGES_MAX_LIMIT", "10000"))
    DRC_CHANGES_DEFAULT_LIMIT: int = int(os.getenv("DRC_CHANGES_DEFAULT_LIMIT", "1000"))

    # Webhook batching settings
    DRC_WEBHOOK_BATCH_WINDOW_SECONDS: int = int(
        os.getenv("DRC_WEBHOOK_BATCH_WINDOW_SECONDS", "5")
    )

    # Uvicorn server settings
    UVICORN_HOST: str = os.getenv("UVICORN_HOST", "0.0.0.0")
    UVICORN_PORT: int = int(os.getenv("UVICORN_PORT", "8001"))
    UVICORN_RELOAD: bool = os.getenv("UVICORN_RELOAD", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    UVICORN_LOG_LEVEL: str = os.getenv("UVICORN_LOG_LEVEL", "info")

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
