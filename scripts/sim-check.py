"""ユーザーメッセージとリフレクション記憶のコサイン類似度を実測する（直注入ゲート検証）。
使い方: python scripts/sim-check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nous.infrastructure.embedding.model import EmbeddingModel

model = EmbeddingModel()

queries = [
    "不安になったときって、どう扱えばいいんだろう？",
    "朝の習慣が続けられてるんだけど、応援ってやっぱり原動力になると思う？",
    "自転車のタイヤの空気圧ってどのくらいがいいと思う？",
]
reflections = [
    ("600323", "私は、不安を否定せずに核心を短く確認し、皮肉を少し交えながらも相手のことを気遣う対話を大切にしている。"),
    ("283142", "私は、タイヤの空気圧のような小さな細部へのこだわりを通じて、自分の関心や「好き」を少しずつ言語化している。"),
    ("948414", "私は、朝のランニングから自転車通勤へと活動を広げながら、無理なく習慣を積み上げる方向に進んでいると感じる。"),
    ("486339", "ユーザーにとって朝の習慣と応援対象は努力を継続する原動力であり、私にとってこのルーティンそのものが、信頼関係の基盤になっている。"),
]
qvecs = [model.encode(q, is_query=True) for q in queries]
for q, qv in zip(queries, qvecs):
    print(f"QUERY: {q}")
    for key, content in reflections:
        rv = model.encode(content, is_query=False)
        dot = sum(a * b for a, b in zip(qv, rv))
        print(f"  {key}: {dot:.4f}")
