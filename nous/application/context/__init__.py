"""AppContext の責務分割パッケージ（composition root の内部委譲先）。

- vector_stack:   ベクトル検証スタック（初期化・プロパティ・ベクトル系イベント購読）
- event_handlers: tool.called 系ハンドラ + メモリ co-access 追跡
- lifecycle:      session_id 状態と close 系

各クラスは mixin として AppContext（nous/application/use_cases.py）が継承する。
公開属性・メソッド・プロパティの名前と意味は不変（呼び出し側・テスト互換）。
"""

from nous.application.context.event_handlers import EventHandlersMixin
from nous.application.context.lifecycle import LifecycleMixin
from nous.application.context.vector_stack import VectorStackMixin

__all__ = ["EventHandlersMixin", "LifecycleMixin", "VectorStackMixin"]
