"""Tests for lightweight entity graph: extractor, service, and SQLite repository."""

from __future__ import annotations

import pytest

from nous.domain.memory.entity_extractor import SimpleEntityExtractor
from nous.domain.memory.graph import Entity, EntityRelation, EntityService
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def entity_repo(sqlite_conn):
    return SQLiteEntityRepository(sqlite_conn)


@pytest.fixture
def extractor():
    return SimpleEntityExtractor()


@pytest.fixture
def entity_service(entity_repo, extractor):
    return EntityService(entity_repo, extractor)


# ===========================================================================
# SimpleEntityExtractor
# ===========================================================================


class TestSimpleEntityExtractor:
    def test_extract_katakana_names(self, extractor: SimpleEntityExtractor):
        """カタカナ名が人名として抽出される"""
        results = extractor.extract("ヘルタとニィロウが話した")
        names = {name for name, _ in results}
        assert "ヘルタ" in names
        assert "ニィロウ" in names
        for name, etype in results:
            if name in ("ヘルタ", "ニィロウ"):
                assert etype == "person"

    def test_extract_places(self, extractor: SimpleEntityExtractor):
        """場所サフィックスが場所として抽出される"""
        results = extractor.extract("東京駅で待ち合わせ")
        places = [(name, etype) for name, etype in results if etype == "place"]
        assert len(places) >= 1
        assert any("東京駅" in name for name, _ in places)

    def test_no_duplicates(self, extractor: SimpleEntityExtractor):
        """重複エンティティは除去される"""
        results = extractor.extract("ヘルタとヘルタが会った")
        herta_count = sum(1 for name, _ in results if name == "ヘルタ")
        assert herta_count == 1

    def test_empty_text(self, extractor: SimpleEntityExtractor):
        """空テキストは空リスト"""
        assert extractor.extract("") == []
        assert extractor.extract(None) == []

    def test_stopwords_excluded(self, extractor: SimpleEntityExtractor):
        """ストップワードは抽出されない"""
        results = extractor.extract("メモリとデータとテストを確認する")
        names = {name for name, _ in results}
        assert "メモリ" not in names
        assert "データ" not in names
        assert "テスト" not in names

    def test_mixed_places_and_persons(self, extractor: SimpleEntityExtractor):
        """場所と人名が正しく分類される"""
        results = extractor.extract("カフカが東京タワーを訪れた")
        type_map = {name: etype for name, etype in results}
        assert type_map.get("カフカ") == "person"
        assert type_map.get("東京タワー") == "place"

    def test_single_char_katakana_excluded(self, extractor: SimpleEntityExtractor):
        """1文字カタカナは抽出されない"""
        results = extractor.extract("ア")
        assert len(results) == 0


# ===========================================================================
# SQLiteEntityRepository
# ===========================================================================


class TestSQLiteEntityRepository:
    def test_save_and_get_entity(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity = Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now)
        result = entity_repo.save_entity(entity)
        assert result.is_ok

        get_result = entity_repo.get_entity("ヘルタ")
        assert get_result.is_ok
        found = get_result.value
        assert found is not None
        assert found.id == "ヘルタ"
        assert found.entity_type == "person"
        assert found.mention_count == 1

    def test_save_entity_increments_mention_count(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity = Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now)
        entity_repo.save_entity(entity)
        entity_repo.save_entity(entity)
        entity_repo.save_entity(entity)

        get_result = entity_repo.get_entity("ヘルタ")
        assert get_result.is_ok
        assert get_result.value.mention_count == 3

    def test_get_nonexistent_entity(self, entity_repo: SQLiteEntityRepository):
        result = entity_repo.get_entity("not_exists")
        assert result.is_ok
        assert result.value is None

    def test_find_entities(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_entity(Entity(id="カフカ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_entity(Entity(id="東京駅", entity_type="place", first_seen=now, last_seen=now))

        # Search all
        result = entity_repo.find_entities("")
        assert result.is_ok
        assert len(result.value) == 3

        # Search by type
        result = entity_repo.find_entities("", entity_type="person")
        assert result.is_ok
        assert len(result.value) == 2

        # Search by name pattern
        result = entity_repo.find_entities("ヘルタ")
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].id == "ヘルタ"

    def test_save_relation(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_entity(Entity(id="カフカ", entity_type="person", first_seen=now, last_seen=now))

        rel = EntityRelation(
            source_entity="ヘルタ",
            target_entity="カフカ",
            relation_type="knows",
            created_at=now,
        )
        result = entity_repo.save_relation(rel)
        assert result.is_ok

        rels_result = entity_repo.get_relations("ヘルタ")
        assert rels_result.is_ok
        assert len(rels_result.value) == 1
        assert rels_result.value[0].relation_type == "knows"

    def test_save_relation_ignores_duplicates(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="a", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_entity(Entity(id="b", entity_type="person", first_seen=now, last_seen=now))
        rel = EntityRelation(source_entity="a", target_entity="b", relation_type="knows", created_at=now)
        entity_repo.save_relation(rel)
        entity_repo.save_relation(rel)  # duplicate — should be ignored
        rels_result = entity_repo.get_relations("a")
        assert rels_result.is_ok
        assert len(rels_result.value) == 1

    def test_get_relations_directional(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="a", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_entity(Entity(id="b", entity_type="person", first_seen=now, last_seen=now))
        rel = EntityRelation(source_entity="a", target_entity="b", relation_type="knows", created_at=now)
        entity_repo.save_relation(rel)

        outgoing = entity_repo.get_relations("a", direction="outgoing")
        assert outgoing.is_ok
        assert len(outgoing.value) == 1

        incoming = entity_repo.get_relations("a", direction="incoming")
        assert incoming.is_ok
        assert len(incoming.value) == 0

        both = entity_repo.get_relations("a", direction="both")
        assert both.is_ok
        assert len(both.value) == 1

    def test_memory_entity_link(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now))

        result = entity_repo.link_memory_entity("mem_001", "ヘルタ")
        assert result.is_ok

        mems = entity_repo.get_entity_memories("ヘルタ")
        assert mems.is_ok
        assert "mem_001" in mems.value

        ents = entity_repo.get_memory_entities("mem_001")
        assert ents.is_ok
        assert len(ents.value) == 1
        assert ents.value[0].id == "ヘルタ"

    def test_link_memory_entity_ignore_duplicate(self, entity_repo: SQLiteEntityRepository):
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.link_memory_entity("mem_001", "ヘルタ")
        entity_repo.link_memory_entity("mem_001", "ヘルタ")  # duplicate
        mems = entity_repo.get_entity_memories("ヘルタ")
        assert mems.is_ok
        assert len(mems.value) == 1

    def test_get_entity_graph_depth(self, entity_repo: SQLiteEntityRepository):
        """depth指定でグラフ取得"""
        now = format_iso(get_now())
        for eid in ("a", "b", "c"):
            entity_repo.save_entity(Entity(id=eid, entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_relation(
            EntityRelation(source_entity="a", target_entity="b", relation_type="knows", created_at=now)
        )
        entity_repo.save_relation(
            EntityRelation(source_entity="b", target_entity="c", relation_type="knows", created_at=now)
        )
        entity_repo.link_memory_entity("mem_001", "a")

        # depth=1 should find b but not c
        graph1 = entity_repo.get_entity_graph("a", depth=1)
        assert graph1.is_ok
        g = graph1.value
        assert g.center.id == "a"
        related_ids_1 = {e.id for e in g.related_entities}
        assert "b" in related_ids_1
        assert "c" not in related_ids_1

        # depth=2 should find both b and c
        graph2 = entity_repo.get_entity_graph("a", depth=2)
        assert graph2.is_ok
        related_ids_2 = {e.id for e in graph2.value.related_entities}
        assert "b" in related_ids_2
        assert "c" in related_ids_2

    def test_get_entity_graph_nonexistent(self, entity_repo: SQLiteEntityRepository):
        result = entity_repo.get_entity_graph("nonexistent")
        assert not result.is_ok


# ===========================================================================
# EntityService
# ===========================================================================


class TestEntityService:
    def test_extract_and_link(self, entity_service: EntityService, entity_repo: SQLiteEntityRepository):
        """記憶からエンティティを抽出してリンクする"""
        result = entity_service.extract_and_link(
            memory_key="mem_001",
            content="ヘルタとカフカが東京タワーを訪れた",
        )
        assert result.is_ok
        entities = result.value
        entity_ids = {e.id for e in entities}
        assert "ヘルタ" in entity_ids or "ヘルタ".lower() in entity_ids
        assert "カフカ" in entity_ids or "カフカ".lower() in entity_ids

        # Verify link
        mems = entity_repo.get_entity_memories("ヘルタ")
        assert mems.is_ok
        assert "mem_001" in mems.value

    def test_extract_and_link_with_tags(self, entity_service: EntityService, entity_repo: SQLiteEntityRepository):
        """タグもエンティティとして登録される"""
        result = entity_service.extract_and_link(
            memory_key="mem_002",
            content="普通のテキスト",
            tags=["料理", "旅行"],
        )
        assert result.is_ok
        # Tags should be added as concept entities
        r1 = entity_repo.get_entity("料理")
        assert r1.is_ok and r1.value is not None
        assert r1.value.entity_type == "concept"

    def test_extract_empty_content(self, entity_service: EntityService):
        """空テキストからは何も抽出されない"""
        result = entity_service.extract_and_link("mem_003", "")
        assert result.is_ok
        assert len(result.value) == 0

    def test_get_entity_graph(self, entity_service: EntityService, entity_repo: SQLiteEntityRepository):
        """エンティティグラフを取得"""
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_entity(Entity(id="カフカ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.save_relation(
            EntityRelation(source_entity="ヘルタ", target_entity="カフカ", relation_type="knows", created_at=now)
        )
        entity_repo.link_memory_entity("mem_001", "ヘルタ")

        result = entity_service.get_entity_graph("ヘルタ")
        assert result.is_ok
        graph = result.value
        assert graph.center.id == "ヘルタ"
        assert len(graph.relations) >= 1
        assert len(graph.related_entities) >= 1
        assert "mem_001" in graph.related_memories

    def test_find_related_memories(self, entity_service: EntityService, entity_repo: SQLiteEntityRepository):
        """エンティティに関連する記憶を取得"""
        now = format_iso(get_now())
        entity_repo.save_entity(Entity(id="ヘルタ", entity_type="person", first_seen=now, last_seen=now))
        entity_repo.link_memory_entity("mem_001", "ヘルタ")
        entity_repo.link_memory_entity("mem_002", "ヘルタ")

        result = entity_service.find_related_memories("ヘルタ")
        assert result.is_ok
        assert set(result.value) == {"mem_001", "mem_002"}

    def test_add_relation(self, entity_service: EntityService, entity_repo: SQLiteEntityRepository):
        """エンティティ間の関係を追加"""
        result = entity_service.add_relation("ヘルタ", "カフカ", "knows")
        assert result.is_ok

        # Both entities should be auto-created
        assert entity_repo.get_entity("ヘルタ").value is not None
        assert entity_repo.get_entity("カフカ").value is not None

        rels = entity_repo.get_relations("ヘルタ")
        assert rels.is_ok
        assert any(r.relation_type == "knows" for r in rels.value)

    def test_add_relation_with_memory_key(self, entity_service: EntityService, entity_repo: SQLiteEntityRepository):
        """memory_key付きの関係を追加"""
        result = entity_service.add_relation("ヘルタ", "カフカ", "likes", memory_key="mem_001")
        assert result.is_ok
        rels = entity_repo.get_relations("ヘルタ")
        assert rels.is_ok
        assert any(r.memory_key == "mem_001" for r in rels.value)
