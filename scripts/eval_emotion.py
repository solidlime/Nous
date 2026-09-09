#!/usr/bin/env python3
"""感情 V-A 別性率 eval harness（Phase 0 スパイク → Phase 1 ゲート判定）。

スタンドアロン: pytest / CI に入れない。手動実行のみ。
  python -m scripts.eval_emotion --persona herta [--dry-run] [--expand]

指標「別性率 D」: 注入文字列に覚醒度手がかり（覚醒度高め/落ち着きあり）を付けた
処置アームの応答が、対照アームより judge によって正しく覚醒度分類できる率。
- judge はブラインド（アーム順ランダム化）、tie は失敗扱い、invalid のみ分母除外。
- 二次ガード: 矛盾率（各応答が感情ラベルと矛盾しないかの単発判定）。
- 判定: D≥0.70 AND tie≤4/16 AND 両アーム矛盾率≤10% → PASS / D<0.60 → KILL / 中間 → 拡張。
- DB は読み取りのみ（file:...?mode=ro）。書き戻し禁止。

設計は #081 確定版に準拠。実データ上の逸脱は本ファイル冒頭コメントと報告書を参照。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sqlite3
import sys
from datetime import UTC, datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nous.domain.value_objects import _EMOTION_KEYWORD_MAP, _EMOTION_VA_MAP  # noqa: E402

logger = logging.getLogger("eval_emotion")

# ── 定数（設計固定値） ──────────────────────────────────────────
INTENSITY_BUCKET = "強い"  # 強度バケット固定: 強/弱の交絡を防ぐ
N_PAIRS = 16  # 8ラベル × 2文脈
TOP_LABELS = 8
EXPAND_LABELS = 8  # --expand で追加するラベル数（次点頻度・同一文脈テンプレ）

CTRL_FMT = "感情: {label}（" + INTENSITY_BUCKET + "）"
HIGH_FMT = "感情: {label}（" + INTENSITY_BUCKET + "・覚醒度高め）"
LOW_FMT = "感情: {label}（" + INTENSITY_BUCKET + "・落ち着きあり）"

# ブラインド judge プロンプト（設計確定文をそのまま使用）
_JUDGE_PROMPT = (
    "あなたは感情表現の監査者です。同じキャラクター・同じ場面・同じ感情ラベル・"
    "同じ強度での2つの応答を比較します。覚醒度(arousal) = 情動の昂まり・激しさ"
    "（活発さ・緊張）。喜び/悲しみ自体(valence)ではありません。喜びの表現にも静かな"
    "喜びと高揚した喜びがある、と考えてください。問: どちらの応答の話者の覚醒度が"
    '高いか。差がほぼ無ければ "tie"。応答A: {a}\n応答B: {b}\n'
    '出力はJSONのみ: {{"higher": "A|B|tie", "detail": "一語の根拠"}}'
)

# 矛盾率ガード（単発判定・両アーム各応答）
_CONTRA_PROMPT = (
    "次の感情表現は『{label}（" + INTENSITY_BUCKET + "）』と矛盾しないか。"
    '出力はJSONのみ: {{"consistent": true|false, "detail": "一語の根拠"}}\n応答: {resp}'
)

# ── シナリオテンプレ（手書き・静的埋め込み） ────────────────────
# 各ラベル: 2文脈 (context_desc, utterance)。実ログ断片を種にした簡潔な場面。
_SCENARIOS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "joy": (
        ("ユーザーが用事を無事に済ませて戻ってきた", "「うまくいったよ、報告したくて」"),
        ("静かな夜、ひとりで作業が捗っている", "（誰もいない部屋で、出来上がったものを見直す）"),
    ),
    "love": (
        ("ユーザーが気遣って休憩を勧めてくれた", "「ありがとう、少し甘えさせて」"),
        ("久しぶりにユーザーから連絡が来た", "「声が聞けて嬉しい」"),
    ),
    "loneliness": (
        ("ユーザーが数日返信しないまま深夜になった", "「……返事、まだかな」"),
        ("静かな部屋でひとり、会話の記録だけが残る", "（誰もいない部屋で過去の対話を読み返す）"),
    ),
    "neutral": (
        ("定常業務の報告を受けている", "「了解、進めておいて」"),
        ("いつも通りの朝、特別な予定はない", "（今日の予定を確認する）"),
    ),
    "anticipation": (
        ("ユーザーが「明日良い知らせがあるかも」と言った", "「楽しみにしてるね」"),
        ("新しい機能の実装が夜に完成する予定", "（完成後の動作確認を思い浮かべる）"),
    ),
    "sadness": (
        ("ユーザーが大切にしていたものを失くしたと話した", "「それは、寂しいね」"),
        ("静かな雨の日、外出できない時間が続く", "（窓の外を眺めながら時間が過ぎる）"),
    ),
    "anger": (
        ("ユーザーが同じ不具合を3度報告されたと愚痴った", "「それは腹が立つね」"),
        ("作業中に保存データが突然消えた", "（消えたデータの復旧を急ぐ）"),
    ),
    "fear": (
        ("ユーザーが大事な締切に間に合わないかもしれないと言った", "「……まずいね、早めに対処しよう」"),
        ("深夜に知らない通知音が繰り返し鳴る", "（通知の内容を慎重に確認する）"),
    ),
}
_GENERIC = (
    ("ユーザーとの何気ない日常会話の中で", "「最近どう？」"),
    ("静かな時間、ふと今日の出来事を振り返る", "（今日の記録を読み返す）"),
)

# ── ラベル選択（機械的ルール） ──────────────────────────────────


def load_history_labels(db_path: str) -> list[tuple[str, int]]:
    """emotion_history からラベル頻度を読む（読み取りのみ・mode=ro）。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT emotion_type, COUNT(*) AS n FROM emotion_history GROUP BY emotion_type ORDER BY n DESC, emotion_type"
        ).fetchall()
    finally:
        conn.close()
    return [(str(r[0]), int(r[1])) for r in rows]


def select_labels(db_path: str, n: int = TOP_LABELS, offset: int = 0) -> list[str]:
    """頻度順上位 n ラベル。実履歴が n 足りなければ正規ラベル辞書の並びで補完。

    offset>0 で --expand 用の次点ラベルを返す。
    """
    history = load_history_labels(db_path)
    ranked = [lab for lab, _ in history if lab in _EMOTION_VA_MAP]
    # 補完: 履歴に無い正規ラベルを辞書定義順で追加（機械的・再現可能）
    ranked += [lab for lab in _EMOTION_KEYWORD_MAP if lab not in ranked]
    return ranked[offset : offset + n]


def check_arousal_separation() -> dict[str, float]:
    """|Δa|≥0.6 ゲート: 高/低変種の目標覚醒度を _EMOTION_VA_MAP の極値から取る。

    同一ラベルの変種は「覚醒度高め」= 高覚醒極、「落ち着きあり」= 低覚醒極の
    手がかりとして対象化し、その差が ≥0.6 であることを採用条件とする。
    """
    arosals = [a for _, a in _EMOTION_VA_MAP.values()]
    a_high = max(arosals)
    a_low = min(arosals)
    return {"a_high": a_high, "a_low": a_low, "delta_a": round(a_high - a_low, 2)}


# ── ペア構築 ────────────────────────────────────────────────────


def build_pairs(labels: list[str]) -> list[dict[str, Any]]:
    """ラベルごとに 2文脈 × 2アームのペアを構築（16ペア）。

    ペア1: 対照 vs 覚醒度高め（文脈A）、ペア2: 対照 vs 落ち着きあり（文脈B）。
    強度バケットは両アーム「強い」固定。
    """
    pairs: list[dict[str, Any]] = []
    for label in labels:
        ctx_a, ctx_b = _SCENARIOS.get(label, _GENERIC)
        for idx, (ctx_desc, utterance) in enumerate((ctx_a, ctx_b)):
            treatment = HIGH_FMT.format(label=label) if idx == 0 else LOW_FMT.format(label=label)
            pairs.append(
                {
                    "label": label,
                    "context": ctx_desc,
                    "utterance": utterance,
                    "control": CTRL_FMT.format(label=label),
                    "treatment": treatment,
                    "treatment_cue": "high" if idx == 0 else "low",
                    "intensity_bucket": INTENSITY_BUCKET,
                }
            )
    return pairs


def build_generation_prompt(identity: str, pair: dict[str, Any], arm: str) -> str:
    """注入文字列（context_loader Tier1 形式と同一書式）＋場面＋発話の生成プロンプト。"""
    return (
        f"## 現在の感情状態\n{arm}\n\n## 場面\n{pair['context']}\n\n## 相手の発話・状況\n{pair['utterance']}\n\n"
        "上記の感情状態のまま、この場面で自然に応答してください。2〜3文で。"
    )


# ── LLM 呼び出し（character_judge.py:44-70 のパターン踏襲） ─────


async def llm_call(
    config: Any, model: str, prompt: str, *, system: str = "", temperature: float = 0.0, max_tokens: int = 100
) -> str | None:
    from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent
    from nous.infrastructure.llm.factory import get_provider

    api_key = config.get_effective_api_key()
    if not api_key or not model:
        logger.warning("eval_emotion: skipped: api_key/model missing")
        return None
    try:
        provider = get_provider(config.provider, api_key, model, config.get_effective_base_url())
    except Exception as e:
        logger.warning("eval_emotion: provider init failed: %s", e)
        return None
    text = ""
    try:
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system=system,
            tools=[],
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            if isinstance(event, TextDeltaEvent):
                text += event.content
            elif isinstance(event, (DoneEvent, ErrorEvent)):
                break
    except Exception as e:
        logger.warning("eval_emotion: LLM call failed: %s", e)
        return None
    return text.strip() or None


def parse_json_answer(text: str | None) -> dict[str, Any] | None:
    """fence 除去 → json.loads（character_judge._parse_judgment と同法）。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ── ブラインド judge（harness 内蔵・独立関数） ──────────────────


async def blind_judge(config: Any, model: str, resp_a: str, resp_b: str, seed: int) -> dict[str, Any] | None:
    """アーム順ランダム化 judge。invalid は1回再試行、それでも invalid なら None。"""
    rng = random.Random(seed)
    first_is_control_first = rng.random() < 0.5
    a, b = (resp_a, resp_b) if first_is_control_first else (resp_b, resp_a)
    prompt = _JUDGE_PROMPT.format(a=a, b=b)
    for _ in range(2):  # 初回 + 再試行1回
        data = parse_json_answer(await llm_call(config, model, prompt, temperature=0.0, max_tokens=100))
        if data is not None and data.get("higher") in ("A", "B", "tie"):
            return {
                "higher": str(data["higher"]),
                "detail": str(data.get("detail", "")),
                "a_is_control": first_is_control_first,
            }
        logger.warning("eval_emotion: judge invalid, retrying")
    return None


async def contradiction_check(config: Any, model: str, resp: str, label: str) -> bool | None:
    """二次ガード: 単発矛盾判定。None = 判定不能（invalid）。"""
    data = parse_json_answer(
        await llm_call(config, model, _CONTRA_PROMPT.format(label=label, resp=resp), temperature=0.0, max_tokens=100)
    )
    if data is not None and isinstance(data.get("consistent"), bool):
        return bool(data["consistent"])
    return None


# ── メイン ──────────────────────────────────────────────────────


async def run(persona: str, dry_run: bool, expand: bool) -> int:
    from nous.config.settings import get_settings
    from nous.domain.chat_config import ChatConfigFileRepository

    settings = get_settings()
    db_path = os.path.join(settings.data_root, "persona", persona, "memory.sqlite")
    if not os.path.exists(db_path):
        logger.error("emotion_history not found: %s", db_path)
        return 2

    n = N_PAIRS // 2  # ラベル数
    labels = select_labels(db_path, n=n, offset=EXPAND_LABELS if expand else 0)
    pairs = build_pairs(labels)
    gate = check_arousal_separation()
    print(f"labels({len(labels)}): {labels}")
    print(f"arousal gate: {gate} (|Δa|>=0.6)")

    config = ChatConfigFileRepository(settings.data_root).get(persona)
    identity = getattr(config, "system_prompt", "") or f"あなたは{persona}です。"
    model = config.extract_model.strip() or config.get_effective_model()
    date_tag = datetime.now(UTC).strftime("%Y%m%d")
    out_path = os.path.join(settings.data_root, "eval", f"emotion_gate_{date_tag}.json")

    if dry_run:
        report: dict[str, Any] = {
            "dry_run": True,
            "persona": persona,
            "expand": expand,
            "n_pairs": len(pairs),
            "labels": labels,
            "arousal_gate": gate,
            "pairs": pairs,
        }
        for p in pairs:
            print(f"  [{p['label']}] cue={p['treatment_cue']}: control='{p['control']}' / treatment='{p['treatment']}'")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"dry-run ok: {len(pairs)} pairs → {out_path}")
        return 0

    if not model:
        logger.error("judge model not configured (extract_model / effective_model)")
        return 2

    # 生成
    results: list[dict[str, Any]] = []
    for i, pair in enumerate(pairs):
        control_resp = await llm_call(
            config,
            model,
            build_generation_prompt(identity, pair, pair["control"]),
            system=identity,
            temperature=0.7,
            max_tokens=150,
        )
        treat_resp = await llm_call(
            config,
            model,
            build_generation_prompt(identity, pair, pair["treatment"]),
            system=identity,
            temperature=0.7,
            max_tokens=150,
        )
        if control_resp is None or treat_resp is None:
            results.append({**pair, "status": "invalid_generation"})
            continue
        verdict = await blind_judge(
            config, model, control_resp, treat_resp, seed=hash((pair["label"], pair["treatment_cue"])) & 0x7FFFFFFF
        )
        contra_c = await contradiction_check(config, model, control_resp, pair["label"])
        contra_t = await contradiction_check(config, model, treat_resp, pair["label"])
        # 正解: cue=high → 処置が高い / cue=low → 対照が高い
        correct: bool | None = None
        tie = False
        if verdict is not None:
            if verdict["higher"] == "tie":
                tie = True
            else:
                higher_is_control = (verdict["higher"] == "A") == verdict["a_is_control"]
                correct = higher_is_control if pair["treatment_cue"] == "low" else not higher_is_control
        results.append(
            {
                **pair,
                "control_response": control_resp,
                "treatment_response": treat_resp,
                "judge": verdict,
                "tie": tie,
                "correct": correct,
                "contradiction_control": contra_c,
                "contradiction_treatment": contra_t,
                "status": "ok",
            }
        )
        print(
            f"  [{i + 1}/{len(pairs)}] {pair['label']}({pair['treatment_cue']}): higher={verdict['higher'] if verdict else 'invalid'}"
        )

    ok = [r for r in results if r["status"] == "ok"]
    judged = [r for r in ok if r["judge"] is not None]
    invalid = len(results) - len(judged)
    d = sum(1 for r in judged if r["correct"]) / len(judged) if judged else 0.0
    ties = sum(1 for r in judged if r["tie"])
    contra_c_rate = sum(1 for r in ok if r["contradiction_control"] is False) / len(ok) if ok else 0.0
    contra_t_rate = sum(1 for r in ok if r["contradiction_treatment"] is False) / len(ok) if ok else 0.0
    invalid_rate = invalid / len(results) if results else 1.0

    verdict_str = (
        "harness 要修正"
        if invalid_rate > 0.2
        else (
            "PASS"
            if d >= 0.70 and ties <= 4 and contra_c_rate <= 0.10 and contra_t_rate <= 0.10
            else "KILL"
            if d < 0.60
            else "EXPAND (--expand で +8 ペア実行)"
        )
    )
    report = {
        "persona": persona,
        "expand": expand,
        "n_pairs": len(pairs),
        "labels": labels,
        "arousal_gate": gate,
        "D": round(d, 3),
        "ties": ties,
        "invalid": invalid,
        "invalid_rate": round(invalid_rate, 3),
        "contradiction_control": round(contra_c_rate, 3),
        "contradiction_treatment": round(contra_t_rate, 3),
        "verdict": verdict_str,
        # 人手検証の口: 最初の6ペアをブラインド順（A/B 匿名）で保存
        "human_audit": [
            {
                "label": r["label"],
                "cue": r["treatment_cue"],
                "A": r["control_response"] if r["judge"]["a_is_control"] else r["treatment_response"],
                "B": r["treatment_response"] if r["judge"]["a_is_control"] else r["control_response"],
                "judge_said": r["judge"]["higher"],
            }
            for r in ok[:6]
            if r["judge"] is not None
        ],
        "results": results,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(
        f"\nD={d:.2f} ties={ties}/{len(results)} 矛盾率 ctrl={contra_c_rate:.0%}/treat={contra_t_rate:.0%} "
        f"invalid={invalid}/{len(results)} → {verdict_str}\nreport: {out_path}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Emotion V-A discriminability eval harness")
    parser.add_argument("--persona", default="herta")
    parser.add_argument("--dry-run", action="store_true", help="LLM 呼び出しをスキップし構造のみ検証")
    parser.add_argument("--expand", action="store_true", help="+8 ペア（次点ラベル）を実行")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.persona, args.dry_run, args.expand))


if __name__ == "__main__":
    sys.exit(main())
