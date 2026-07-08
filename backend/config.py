from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    translation_batch_max_bytes: int
    translation_batch_max_segments: int
    translation_timeout_seconds: int
    glossary_max_terms_per_request: int
    glossary_max_prompt_chars: int
    bedrock_model_id: str
    bedrock_region: str
    bedrock_aws_profile: str
    qa_ai_enabled: bool
    qa_ai_model_id: str
    qa_ai_uncertain_threshold: float
    qa_ai_batch_max_segments: int
    qa_repair_enabled: bool
    qa_repair_max_attempts: int
    qa_repair_batch_max_segments: int
    tm_weak_ai_enabled: bool
    tm_max_entries: int
    tm_prune_batch_size: int
    require_auth: bool
    dev_user_email: str
    initial_admin_email: str
    cognito_domain: str
    cognito_client_id: str
    cognito_client_secret: str
    cognito_redirect_uri: str
    frontend_url: str
    cors_allowed_origins_raw: str

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

    @property
    def cors_allowed_origins(self) -> list[str]:
        origins: list[str] = []

        def add(origin: str) -> None:
            normalized = origin.rstrip("/")
            if normalized and normalized not in origins:
                origins.append(normalized)

        add(self.frontend_url)
        for raw in self.cors_allowed_origins_raw.split(","):
            add(raw.strip())

        for origin in list(origins):
            parsed = urlsplit(origin)
            host = parsed.hostname
            if not host or parsed.port is None:
                continue
            if host == "localhost":
                add(urlunsplit((parsed.scheme, f"127.0.0.1:{parsed.port}", parsed.path, parsed.query, parsed.fragment)))
            elif host == "127.0.0.1":
                add(urlunsplit((parsed.scheme, f"localhost:{parsed.port}", parsed.path, parsed.query, parsed.fragment)))

        return origins


def load_config() -> AppConfig:
    raw_data_dir = os.getenv("DATA_DIR", "./data")
    data_dir = (BASE_DIR / raw_data_dir).resolve() if raw_data_dir.startswith(".") else Path(raw_data_dir).resolve()
    return AppConfig(
        port=int(os.getenv("PORT", "8080")),
        data_dir=data_dir,
        pandoc_path=os.getenv("PANDOC_PATH", "pandoc"),
        pandoc_timeout_seconds=int(os.getenv("PANDOC_TIMEOUT_SECONDS", "300")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "50")),
        translation_batch_max_bytes=int(os.getenv("TRANSLATION_BATCH_MAX_BYTES", "5000")),
        translation_batch_max_segments=int(os.getenv("TRANSLATION_BATCH_MAX_SEGMENTS", "40")),
        translation_timeout_seconds=int(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "90")),
        glossary_max_terms_per_request=int(os.getenv("GLOSSARY_MAX_TERMS_PER_REQUEST", "100")),
        glossary_max_prompt_chars=int(os.getenv("GLOSSARY_MAX_PROMPT_CHARS", "12000")),
        bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0"),
        bedrock_region=os.getenv("BEDROCK_REGION", "us-east-1"),
        bedrock_aws_profile=os.getenv("BEDROCK_AWS_PROFILE", ""),
        qa_ai_enabled=_get_bool("QA_AI_ENABLED", True),
        qa_ai_model_id=os.getenv("QA_AI_MODEL_ID", "") or os.getenv(
            "QA_BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0"
        ),
        qa_ai_uncertain_threshold=float(os.getenv("QA_AI_UNCERTAIN_THRESHOLD", "0.75")),
        qa_ai_batch_max_segments=int(os.getenv("QA_AI_BATCH_MAX_SEGMENTS", "40")),
        qa_repair_enabled=_get_bool("QA_REPAIR_ENABLED", True),
        qa_repair_max_attempts=int(os.getenv("QA_REPAIR_MAX_ATTEMPTS", "1")),
        qa_repair_batch_max_segments=int(os.getenv("QA_REPAIR_BATCH_MAX_SEGMENTS", "40")),
        tm_weak_ai_enabled=_get_bool("TM_WEAK_AI_ENABLED", False),
        tm_max_entries=int(os.getenv("TM_MAX_ENTRIES", "200000")),
        tm_prune_batch_size=int(os.getenv("TM_PRUNE_BATCH_SIZE", "5000")),
        require_auth=_get_bool("REQUIRE_AUTH", False),
        dev_user_email=os.getenv("DEV_USER_EMAIL", "dev@voltdocs.local"),
        initial_admin_email=os.getenv("INITIAL_ADMIN_EMAIL", "").strip(),
        cognito_domain=os.getenv("COGNITO_DOMAIN", "").rstrip("/"),
        cognito_client_id=os.getenv("COGNITO_CLIENT_ID", ""),
        cognito_client_secret=os.getenv("COGNITO_CLIENT_SECRET", ""),
        cognito_redirect_uri=os.getenv("COGNITO_REDIRECT_URI", ""),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
        cors_allowed_origins_raw=os.getenv("CORS_ALLOWED_ORIGINS", ""),
    )
