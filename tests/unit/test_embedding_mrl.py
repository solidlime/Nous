"""ruri-v3-70m デフォルト化 + MRL 256 次元切り詰めの回帰テスト。

70m は graph 出力 384 次元だが、ruri-v3 系は MRL (Matryoshka) 学習なので
先頭 N 次元を切り出して L2 再正規化すれば 256 次元で使える。既存 Qdrant
コレクション（256 次元）と一致させるため ``_dimension`` は切り詰め後を返す。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nous.config.settings import EmbeddingConfig
from nous.infrastructure.embedding.model import EmbeddingModel

GRAPH_DIM = 384


def _fake_session(graph_dim: int = GRAPH_DIM) -> MagicMock:
    sess = MagicMock()
    out = MagicMock()
    out.shape = [None, None, graph_dim]
    sess.get_outputs.return_value = [out]
    return sess


def _hidden(batch: int = 2, seq: int = 5, dim: int = GRAPH_DIM, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((batch, seq, dim)).astype(np.float32)


# ---------------------------------------------------------------------------
# MRL 切り詰め — _pool
# ---------------------------------------------------------------------------


class TestMrlTruncation:
    def test_pool_truncates_to_configured_dimensions(self):
        model = EmbeddingModel(EmbeddingConfig(dimensions=256))
        hidden = _hidden()
        mask = np.ones((2, 5), dtype=np.int64)

        pooled = model._pool(hidden, mask)

        assert pooled.shape == (2, 256)
        norms = np.linalg.norm(pooled, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_pool_truncation_is_renormalised_prefix(self):
        """先頭 256 次元を切り出す前後で MRL 埋め込みが一致する（norm の差だけ）。"""
        dims = 256
        model = EmbeddingModel(EmbeddingConfig(dimensions=dims))
        full = EmbeddingModel(EmbeddingConfig(dimensions=None))
        hidden = _hidden(seed=7)
        mask = np.ones((2, 5), dtype=np.int64)

        truncated = model._pool(hidden, mask)
        prefix = full._pool(hidden, mask)[:, :dims]
        prefix = prefix / np.linalg.norm(prefix, axis=1, keepdims=True)

        np.testing.assert_allclose(truncated, prefix, atol=1e-6)

    def test_pool_full_dim_when_dimensions_none(self):
        model = EmbeddingModel(EmbeddingConfig(dimensions=None))
        hidden = _hidden()
        mask = np.ones((2, 5), dtype=np.int64)

        pooled = model._pool(hidden, mask)

        assert pooled.shape == (2, GRAPH_DIM)
        np.testing.assert_allclose(np.linalg.norm(pooled, axis=1), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# _load_model — 次元検出と切り詰め後の _dimension
# ---------------------------------------------------------------------------


class _LoadPatches:
    def __init__(self, graph_dim: int = GRAPH_DIM):
        self.graph_dim = graph_dim

    def __enter__(self):
        self._snapshot = patch("nous.infrastructure.embedding.model.snapshot_download", return_value="/tmp/fake-model")
        self._tok = patch("nous.infrastructure.embedding.model.Tokenizer")
        self._ort = patch("nous.infrastructure.embedding.model.onnxruntime.InferenceSession")
        self._snapshot.start()
        self._tok.start()
        ort_mock = self._ort.start()
        ort_mock.return_value.get_outputs.return_value = _fake_session(self.graph_dim).get_outputs.return_value
        return self

    def __exit__(self, *exc):
        self._ort.stop()
        self._tok.stop()
        self._snapshot.stop()
        return False


class TestLoadModelDimension:
    def test_dimension_is_truncated_length(self):
        with _LoadPatches():
            model = EmbeddingModel(EmbeddingConfig(dimensions=256))
            model._load_model()

        assert model._dimension == 256
        assert model.dimension == 256

    def test_dimension_is_full_when_none(self):
        with _LoadPatches():
            model = EmbeddingModel(EmbeddingConfig(dimensions=None))
            model._load_model()

        assert model._dimension == GRAPH_DIM
        assert model.dimension == GRAPH_DIM

    def test_rejects_dimensions_above_graph_dim(self):
        with _LoadPatches(graph_dim=384):
            model = EmbeddingModel(EmbeddingConfig(dimensions=512))
            with pytest.raises(ValueError, match="dimensions"):
                model._load_model()


# ---------------------------------------------------------------------------
# encode 経路（モック）— 実際に返る次元と正規化
# ---------------------------------------------------------------------------


class _FakeEncoding:
    def __init__(self, n: int = 5):
        self.ids = list(range(1, n + 1))
        self.attention_mask = [1] * n


class _FakeTokenizer:
    def __init__(self):
        self.pretrained_from: list[str] = []

    def enable_padding(self, **_kw):
        pass

    def enable_truncation(self, **_kw):
        pass

    def encode(self, _text: str) -> _FakeEncoding:
        return _FakeEncoding(5)


class TestEncodeRoute:
    def _loaded_model(self, dimensions: int | None) -> EmbeddingModel:
        model = EmbeddingModel(EmbeddingConfig(dimensions=dimensions))
        tok = _FakeTokenizer()
        sess = MagicMock()
        sess.run.return_value = [_hidden(batch=1, seq=5)]
        model._tokenizer = tok  # type: ignore[assignment]
        model._session = sess
        model._dimension = dimensions or GRAPH_DIM
        return model

    def test_encode_returns_256d_l2_normalised(self):
        model = self._loaded_model(256)
        vec = model.encode("テスト", is_query=True)

        assert vec.shape == (256,)
        assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-6

    def test_encode_returns_full_dim_when_none(self):
        model = self._loaded_model(None)
        vec = model.encode("テスト")

        assert vec.shape == (GRAPH_DIM,)
        assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-6

    def test_encode_batch_returns_256d(self):
        model = self._loaded_model(256)
        model._session.run.return_value = [_hidden(batch=2, seq=5)]
        mat = model.encode_batch(["a", "b"])

        assert mat.shape == (2, 256)
        np.testing.assert_allclose(np.linalg.norm(mat, axis=1), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# トークナイザ解決 — 70m を取り違えると埋め込みが無言で壊れる
# ---------------------------------------------------------------------------


class TestTokenizerResolution:
    def test_default_config_resolves_to_70m(self):
        model = EmbeddingModel()
        assert model._tok_name == "cl-nagoya/ruri-v3-70m"

    def test_explicit_tokenizer_wins(self):
        model = EmbeddingModel(EmbeddingConfig(tokenizer="custom/tok"))
        assert model._tok_name == "custom/tok"

    def test_load_model_uses_config_tokenizer(self):
        with _LoadPatches():
            from nous.infrastructure.embedding.model import Tokenizer

            model = EmbeddingModel(EmbeddingConfig(tokenizer="cl-nagoya/ruri-v3-70m"))
            model._load_model()

            Tokenizer.from_pretrained.assert_called_once_with("cl-nagoya/ruri-v3-70m")


# ---------------------------------------------------------------------------
# デフォルト設定（既存 256 次元コレクションと一致）
# ---------------------------------------------------------------------------


class TestEmbeddingDefaults:
    def test_default_model_is_70m_onnx(self):
        cfg = EmbeddingConfig()
        assert cfg.model == "mochiya98/ruri-v3-70m-onnx"

    def test_default_dimensions_is_256(self):
        cfg = EmbeddingConfig()
        assert cfg.dimensions == 256

    def test_dimensions_must_be_positive(self):
        with pytest.raises(ValueError):
            EmbeddingConfig(dimensions=0)

    def test_dimensions_none_allowed(self):
        assert EmbeddingConfig(dimensions=None).dimensions is None
