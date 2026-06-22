from inspect import getsource
from pathlib import Path

from src import ui_components


ROOT = Path(__file__).resolve().parents[1]


def test_score_dimensions_are_collapsed_by_default():
    source = getsource(ui_components.render_dimension_cards)
    assert "expanded=False" in source
    assert "expanded=idx == 0" not in source


def test_results_css_prevents_two_by_one_card_overlap():
    css = (ROOT / "assets/styles/results_bento.css").read_text(encoding="utf-8")
    assert ":has(> .sentiment-metric-card.bento-size-2x1)" in css
    assert "grid-auto-rows: minmax(176px, auto)" in css
    assert ".research-point-grid" in css


def test_scoring_explanation_uses_card_grid():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def _render_research_explanation_panel" in app_source
    assert 'class="research-point-card"' in app_source
    assert 'st.markdown(f"- {line}")' not in app_source


def test_nested_inputs_strip_double_borders():
    css = (ROOT / "assets/jocket_final.css").read_text(encoding="utf-8")
    assert '.stTextInput [data-testid="stTextInputRootElement"] [data-baseweb="input"]' in css
    assert '.stDateInput [data-testid="stDateInputField"] [data-baseweb="input"]' in css

