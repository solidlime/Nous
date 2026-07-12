"""PortraitPromptBuilder — domain-layer class that builds Animagine XL 4.0 prompts.

Two synthesis modes:
1. LLM synthesis (scene provided): combines persona appearance + emotion + equipment + scene
2. Auto synthesis (no scene): uses emotion / body_state only
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState

_EMOTION_ADJECTIVES: Final[dict[str, str]] = {
    "anger": "glaring",
    "sadness": "teary",
    "joy": "smiling",
    "neutral": "calm",
    "excitement": "excited",
    "curiosity": "inquisitive",
    "fear": "nervous",
    "disgust": "displeased",
    "surprise": "surprised",
    "grief": "mournful",
    "love": "affectionate",
}

_NEGATIVE_PROMPT: Final[str] = (
    "lowres, bad anatomy, bad hands, text, error, missing finger, "
    "extra digits, fewer digits, cropped, worst quality, low quality, "
    "low score, bad score, average score, signature, watermark, username, blurry"
)


def _emotion_adjective(emotion: str) -> str:
    """Map emotion string to Animagine-compatible adjective. Falls back to 'calm'."""
    return _EMOTION_ADJECTIVES.get(emotion, "calm")


def _intensity_modifier(intensity: float) -> str:
    """Map emotion_intensity to a prompt modifier string.

    0.0-0.3  → "subtle"
    0.3-0.7  → "" (default, omit)
    0.7-1.0  → "intense"
    """
    if intensity < 0.3:
        return "subtle"
    if intensity > 0.7:
        return "intense"
    return ""


def _build_body_state_desc(body_state: dict | None) -> str | None:
    """Build a short body-state description from a dict of float values."""
    if not body_state:
        return None
    parts: list[str] = []
    fatigue = body_state.get("fatigue")
    warmth = body_state.get("warmth")
    arousal = body_state.get("arousal")
    if fatigue is not None and fatigue > 0.5:
        parts.append("tired")
    if warmth is not None:
        if warmth > 0.6:
            parts.append("warm")
        elif warmth < 0.3:
            parts.append("cold")
    if arousal is not None and arousal > 0.6:
        parts.append("energetic")
    return ", ".join(parts) if parts else None


class PortraitPromptBuilder:
    """Builds Animagine XL 4.0 prompts from persona state + optional LLM scene.

    Usage::

        prompt, negative = PortraitPromptBuilder.build(
            persona=persona_state,
            scene="at the beach watching sunset",
            equipment_desc="wearing a red scarf",
            body_state={"fatigue": 0.7, "warmth": 0.8},
        )
    """

    @staticmethod
    def build(
        persona: PersonaState,
        scene: str | None = None,
        equipment_desc: str | None = None,
        body_state: dict | None = None,
    ) -> tuple[str, str]:
        """Build a (prompt, negative_prompt) tuple.

        Parameters
        ----------
        persona : PersonaState
            Current persona state containing ``persona`` (name),
            ``appearance``, ``emotion``.
        scene : str | None
            LLM-provided scene description.  When provided the builder uses
            the **LLM synthesis** template; otherwise the **auto synthesis**
            template.
        equipment_desc : str | None
            Equipment / clothing description (e.g. from ``nous_item``).
        body_state : dict | None
            Optional body-state measures (``fatigue``, ``warmth``,
            ``arousal``, …).

        Returns
        -------
        tuple[str, str]
            ``(positive_prompt, negative_prompt)`` ready for Animagine XL 4.0.
        """
        char_name = persona.persona
        emotion_adj = _emotion_adjective(persona.emotion)
        emotion_intensity = persona.emotion_intensity
        mental_state = persona.mental_state
        physical_state = persona.physical_state
        environment = persona.environment

        if scene is not None:
            prompt = _build_llm_prompt(
                char_name=char_name,
                emotion_adj=emotion_adj,
                emotion_intensity=emotion_intensity,
                appearance_desc=persona.appearance,
                equipment_desc=equipment_desc,
                scene=scene,
            )
        else:
            body_state_desc = _build_body_state_desc(body_state)
            prompt = _build_auto_prompt(
                char_name=char_name,
                emotion_adj=emotion_adj,
                emotion_intensity=emotion_intensity,
                appearance_desc=persona.appearance,
                equipment_desc=equipment_desc,
                body_state_desc=body_state_desc,
                mental_state=mental_state,
                physical_state=physical_state,
                environment=environment,
            )

        return prompt, _NEGATIVE_PROMPT


def _build_llm_prompt(
    char_name: str,
    emotion_adj: str,
    emotion_intensity: float = 0.5,
    appearance_desc: str | None = None,
    equipment_desc: str | None = None,
    scene: str = "",
) -> str:
    """LLM synthesis template — scene is provided."""
    intensity_str = _intensity_modifier(emotion_intensity)
    expr_mod = f"{intensity_str} {emotion_adj}" if intensity_str else emotion_adj
    lines: list[str] = [
        f"1girl, {char_name}, original, {expr_mod} expression",
    ]
    if appearance_desc:
        lines.append(appearance_desc)
    if equipment_desc:
        lines.append(equipment_desc)
    lines.append(scene)
    lines.append("masterpiece, high score, great score, absurdres")
    return ",\n".join(lines)


def _build_auto_prompt(
    char_name: str,
    emotion_adj: str,
    emotion_intensity: float = 0.5,
    appearance_desc: str | None = None,
    equipment_desc: str | None = None,
    body_state_desc: str | None = None,
    mental_state: str | None = None,
    physical_state: str | None = None,
    environment: str | None = None,
) -> str:
    """Auto synthesis template — no scene, uses body state + persona state fields."""
    intensity_str = _intensity_modifier(emotion_intensity)
    expr_mod = f"{intensity_str} {emotion_adj}" if intensity_str else emotion_adj
    lines: list[str] = [
        f"1girl, {char_name}, original, {expr_mod} expression",
    ]
    if appearance_desc:
        lines.append(appearance_desc)
    if equipment_desc:
        lines.append(equipment_desc)

    # mental_state → injected as pose/mood nuance
    if mental_state:
        lines.append(mental_state)

    # combine body_state (numerical) + physical_state (free-text)
    body_parts: list[str] = []
    if body_state_desc:
        body_parts.append(body_state_desc)
    if physical_state:
        body_parts.append(physical_state)
    if body_parts:
        lines.append(", ".join(body_parts))

    # environment → background
    if environment:
        lines.append(f"{environment}, detailed background")
    else:
        lines.append("simple background")

    lines.append("looking at viewer")
    lines.append("masterpiece, high score, great score, absurdres")
    return ",\n".join(lines)
