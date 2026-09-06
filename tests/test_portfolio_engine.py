"""Regression tests for shared-capital portfolio bookkeeping."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import src.portfolio_engine as portfolio_module
from src.portfolio_engine import PortfolioEngine
from src.types import (
    CostConfig,
    Execution,
    ExitConfig,
    PortfolioConfig,
    PortfolioEntryRanking,
)
from tests._helpers import make_config


def _frame(dates, closes, *, signal_at=None, rsi=None, rsi_cum=None):
    """Return a precomputed signal frame suitable for monkeypatching the builder."""
    index = pd.DatetimeIndex(dates)
    close = np.asarray(closes, dtype=float)
    signal = np.zeros(len(index), dtype=bool)
    if signal_at is not None:
        signal[signal_at] = True
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "rsi": np.asarray(rsi if rsi is not None else [10.0] * len(index)),
            "rsi_cum": np.asarray(
                rsi_cum if rsi_cum is not None else [np.nan] * len(index)
            ),
            "sma_exit": np.full(len(index), np.nan),
            "atr_mult": np.ones(len(index)),
            "entry_signal": signal,
            "pattern": np.where(signal, "Hammer", ""),
        },
        index=index,
    )


def _identity_signal_builder(monkeypatch):
    monkeypatch.setattr(portfolio_module, "build_signal_frame", lambda df, cfg: df.copy())


def _portfolio(**overrides):
    values = dict(initial_capital=10_000.0, pct_per_trade=100.0, leverage=1.0)
    values.update(overrides)
    return PortfolioConfig(**values)


def test_cumulative_rsi_exit_matches_single_asset_rule(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    frame = _frame(
        dates,
        [100, 100, 100, 103, 103],
        signal_at=1,
        rsi=[10, 10, 50, 70, 70],
        rsi_cum=[np.nan, 20, 60, 120, 140],
    )
    exits = ExitConfig(
        use_rsi_exit=False,
        use_rsi_cum_exit=True,
        rsi_cum_periods=2,
        rsi_cum_threshold=100.0,
        use_max_bars=False,
        use_profit_target=False,
        use_stop_loss=False,
        use_sma_exit=False,
        use_signal_low_stop=False,
    )
    cfg = make_config(
        exits=exits,
        entry_execution=Execution.NEXT_OPEN,
        exit_execution=Execution.SIGNAL_CLOSE,
    )

    result = PortfolioEngine({"AAA": frame}, cfg, _portfolio()).run()

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["exit_date"] == dates[3]
    assert trade["exit_reason"] == "RSI(2) acum > 100"


def test_time_stop_counts_only_the_tickers_own_bars(monkeypatch):
    _identity_signal_builder(monkeypatch)
    a_dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-06"])
    b_dates = pd.to_datetime(["2024-01-03", "2024-01-05", "2024-01-07"])
    a = _frame(a_dates, [100, 100, 100, 101], signal_at=0)
    b = _frame(b_dates, [50, 50, 50])
    exits = ExitConfig(
        use_rsi_exit=False,
        use_rsi_cum_exit=False,
        use_max_bars=True,
        max_bars=2,
        use_profit_target=False,
        use_stop_loss=False,
        use_sma_exit=False,
        use_signal_low_stop=False,
    )
    cfg = make_config(
        exits=exits,
        entry_execution=Execution.NEXT_OPEN,
        exit_execution=Execution.SIGNAL_CLOSE,
    )

    result = PortfolioEngine({"AAA": a, "BBB": b}, cfg, _portfolio()).run()

    trade = result.trades.iloc[0]
    assert trade["exit_date"] == a_dates[3]
    assert trade["bars_held"] == 2
    assert trade["exit_reason"] == "Time stop (2 bars)"


def test_short_history_position_closes_on_its_own_last_real_bar(monkeypatch):
    _identity_signal_builder(monkeypatch)
    a_dates = pd.date_range("2024-01-01", periods=3, freq="D")
    b_dates = pd.date_range("2024-01-01", periods=6, freq="D")
    a = _frame(a_dates, [100, 100, 123], signal_at=0)
    b = _frame(b_dates, [50] * len(b_dates))

    result = PortfolioEngine({"AAA": a, "BBB": b}, make_config(), _portfolio()).run()

    trade = result.trades.iloc[0]
    assert trade["ticker"] == "AAA"
    assert trade["exit_date"] == a_dates[-1]
    assert trade["exit_price"] == pytest.approx(123.0)
    assert trade["bars_held"] == 1
    assert result.positions_open.loc[a_dates[-1]] == 0
    assert result.exposure.loc[a_dates[-1]] == pytest.approx(0.0)


def test_end_of_data_force_close_resets_final_position_and_exposure(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    frame = _frame(dates, [100, 100, 110], signal_at=0)

    result = PortfolioEngine({"AAA": frame}, make_config(), _portfolio()).run()

    assert result.positions_open.iloc[-1] == 0
    assert result.exposure.iloc[-1] == pytest.approx(0.0)
    assert result.time_in_market == pytest.approx(1 / 3)
    assert result.avg_positions == pytest.approx(1 / 3)


def test_entry_commission_is_included_in_buying_power(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    frame = _frame(dates, [10, 10, 11], signal_at=0)
    cfg = make_config(
        costs=CostConfig(commission_fixed=1.0),
        entry_execution=Execution.NEXT_OPEN,
    )
    pf = _portfolio(initial_capital=100.0)
    engine = PortfolioEngine({"AAA": frame}, cfg, pf)

    result = engine.run()

    trade = result.trades.iloc[0]
    # With a $1 entry fee, only 9.9 shares fit: 9.9 * $10 + $1 = $100.
    # Infer quantity from the $1 price gain and the two fixed commissions.
    shares = trade["pnl"] + 2.0
    assert shares == pytest.approx(9.9)
    assert trade["entry_price"] * shares + 1.0 <= pf.initial_capital + 1e-9
    assert result.equity_curve.iloc[1] == pytest.approx(99.0)


def test_raw_corporate_actions_adjust_position_and_credit_dividend(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    frame = _frame(dates, [100, 100, 50], signal_at=0)
    frame["split"] = [0.0, 0.0, 2.0]
    frame["dividend"] = [0.0, 0.0, 1.0]
    cfg = make_config(apply_corporate_actions=True)

    result = PortfolioEngine({"AAA": frame}, cfg, _portfolio()).run()

    assert result.dividend_income == pytest.approx(200.0)
    assert result.equity_curve.iloc[-1] == pytest.approx(10_200.0)
    assert result.trades.iloc[0]["entry_price"] == pytest.approx(50.0)


def test_margin_interest_accrues_on_negative_cash(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    a = _frame(dates, [100, 100, 100], signal_at=0)
    b = _frame(dates, [100, 100, 100], signal_at=0)
    cfg = make_config(costs=CostConfig(annual_margin_rate=0.36525))
    pf = _portfolio(pct_per_trade=100.0, leverage=2.0, max_entries_per_date=0)

    result = PortfolioEngine({"AAA": a, "BBB": b}, cfg, pf).run()

    assert result.financing_costs == pytest.approx(10.0)
    assert result.equity_curve.iloc[-1] == pytest.approx(9_990.0)


def test_only_lowest_rsi_candidate_enters_on_the_same_date(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-05", periods=3, freq="W-FRI")
    a = _frame(dates, [100, 100, 101], signal_at=0, rsi=[6, 50, 50])
    b = _frame(dates, [100, 100, 101], signal_at=0, rsi=[2, 50, 50])
    pf = _portfolio(
        pct_per_trade=10.0,
        max_entries_per_date=1,
        entry_ranking=PortfolioEntryRanking.LOWEST_RSI,
    )

    result = PortfolioEngine({"AAA": a, "BBB": b}, make_config(), pf).run()

    assert result.trades["ticker"].tolist() == ["BBB"]
    assert result.trades["entry_date"].tolist() == [dates[1]]


def test_largest_hammer_atr_can_override_lowest_rsi(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-05", periods=3, freq="W-FRI")
    a = _frame(dates, [100, 100, 101], signal_at=0, rsi=[6, 50, 50])
    b = _frame(dates, [100, 100, 101], signal_at=0, rsi=[2, 50, 50])
    a.loc[dates[0], "atr_mult"] = 3.0
    b.loc[dates[0], "atr_mult"] = 1.5
    pf = _portfolio(
        pct_per_trade=10.0,
        max_entries_per_date=1,
        entry_ranking=PortfolioEntryRanking.LARGEST_HAMMER_ATR,
    )

    result = PortfolioEngine({"AAA": a, "BBB": b}, make_config(), pf).run()

    assert result.trades["ticker"].tolist() == ["AAA"]


def test_breadth_filter_allows_entries_at_exact_threshold(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    leader = _frame(dates, [100, 110, 110, 110], signal_at=1)
    laggard = _frame(dates, [100, 90, 90, 90])
    leader["_member"] = True
    laggard["_member"] = True
    pf = _portfolio(
        use_breadth_filter=True,
        breadth_sma_period=2,
        breadth_threshold_pct=50.0,
    )

    result = PortfolioEngine({"LEAD": leader, "LAG": laggard}, make_config(), pf).run()

    assert result.breadth.loc[dates[1]] == pytest.approx(0.5)
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["ticker"] == "LEAD"


def test_breadth_filter_blocks_new_entry_below_threshold(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    leader = _frame(dates, [100, 110, 110, 110], signal_at=1)
    laggard = _frame(dates, [100, 90, 90, 90])
    leader["_member"] = True
    laggard["_member"] = True
    pf = _portfolio(
        use_breadth_filter=True,
        breadth_sma_period=2,
        breadth_threshold_pct=51.0,
    )

    result = PortfolioEngine({"LEAD": leader, "LAG": laggard}, make_config(), pf).run()

    assert result.breadth.loc[dates[1]] == pytest.approx(0.5)
    assert result.trades.empty


def test_breadth_uses_only_point_in_time_members(monkeypatch):
    _identity_signal_builder(monkeypatch)
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    leader = _frame(dates, [100, 110, 110, 110], signal_at=1)
    former_member = _frame(dates, [100, 90, 90, 90])
    leader["_member"] = True
    former_member["_member"] = False
    pf = _portfolio(
        use_breadth_filter=True,
        breadth_sma_period=2,
        breadth_threshold_pct=100.0,
    )

    result = PortfolioEngine(
        {"LEAD": leader, "FORMER": former_member}, make_config(), pf
    ).run()

    assert result.breadth.loc[dates[1]] == pytest.approx(1.0)
    assert len(result.trades) == 1
