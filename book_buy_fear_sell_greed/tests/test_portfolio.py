import numpy as np
import pandas as pd

from fear_greed.engine import StrategyConfig
from fear_greed.portfolio import PortfolioConfig, run_portfolio


def ohlcv(close):
    close = np.asarray(close, dtype=float)
    idx = pd.bdate_range("2020-01-01", periods=len(close))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 2_000_000}, index=idx)


def trend_cycle():
    return np.r_[np.linspace(100, 130, 60), np.linspace(130, 70, 80), np.linspace(70, 120, 80)]


def test_shared_portfolio_resolves_simultaneous_signals_deterministically():
    data = {"BBB": ohlcv(trend_cycle()), "AAA": ohlcv(trend_cycle())}
    result = run_portfolio(
        data,
        StrategyConfig("vxx_trend", commission_model="Sem comissão", slippage_bps=0),
        PortfolioConfig(initial_capital=100_000, position_size_pct=100, max_gross_pct=100, max_positions=1),
    )
    first_entries = result.decisions[result.decisions.reason == "nova posição"]
    rejections = result.decisions[result.decisions.reason == "máximo de posições"]
    assert first_entries.iloc[0].ticker == "AAA"
    assert not rejections.empty
    assert result.equity.open_positions.max() == 1


def test_portfolio_marks_open_positions_to_market_every_day():
    close = np.r_[np.linspace(100, 130, 60), np.linspace(130, 70, 80)]
    result = run_portfolio(
        {"VXX": ohlcv(close)},
        StrategyConfig("vxx_trend", commission_model="Sem comissão", slippage_bps=0),
        PortfolioConfig(initial_capital=100_000, position_size_pct=50, max_gross_pct=100, max_positions=2),
    )
    active = result.equity[result.equity.open_positions > 0]
    assert len(active) > 2
    assert active.equity.nunique() > 2
    assert active.gross_exposure.nunique() > 2
    assert result.metrics["open_positions_end"] == 1


def test_leverage_multiplies_position_and_exposure_capacity():
    data = {"VXX": ohlcv(trend_cycle())}
    base = run_portfolio(
        data,
        StrategyConfig("vxx_trend", commission_model="Sem comissão", slippage_bps=0),
        PortfolioConfig(initial_capital=100_000, position_size_pct=50, max_gross_pct=100, max_positions=1, leverage=1),
    )
    leveraged = run_portfolio(
        data,
        StrategyConfig("vxx_trend", commission_model="Sem comissão", slippage_bps=0),
        PortfolioConfig(initial_capital=100_000, position_size_pct=50, max_gross_pct=100, max_positions=1, leverage=2),
    )
    base_entry = base.trades.iloc[0].tranche_notionals[0]
    leveraged_entry = leveraged.trades.iloc[0].tranche_notionals[0]
    assert leveraged_entry == 2 * base_entry
    assert leveraged.equity.configured_leverage.eq(2).all()
    assert leveraged.equity.effective_max_gross_pct.eq(200).all()
