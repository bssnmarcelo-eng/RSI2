"""Static markdown blocks shown in the UI (strategy description + disclaimer)."""

STRATEGY_DESCRIPTION = """
**Long-only mean-reversion strategy.** A long *setup* is confirmed at a candle's
**close** when **both**:

1. **RSI(2)** is below the entry threshold (default **10**), and
2. the candle is a **bullish reversal pattern** (default: **Hammer**).

Because the signal is only known once the candle closes, the realistic default is
to **enter at the next candle's open** and **exit at the next candle's open** —
this avoids look-ahead bias.
"""


DISCLAIMER = """
⚠️ **Backtest results are hypothetical.** Past performance does not guarantee
future results. Signals are generated at candle close; default entries and exits
occur at the next candle's open to avoid look-ahead bias. Test any strategy
**out-of-sample** before considering real use. This tool is for research and
education only and is **not** investment advice.
"""
