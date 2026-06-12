from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default).lower()).strip().lower() == "true"


@dataclass(frozen=True)
class AppConfig:
    port: int
    data_dir: Path
    pandoc_path: str
    pandoc_timeout_seconds: int
    max_upload_mb: int
    translation_lambda_url: str
    translation_batch_max_bytes: int
    translation_batch_max_segments: int
    translation_timeout_seconds: int
    glossary_max_terms_per_request: int
    glossary_max_prompt_chars: int
    # Bedrock direct mode (used when translation_lambda_url is empty)
    bedrock_model_id: str
    bedrock_region: str
    bedrock_aws_profile: str
    require_auth: bool
    dev_user_email: str
    initial_admin_email: str
    cognito_domain: str
    cognito_client_id: str
    cognito_client_secret: str
    cognito_redirect_uri: str
    frontend_url: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "voltdocs.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


def load_config() -> AppConfig:
    raw_data_dir = os.getenv("DATA_DIR", "./data")
    data_dir = (BASE_DIR / raw_data_dir).resolve() if raw_data_dir.startswith(".") else Path(raw_data_dir).resolve()
    return AppConfig(
        port=int(os.getenv("PORT", "8080")),
        data_dir=data_dir,
        pandoc_path=os.getenv("PANDOC_PATH", "pandoc"),
        pandoc_timeout_seconds=int(os.getenv("PANDOC_TIMEOUT_SECONDS", "300")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "50")),
        translation_lambda_url=os.getenv("TRANSLATION_LAMBDA_URL", ""),
        translation_batch_max_bytes=int(os.getenv("TRANSLATION_BATCH_MAX_BYTES", "5000")),
        translation_batch_max_segments=int(os.getenv("TRANSLATION_BATCH_MAX_SEGMENTS", "120")),
        translation_timeout_seconds=int(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "90")),
        glossary_max_terms_per_request=int(os.getenv("GLOSSARY_MAX_TERMS_PER_REQUEST", "100")),
        glossary_max_prompt_chars=int(os.getenv("GLOSSARY_MAX_PROMPT_CHARS", "12000")),
        bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        bedrock_region=os.getenv("BEDROCK_REGION", "us-east-1"),
        bedrock_aws_profile=os.getenv("BEDROCK_AWS_PROFILE", ""),
        require_auth=_get_bool("REQUIRE_AUTH", False),
        dev_user_email=os.getenv("DEV_USER_EMAIL", "dev@voltdocs.local"),
        initial_admin_email=os.getenv("INITIAL_ADMIN_EMAIL", "").strip(),
        cognito_domain=os.getenv("COGNITO_DOMAIN", "").rstrip("/"),
        cognito_client_id=os.getenv("COGNITO_CLIENT_ID", ""),
        cognito_client_secret=os.getenv("COGNITO_CLIENT_SECRET", ""),
        cognito_redirect_uri=os.getenv("COGNITO_REDIRECT_URI", ""),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
    )
