"""get_logger ファクトリ: "nous." プレフィックスは呼び出し名に既に付いていても 1 回だけ。"""

from __future__ import annotations

from nous.infrastructure.logging.structured import get_logger


def test_full_dotted_name_gets_single_prefix():
    """__name__ 完全修飾名（nous.application...）を渡しても nous. は1回。"""
    logger = get_logger("nous.application.chat.introspection")
    assert logger.name == "nous.application.chat.introspection"


def test_relative_name_gets_prefix():
    logger = get_logger("application.chat")
    assert logger.name == "nous.application.chat"


def test_prefixed_name_is_idempotent():
    name = "nous.domain.persona.service"
    assert get_logger(name).name == get_logger(get_logger(name).name).name
