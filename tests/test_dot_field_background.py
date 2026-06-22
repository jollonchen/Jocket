from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_COMPONENTS = (ROOT / "src" / "ui_components.py").read_text(encoding="utf-8")
FINAL_CSS = (ROOT / "assets" / "jocket_final.css").read_text(encoding="utf-8")


def test_dot_field_uses_selected_react_bits_preset() -> None:
    assert 'bulgeStrength: 36' in UI_COMPONENTS
    assert 'waveAmplitude: 1' in UI_COMPONENTS
    assert 'gradientFrom: "#0a803a"' in UI_COMPONENTS
    assert 'gradientTo: "#0e1289"' in UI_COMPONENTS


def test_dot_field_is_results_only_and_excludes_loading() -> None:
    assert (
        'const shouldBeActive = currentPage !== "AI洞察" &&\n'
        '                  doc.body.classList.contains("jocket-results-page") &&\n'
        '                  !hasLoading;'
    ) in UI_COMPONENTS
    assert 'doc.querySelector(".jocket-loading-marker")' in UI_COMPONENTS
    assert 'doc.querySelector(\'div[data-testid="stSpinner"]\')' in UI_COMPONENTS
    assert 'doc.querySelector(\'#jocket-ai-processing[data-running="true"]\')' in UI_COMPONENTS


def test_legacy_dot_field_gate_and_palette_are_removed() -> None:
    assert 'currentPage !== "AI洞察" && !hasLanding && !hasLoading' not in UI_COMPONENTS
    assert 'const bulgeStrength = 67' not in UI_COMPONENTS
    assert 'const gradientFrom = "#4a4a4a"' not in UI_COMPONENTS
    assert 'const gradientTo = "#272727"' not in UI_COMPONENTS
    assert 'doc.getElementById("jocket-dot-field")?.remove()' not in UI_COMPONENTS


def test_dot_field_canvas_and_glow_are_visible_when_mounted() -> None:
    assert '#jocket-dot-field-container.active' in FINAL_CSS
    assert '#jocket-dot-field-canvas' in FINAL_CSS
    assert '#jocket-dot-field-glow' in FINAL_CSS
    assert 'opacity: 0.78 !important;' in FINAL_CSS
    assert 'win.requestAnimationFrame(show);' not in UI_COMPONENTS
    assert 'show();\n\n                const ctx = canvas.getContext' in UI_COMPONENTS


def test_splash_background_yields_to_non_ai_results_background() -> None:
    assert 'const isResultsPage = doc.body.classList.contains("jocket-results-page");' in UI_COMPONENTS
    assert (
        'const shouldBeActive = isAiChatActive || '
        '(!isResultsPage && (hasPageG || isAiRunning));'
    ) in UI_COMPONENTS


def test_ai_chat_result_and_loading_keep_landing_background() -> None:
    assert 'const isAiChatActive = !!doc.getElementById("jocket-ai-chat-active");' in UI_COMPONENTS
    assert 'const shouldBeActive = isAiChatActive ||' in UI_COMPONENTS
    assert 'const currentPage = doc.getElementById("jocket-current-page")' in UI_COMPONENTS
    assert 'currentPage !== "AI洞察"' in UI_COMPONENTS


def test_navigation_hides_dot_field_before_streamlit_rerender() -> None:
    assert 'doc.addEventListener("pointerdown"' in UI_COMPONENTS
    assert 'win.__jocketBackgroundSwitchTarget__ = targetPage;' in UI_COMPONENTS
    assert 'win.__jocketDotField__?.hide?.();' in UI_COMPONENTS
    assert 'currentPage !== pendingTarget' in UI_COMPONENTS
    assert 'now - matchedAt < 180' in UI_COMPONENTS
    assert '120ms DOM observer debounce' in UI_COMPONENTS
    assert 'visibility", "hidden", "important"' in UI_COMPONENTS


def test_dot_field_destroy_has_no_visible_fade_out_tail() -> None:
    assert 'win.setTimeout(() => container.remove(), 240)' not in UI_COMPONENTS
    assert 'hide();\n                    container.remove();' in UI_COMPONENTS


def test_results_page_class_and_background_sync_before_debounced_card_work() -> None:
    observer_start = UI_COMPONENTS.index("const magicObserver = new MagicObserver")
    debounce_start = UI_COMPONENTS.index("if (magicRefreshTimer !== null) return;", observer_start)
    observer_head = UI_COMPONENTS[observer_start:debounce_start]

    assert "syncResultsPageState();" in observer_head
    assert "manageSplashCursor();" in observer_head
    assert "manageDotField();" in observer_head
    assert UI_COMPONENTS.index("syncResultsPageState();", observer_start) < debounce_start
