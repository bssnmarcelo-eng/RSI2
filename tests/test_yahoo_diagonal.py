from __future__ import annotations

import pandas as pd
import pytest

from src.options.yahoo_diagonal import (
    build_diagonal_proposal,
    business_dte,
    is_standard_monthly_expiration,
    select_expiration,
    yahoo_symbol,
)


def _calls(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "contractSymbol", "strike", "bid", "ask", "openInterest",
            "impliedVolatility", "lastTradeDate",
        ],
    )


def test_symbol_and_expiration_selection():
    assert yahoo_symbol("brk.b") == "BRK-B"
    expirations = ["2026-02-06", "2026-02-20", "2026-03-27"]
    selected = select_expiration(expirations, 20, as_of="2026-01-23")
    assert selected == "2026-02-20"
    assert business_dte(selected, "2026-01-23") == 20
    assert is_standard_monthly_expiration("2026-02-20")
    assert is_standard_monthly_expiration("2025-04-17")  # Good Friday adjustment
    assert not is_standard_monthly_expiration("2026-02-13")


def test_build_diagonal_selects_strikes_sizes_and_calculates_reward_risk():
    long_calls = _calls([
        ["XYZ-L95", 95.0, 8.0, 9.0, 20, 0.30, "2026-01-20"],
        ["XYZ-L100", 100.0, 5.5, 6.0, 100, 0.28, "2026-01-20"],
        ["XYZ-L105", 105.0, 3.0, 4.0, 50, 0.27, "2026-01-20"],
    ])
    short_calls = _calls([
        ["XYZ-S105", 105.0, 4.0, 4.5, 100, 0.31, "2026-01-20"],
        ["XYZ-S110", 110.0, 2.0, 2.5, 10, 0.30, "2026-01-20"],
        ["XYZ-S115", 115.0, 0.0, 1.0, 100, 0.29, "2026-01-20"],
    ])

    proposal = build_diagonal_proposal(
        ticker="XYZ",
        spot=100.0,
        short_expiration="2026-02-20",
        long_expiration="2026-04-17",
        short_calls=short_calls,
        long_calls=long_calls,
        mfe_20d=0.10,
        mfe_60d=0.20,
        capital=100_000.0,
        risk_pct=6.0,
        min_reward_risk=3.0,
        commission_per_contract=0.0,
        as_of="2026-01-23",
    )

    assert proposal.long_call["strike"] == 100.0
    assert proposal.short_call["strike"] == 110.0
    assert proposal.debit_per_package == pytest.approx(925.0)
    assert proposal.packages == 6
    assert proposal.long_quantity == 12
    assert proposal.short_quantity == 6
    assert proposal.long_cost == pytest.approx(6_900.0)
    assert proposal.short_credit == pytest.approx(1_350.0)
    assert proposal.entry_commissions == 0.0
    assert proposal.total_debit == pytest.approx(5_550.0)
    assert proposal.required_target == pytest.approx(118.5)
    assert proposal.required_move == pytest.approx(0.185)
    assert proposal.long_target_profit == pytest.approx(17_100.0)
    assert proposal.short_target_profit == pytest.approx(1_350.0)
    assert proposal.target_profit == pytest.approx(18_450.0)
    assert proposal.reward_risk == pytest.approx(3_075.0 / 925.0)
    assert proposal.qualifies

    ratio_1_1 = build_diagonal_proposal(
        ticker="XYZ",
        spot=100.0,
        short_expiration="2026-02-20",
        long_expiration="2026-04-17",
        short_calls=short_calls,
        long_calls=long_calls,
        mfe_20d=0.10,
        mfe_60d=0.20,
        capital=100_000.0,
        risk_pct=6.0,
        min_reward_risk=3.0,
        commission_per_contract=0.0,
        longs_per_short=1,
        as_of="2026-01-23",
    )
    assert ratio_1_1.longs_per_short == 1
    assert ratio_1_1.long_quantity == ratio_1_1.short_quantity == 17
    assert ratio_1_1.debit_per_package == pytest.approx(350.0)
    assert ratio_1_1.total_debit == pytest.approx(5_950.0)
    assert ratio_1_1.required_target == pytest.approx(114.0)
    assert ratio_1_1.required_move == pytest.approx(0.14)
    assert ratio_1_1.target_profit == pytest.approx(28_050.0)
    assert ratio_1_1.reward_risk == pytest.approx(1_650.0 / 350.0)
    assert ratio_1_1.qualifies


def test_build_diagonal_rejects_quotes_without_liquidity():
    calls = _calls([
        ["XYZ", 100.0, 1.0, 2.0, 0, 0.30, "2026-01-20"],
    ])
    with pytest.raises(ValueError, match="open interest"):
        build_diagonal_proposal(
            ticker="XYZ",
            spot=100.0,
            short_expiration="2026-02-20",
            long_expiration="2026-04-17",
            short_calls=calls,
            long_calls=calls,
            mfe_20d=0.10,
            mfe_60d=0.20,
            as_of="2026-01-23",
        )
