"""Tests for Settings configuration."""

from __future__ import annotations

from pathlib import Path

from nous.config.settings import (
    EmbeddingConfig,
    ForgettingConfig,
    IrodoriConfig,
    PortraitGenerationConfig,
    QdrantConfig,
    RerankerConfig,
    ServerConfig,
    Settings,
)


class TestDefaultValues:
    def test_server_defaults(self):
        cfg = ServerConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 26262

    def test_embedding_defaults(self):
        cfg = EmbeddingConfig()
        assert cfg.model == "onnx-community/ruri-v3-30m-ONNX"
        assert cfg.device == "cpu"

    def test_reranker_defaults(self):
        cfg = RerankerConfig()
        assert cfg.model == "hotchpotch/japanese-reranker-xsmall-v2"
        assert cfg.enabled is True

    def test_qdrant_defaults(self):
        cfg = QdrantConfig()
        assert cfg.url == "http://localhost:6333"
        assert cfg.api_key is None
        assert cfg.collection_prefix == "memory_"

    def test_forgetting_defaults(self):
        cfg = ForgettingConfig()
        assert cfg.enabled is True
        assert cfg.decay_interval_seconds == 3600
        assert cfg.min_strength == 0.005
        assert cfg.emotion_half_life_hours == 24.0

    def test_portrait_gen_defaults(self):
        cfg = PortraitGenerationConfig()
        # CRITICAL: default OFF (managed per-persona via ChatConfig.portrait_enabled)
        assert cfg.provider == "comfyui"
        assert cfg.comfyui_url == "http://localhost:8188"
        assert cfg.auto_generate is False
        assert cfg.generate_interval_min == 10
        assert cfg.size == "512x512"
        assert cfg.quality == "standard"
        assert cfg.emotion_threshold == 0.3
        assert cfg.max_monthly_budget == 5.0

    def test_irodori_defaults(self):
        cfg = IrodoriConfig()
        assert cfg.enabled is False
        assert cfg.url == "http://localhost:8088/v1"
        assert cfg.voice == "default"
        assert cfg.timeout_seconds == 30


class TestSettings:
    def test_full_defaults(self, monkeypatch):
        # CI環境で NOUS_DATA_ROOT / NOUS_DATA_DIR が設定されている可能性があるため削除
        monkeypatch.delenv("NOUS_DATA_ROOT", raising=False)
        monkeypatch.delenv("NOUS_DATA_DIR", raising=False)
        s = Settings()
        assert s.timezone == "Asia/Tokyo"
        assert s.data_dir == "./data/memory"
        assert s.log_level == "INFO"
        assert s.default_persona is None
        assert s.server.port == 26262
        assert s.contradiction_threshold == 0.85
        assert s.duplicate_threshold == 0.90
        # Portrait generation — critical cost-control layer: default OFF
        assert s.portrait_gen.provider == "comfyui"

    def test_env_override_simple(self, monkeypatch):
        monkeypatch.setenv("NOUS_TIMEZONE", "UTC")
        monkeypatch.setenv("NOUS_LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.timezone == "UTC"
        assert s.log_level == "DEBUG"

    def test_env_override_nested(self, monkeypatch):
        monkeypatch.setenv("NOUS_SERVER__PORT", "9999")
        s = Settings()
        assert s.server.port == 9999

    def test_env_override_portrait_gen(self, monkeypatch):
        monkeypatch.setenv("NOUS_PORTRAIT_GEN__PROVIDER", "openai")
        monkeypatch.setenv("NOUS_PORTRAIT_GEN__AUTO_GENERATE", "true")
        s = Settings()
        assert s.portrait_gen.provider == "openai"
        assert s.portrait_gen.auto_generate is True
        # Other fields should remain default
        assert s.portrait_gen.comfyui_url == "http://localhost:8188"
        assert s.portrait_gen.max_monthly_budget == 5.0

    def test_env_override_irodori(self, monkeypatch):
        monkeypatch.setenv("NOUS_IRODORI__URL", "http://192.168.1.100:8088/v1")
        monkeypatch.setenv("NOUS_IRODORI__VOICE", "kobayashi")
        s = Settings()
        assert s.irodori.url == "http://192.168.1.100:8088/v1"
        assert s.irodori.voice == "kobayashi"
        # Other fields should remain default
        assert s.irodori.enabled is False
        assert s.irodori.timeout_seconds == 30

    def test_env_override_data_root(self, monkeypatch):
        monkeypatch.setenv("NOUS_DATA_ROOT", "/custom/data")
        s = Settings()
        assert s.data_root == "/custom/data"
        assert s.data_dir == "/custom/data/memory"
        assert s.import_dir == "/custom/data/import"
        assert s.cache_dir == "/custom/data/cache"
        assert s.config_dir == "/custom/data/config"


class TestEnsureDirectories:
    """ensure_directories() should create expected directories, NOT
    sentence_transformers or torch (removed in ONNX migration)."""

    def test_creates_expected_dirs(self, tmp_path):
        s = Settings(data_root=str(tmp_path))
        s.ensure_directories()

        expected = [
            Path(s.data_dir),
            Path(s.data_root) / "logs",
            Path(s.data_root) / "backups",
            Path(s.import_dir),
            Path(s.import_dir) / "done",
            Path(s.cache_dir),
            Path(s.cache_dir) / "huggingface",
            Path(s.config_dir),
            Path(s.skills_dir),
        ]
        for d in expected:
            assert d.is_dir(), f"Missing: {d}"

    def test_no_sentence_transformers_dir(self, tmp_path):
        s = Settings(data_root=str(tmp_path))
        s.ensure_directories()
        st_dir = Path(s.cache_dir) / "sentence_transformers"
        assert not st_dir.exists()

    def test_no_torch_dir(self, tmp_path):
        s = Settings(data_root=str(tmp_path))
        s.ensure_directories()
        torch_dir = Path(s.cache_dir) / "torch"
        assert not torch_dir.exists()

    def test_idempotent(self, tmp_path):
        s = Settings(data_root=str(tmp_path))
        s.ensure_directories()
        s.ensure_directories()  # should not raise
