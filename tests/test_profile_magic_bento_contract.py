from inspect import getsource
from unittest.mock import patch

from src.ui_components import load_css, render_company_profile


def test_profile_cards_emit_explicit_bento_sizes():
    rendered = []
    profile = {
        "name": "测试公司",
        "code": "600000",
        "yahoo_code": "600000.SS",
        "market_cap": 1_000_000_000,
        "float_market_cap": 800_000_000,
    }

    with patch("src.ui_components.st.markdown", side_effect=lambda html, **_: rendered.append(html)):
        render_company_profile(profile, "公司简介")

    html = "".join(rendered)
    assert 'profile-main-card bento-size-4x2' in html
    assert html.count('profile-kv-card bento-size-1x1') == 6


def test_profile_cards_are_registered_with_magic_bento_enhancer():
    enhancer_source = getsource(load_css)
    assert '".profile-main-card"' in enhancer_source
    assert '".profile-kv-card"' in enhancer_source
    assert '.profile-kv-card, .ta-stat-card' in enhancer_source
    assert '.profile-card, .profile-main-card, .market-cycle-card' in enhancer_source
