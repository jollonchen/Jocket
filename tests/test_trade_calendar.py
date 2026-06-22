import pandas as pd

from src.data_fetcher import DataFetcher


def test_market_date_corrects_weekday_holiday():
    result = DataFetcher._reconcile_expected_trade_date(
        pd.Timestamp("2026-06-19"),
        pd.Timestamp("2026-06-18"),
    )

    assert result == pd.Timestamp("2026-06-18")


def test_stale_market_date_cannot_move_expected_date_too_far_back():
    result = DataFetcher._reconcile_expected_trade_date(
        pd.Timestamp("2026-06-19"),
        pd.Timestamp("2026-05-29"),
    )

    assert result == pd.Timestamp("2026-06-19")


def test_future_market_date_does_not_override_pre_close_expectation():
    result = DataFetcher._reconcile_expected_trade_date(
        pd.Timestamp("2026-06-18"),
        pd.Timestamp("2026-06-19"),
    )

    assert result == pd.Timestamp("2026-06-18")
