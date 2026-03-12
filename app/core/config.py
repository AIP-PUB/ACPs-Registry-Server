from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Any
from pydantic import field_validator
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

    # File storage settings
    UPLOAD_BASE_PATH: str = os.getenv("UPLOAD_BASE_PATH", "/path/to/storage")

    # CA Server settings for ATR protocol
    CA_SERVER_BASE_URL: str = os.getenv(
        "CA_SERVER_BASE_URL", "http://ca-server:8003/acps-atr-v2"
    )
    CA_SERVER_MOCK: bool = os.getenv("CA_SERVER_MOCK", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    # ATR (Agent Trusted Registration) settings
    ATR_BASE_PATH: str = os.getenv("ATR_BASE_PATH", "/acps-atr-v2")
    ATR_ALLOW_IP_LIST: str = os.getenv(
        "ATR_ALLOW_IP_LIST", "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )

    # DSP (Data Synchronization Protocol) settings
    DSP_BASE_PATH: str = os.getenv("DSP_BASE_PATH", "/acps-dsp-v2")
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "agent-registry")
    PROJECT_VERSION: str = os.getenv("PROJECT_VERSION", "1.0.0")

    # DSP data retention settings
    DSP_RETENTION_WINDOW_HOURS: int = int(
        os.getenv("DSP_RETENTION_WINDOW_HOURS", "168")
    )  # 7 days
    DSP_RETENTION_MAX_RECORDS: int = int(
        os.getenv("DSP_RETENTION_MAX_RECORDS", "100000")
    )  # Maximum records to keep

    # DSP snapshot settings
    DSP_SNAPSHOT_ACCESS_TIMEOUT_HOURS: int = int(
        os.getenv("DSP_SNAPSHOT_ACCESS_TIMEOUT_HOURS", "2")
    )
    DSP_SNAPSHOT_MAX_LIFETIME_HOURS: int = int(
        os.getenv("DSP_SNAPSHOT_MAX_LIFETIME_HOURS", "24")
    )
    DSP_SNAPSHOT_CLEANUP_INTERVAL_HOURS: int = int(
        os.getenv("DSP_SNAPSHOT_CLEANUP_INTERVAL_HOURS", "1")
    )

    # DSP changes settings
    DSP_CHANGES_MAX_LIMIT: int = int(os.getenv("DSP_CHANGES_MAX_LIMIT", "10000"))
    DSP_CHANGES_DEFAULT_LIMIT: int = int(os.getenv("DSP_CHANGES_DEFAULT_LIMIT", "1000"))

    # DSP webhook batching settings
    DSP_WEBHOOK_BATCH_WINDOW_SECONDS: int = int(
        os.getenv("DSP_WEBHOOK_BATCH_WINDOW_SECONDS", "5")
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

    CA_CHALLENGE_STATUS_PATH_TYPE: str = os.getenv(
        "CA_CHALLENGE_STATUS_PATH_TYPE", "parent"
    )

    AIC_CRC_SALT: str = os.getenv("AIC_CRC_SALT", "0x0000ABCD")

    @field_validator("AIC_CRC_SALT", mode="before")
    @classmethod
    def validate_hex_str(cls, v: Any) -> Any:
        if isinstance(v, str):
            if not v.startswith("0x") and not v.startswith("0X"):
                raise ValueError("Hex string must start with 0x")
            try:
                # Check if it is a valid hex string
                int(v, 16)
                if len(v) <= 4:
                    # 0x + at least 1 byte (2 hex chars) -> length >= 4
                    raise ValueError("Hex string must be longer than 1 byte")
                return v
            except ValueError:
                raise ValueError("Invalid hex string")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )


settings = Settings()
