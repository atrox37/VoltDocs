from config import load_config


def test_cors_allowed_origins_defaults_include_localhost_variants(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    cfg = load_config()

    assert cfg.cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert cfg.tm_max_entries == 200000
    assert cfg.tm_prune_batch_size == 5000
    assert cfg.tm_weak_ai_enabled is False


def test_cors_allowed_origins_merge_and_deduplicate(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://docs.example.com")
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "https://admin.example.com, https://docs.example.com/, https://preview.example.com",
    )

    cfg = load_config()

    assert cfg.cors_allowed_origins == [
        "https://docs.example.com",
        "https://admin.example.com",
        "https://preview.example.com",
    ]
