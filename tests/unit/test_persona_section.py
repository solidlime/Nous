"""Regression: render_persona_js() must execute without NameError (drive-by F821 fix)."""

from __future__ import annotations

from nous.api.http.sections.persona import render_persona_js, render_persona_tab


def test_render_persona_tab_executes():
    assert "tab-personas" in render_persona_tab()


def test_render_persona_js_executes():
    js = render_persona_js()
    # edit/delete buttons must escape name at JS level, not Python level
    assert 'esc(name) + \'&#39;" class="glass-btn"' in js
