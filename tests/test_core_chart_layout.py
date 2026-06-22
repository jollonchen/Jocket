from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_charts_are_four_equal_2x2_cards() -> None:
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    css_source = (ROOT / "assets/styles/results_bento.css").read_text(encoding="utf-8")

    start = app_source.index('key="result_core_charts_row"')
    end = app_source.index("dashboard_code = str(", start)
    core_chart_block = app_source[start:end]

    assert 'st.columns(4, gap="small")' in core_chart_block
    assert core_chart_block.count('size="2x2"') == 4

    assert ':not(:has(.chart-size-marker))' in css_source
    final_rule = css_source[css_source.index("/* Final core-chart authority") :]
    assert "grid-template-columns: repeat(8, minmax(0, 1fr))" in final_rule
    assert "grid-column: span 2 !important" in final_rule
    assert final_rule.count("340px !important") == 3


def test_chart_headers_share_muted_label_and_semantic_status_contract() -> None:
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    css_source = (ROOT / "assets/styles/results_bento.css").read_text(encoding="utf-8")

    assert "def _score_chart_badge(" in app_source
    assert 'pill_class=trend_class' in app_source
    assert 'pill_class=vol_class' in app_source
    assert 'pill_class=pv_class' in app_source
    assert "--chart-heading-size" in css_source
    assert ".chart-title > span:first-child" in css_source
    assert ".chart-title > .pill::after" in css_source
    for tone in ("pill-green", "pill-cyan", "pill-purple", "pill-orange", "pill-red"):
        assert f".chart-title > .{tone}" in css_source


def test_compact_stock_chart_text_no_polar_for_cartesian() -> None:
    import plotly.graph_objects as go
    from app import _compact_stock_chart_text

    # 1. Cartesian figure
    fig_cartesian = go.Figure(go.Scatter(x=[1], y=[2]))
    # Before calling compacting, 'polar' is not in layout json
    assert 'polar' not in fig_cartesian.layout.to_plotly_json()

    # Apply compacting
    fig_compacted = _compact_stock_chart_text(fig_cartesian)
    # The compacted figure layout should still NOT contain 'polar' layout settings
    assert 'polar' not in fig_compacted.layout.to_plotly_json()

    # 2. Polar figure
    fig_polar = go.Figure(go.Scatterpolar(r=[1], theta=[2]))
    fig_compacted_polar = _compact_stock_chart_text(fig_polar)
    # The compacted polar figure SHOULD contain 'polar' layout settings
    assert 'polar' in fig_compacted_polar.layout.to_plotly_json()

