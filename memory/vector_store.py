"""
Qdrant ベクトルストア (Nous 版、NAS 最適化)。

MemoryMCP の vector_utils.py を VectorStore クラスとして再設計。
主な変更点:
  - Lazy singleton: 初回 search/add 時にのみモデルをロード
  - コレクション名: nous_{persona} (MemoryMCP の memory_{persona} と分離)
  - Qdrant: on_disk=True, hnsw_config.on_disk=True でディスク優先
  - バッチサイズ: 8 (NAS の RAM 制約に配慮)
  - persona を引数で受け取るステートレス設計
"""

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from config import load_config


class VectorStore:
    """ペルソナ別 Qdrant ベクトルストア。

    モデルは Lazy ロード: add() / search() が最初に呼ばれた時点でロードする。
    コンストラクタは軽量で即座に返る。

    Args:
        persona: ペルソナ名 (コレクション名: nous_{persona})
    """

    _model_lock = threading.Lock()
    # クラスレベルでモデルを共有 (メモリ節約)
    _embeddings = None
    _reranker = None

    def __init__(self, persona: str) -> None:
        self.persona = persona
        cfg = load_config()
        prefix = cfg.get("qdrant_collection_prefix", "nous_")
        # MemoryMCP の "memory_" と被らないよう "nous_" プレフィックスを使用
        self.collection_name = f"{prefix}{persona}"
        self._client = None
        self._initialized = False
        self._init_lock = threading.Lock()

    # ── 初期化 (Lazy) ────────────────────────────────────────────────────────

    def _ensure_initialized(self) -> bool:
        """モデルと Qdrant クライアントを遅延初期化する。

        Returns:
            初期化に成功した場合 True
        """
        if self._initialized:
            return True

        with self._init_lock:
            if self._initialized:
                return True

            try:
                self._load_models()
                self._client = self._create_client()
                self._ensure_collection()
                self._initialized = True
                return True
            except Exception as e:
                print(f"VectorStore init failed (persona={self.persona}): {e}")
                return False

    def _load_models(self) -> None:
        """埋め込みモデルとリランカーをクラスレベルで共有ロードする。"""
        with VectorStore._model_lock:
            if VectorStore._embeddings is not None:
                return

            from langchain_huggingface import HuggingFaceEmbeddings
            try:
                from sentence_transformers import CrossEncoder
                crossencoder_available = True
            except ImportError:
                crossencoder_available = False

            cfg = load_config()
            embeddings_model = cfg.get("embeddings_model", "cl-nagoya/ruri-v3-30m")
            device = cfg.get("embeddings_device", "cpu")
            reranker_model = cfg.get("reranker_model", "hotchpotch/japanese-reranker-xsmall-v2")

            # CPU モードなら CUDA を無効化
            if device == "cpu":
                os.environ["CUDA_VISIBLE_DEVICES"] = ""
            os.environ["TORCH_COMPILE_DISABLE"] = "1"

            # 埋め込みモデルロード (batch_size=8 で NAS のメモリ圧迫を抑える)
            VectorStore._embeddings = HuggingFaceEmbeddings(
                model_name=embeddings_model,
                model_kwargs={"device": device},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
            )
            print(f"Embeddings model loaded: {embeddings_model}")

            # リランカーロード (オプション)
            if crossencoder_available and reranker_model:
                from sentence_transformers import CrossEncoder
                try:
                    VectorStore._reranker = CrossEncoder(reranker_model, device=device)
                    print(f"Reranker model loaded: {reranker_model}")
                except Exception as e:
                    print(f"Reranker load failed: {e}")
                    VectorStore._reranker = None

    def _get_embedding_dimension(self) -> int:
        """埋め込み次元数を返す。モデルロード前に呼ばれた場合はデフォルトを返す。"""
        try:
            if VectorStore._embeddings is not None:
                from sentence_transformers import SentenceTransformer
                cfg = load_config()
                m = SentenceTransformer(cfg.get("embeddings_model", "cl-nagoya/ruri-v3-30m"))
                return int(m.get_sentence_embedding_dimension())
        except Exception:
            pass
        return 384

    def _create_client(self):
        """Qdrant クライアントを生成する。"""
        from qdrant_client import QdrantClient
        cfg = load_config()
        url = cfg.get("qdrant_url", "http://localhost:6333")
        api_key = cfg.get("qdrant_api_key")
        return QdrantClient(url=url, api_key=api_key)

    def _ensure_collection(self) -> None:
        """コレクションが存在しない場合は作成する。

        on_disk=True でディスクオフロードを有効にし、NAS の RAM を節約する。
        """
        from qdrant_client.models import (
            Distance, VectorParams, HnswConfigDiff, OptimizersConfigDiff
        )

        dim = self._get_embedding_dimension()

        existing = [c.name for c in self._client.get_collections().collections]
        if self.collection_name not in existing:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=dim,
                    distance=Distance.COSINE,
                    on_disk=True,  # ベクトルをディスクに保存 (RAM 節約)
                ),
                hnsw_config=HnswConfigDiff(
                    on_disk=True,  # HNSW インデックスもディスクに保存
                ),
                optimizers_config=OptimizersConfigDiff(
                    memmap_threshold=10000,
                ),
            )
            print(f"Qdrant collection created: {self.collection_name}")

    # ── 公開 API ─────────────────────────────────────────────────────────────

    def add(self, key: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """記憶をベクトルストアに追加する。

        Args:
            key: 記憶キー (Qdrant の point ID)
            content: 埋め込む本文
            metadata: 付加情報 dict

        Returns:
            追加に成功した場合 True
        """
        if not self._ensure_initialized():
            return False

        try:
            from qdrant_client.models import PointStruct
            vector = VectorStore._embeddings.embed_query(content)
            payload = metadata or {}
            payload["key"] = key
            payload["content"] = content

            self._client.upsert(
                collection_name=self.collection_name,
                points=[PointStruct(id=_key_to_id(key), vector=vector, payload=payload)],
            )
            return True
        except Exception as e:
            print(f"VectorStore.add failed ({key}): {e}")
            return False

    def update(self, key: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """既存記憶のベクトルを更新する (delete + add)。

        Args:
            key: 記憶キー
            content: 新しい本文
            metadata: 付加情報 dict

        Returns:
            更新に成功した場合 True
        """
        self.delete(key)
        return self.add(key, content, metadata)

    def delete(self, key: str) -> bool:
        """ベクトルストアから記憶を削除する。

        Args:
            key: 記憶キー

        Returns:
            削除に成功した場合 True
        """
        if not self._ensure_initialized():
            return False

        try:
            from qdrant_client.models import PointIdsList
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[_key_to_id(key)]),
            )
            return True
        except Exception as e:
            print(f"VectorStore.delete failed ({key}): {e}")
            return False

    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """セマンティック検索を実行する。

        リランカーが利用可能な場合は上位候補をリランクする。

        Args:
            query: 検索クエリ
            top_k: 返す結果数
            score_threshold: この値以下のスコアは除外

        Returns:
            [(key, score, payload), ...] のリスト (スコア降順)
        """
        if not self._ensure_initialized():
            return []

        try:
            cfg = load_config()
            reranker_top_n = cfg.get("reranker_top_n", 10)
            # リランカーがある場合は多めに取得してリランク
            fetch_k = max(top_k, reranker_top_n) if VectorStore._reranker else top_k

            query_vector = VectorStore._embeddings.embed_query(query)
            hits = self._client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=fetch_k,
                score_threshold=score_threshold,
            )

            results: List[Tuple[str, float, Dict[str, Any]]] = [
                (hit.payload.get("key", ""), hit.score, hit.payload)
                for hit in hits
            ]

            # リランク
            if VectorStore._reranker and results:
                pairs = [[query, r[2].get("content", "")] for r in results]
                scores = VectorStore._reranker.predict(pairs)
                reranked = sorted(
                    zip(scores, results), key=lambda x: x[0], reverse=True
                )
                results = [r for _, r in reranked]

            return results[:top_k]
        except Exception as e:
            print(f"VectorStore.search failed: {e}")
            return []

    def rebuild(self, db_path: str) -> int:
        """SQLite DB から全記憶を読み込んでコレクションを再構築する。

        Args:
            db_path: SQLite DB ファイルパス

        Returns:
            インデックスした記憶の件数
        """
        if not self._ensure_initialized():
            return 0

        try:
            # 既存コレクションを削除して再作成
            self._client.delete_collection(self.collection_name)
            self._ensure_collection()

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT key, content, tags, importance, emotion, emotion_intensity,
                           action_tag, environment, physical_state, mental_state,
                           relationship_status
                    FROM memories
                    """
                ).fetchall()

            from qdrant_client.models import PointStruct
            points = []
            for row in rows:
                (key, content, tags_json, importance, emotion, emotion_intensity,
                 action_tag, environment, physical_state, mental_state,
                 relationship_status) = row

                enriched = _build_enriched_content(
                    content=content,
                    tags_json=tags_json,
                    emotion=emotion,
                    emotion_intensity=emotion_intensity,
                    action_tag=action_tag,
                    environment=environment,
                    physical_state=physical_state,
                    mental_state=mental_state,
                    relationship_status=relationship_status,
                )

                vector = VectorStore._embeddings.embed_query(enriched)
                payload = {
                    "key": key,
                    "content": content,
                    "importance": importance,
                    "emotion": emotion,
                }
                points.append(PointStruct(id=_key_to_id(key), vector=vector, payload=payload))

                # バッチサイズ 8 で逐次アップロード (NAS のメモリ節約)
                if len(points) >= 8:
                    self._client.upsert(collection_name=self.collection_name, points=points)
                    points = []

            if points:
                self._client.upsert(collection_name=self.collection_name, points=points)

            count = len(rows)
            print(f"VectorStore.rebuild complete: {count} memories (collection={self.collection_name})")
            return count
        except Exception as e:
            print(f"VectorStore.rebuild failed: {e}")
            return 0

    def count(self) -> int:
        """コレクション内のベクトル数を返す。"""
        if not self._ensure_initialized():
            return 0
        try:
            info = self._client.get_collection(self.collection_name)
            return info.points_count or 0
        except Exception as e:
            print(f"VectorStore.count failed: {e}")
            return 0


# ── 内部ヘルパー ──────────────────────────────────────────────────────────────

def _key_to_id(key: str) -> int:
    """記憶キー文字列を Qdrant の整数 point ID に変換する。

    Qdrant は整数 ID または UUID をサポートするが、文字列キーを
    安定したハッシュで整数に変換して使用する。
    """
    return abs(hash(key)) % (2 ** 53)


def _build_enriched_content(
    content: str,
    tags_json: Optional[str] = None,
    emotion: Optional[str] = None,
    emotion_intensity: Optional[float] = None,
    action_tag: Optional[str] = None,
    environment: Optional[str] = None,
    physical_state: Optional[str] = None,
    mental_state: Optional[str] = None,
    relationship_status: Optional[str] = None,
) -> str:
    """メタデータを含む検索用エンリッチコンテンツを構築する。

    タグ・感情・環境などをテキストに追記することで
    セマンティック検索の精度を向上させる。
    """
    enriched = content

    if tags_json:
        try:
            tags_list = json.loads(tags_json)
            if tags_list:
                enriched += f"\n[Tags: {', '.join(tags_list)}]"
        except Exception:
            pass

    if emotion and emotion != "neutral":
        enriched += f"\n[Emotion: {emotion}"
        if emotion_intensity and emotion_intensity > 0.5:
            enriched += f" (intensity: {emotion_intensity:.1f})"
        enriched += "]"

    if action_tag:
        enriched += f"\n[Action: {action_tag}]"

    if environment and environment != "unknown":
        enriched += f"\n[Environment: {environment}]"

    states = []
    if physical_state and physical_state != "normal":
        states.append(f"physical:{physical_state}")
    if mental_state and mental_state != "calm":
        states.append(f"mental:{mental_state}")
    if states:
        enriched += f"\n[State: {', '.join(states)}]"

    if relationship_status and relationship_status != "normal":
        enriched += f"\n[Relationship: {relationship_status}]"

    return enriched
