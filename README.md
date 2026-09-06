# RSI(2) + Candlestick Mean-Reversion Backtester

A professional backtesting application for a long-only mean-reversion strategy,
built with Python, Pandas, NumPy, Streamlit and Plotly. CSV backtests are fully
local. The optional Norgate integration supplies screening universes, prices,
point-in-time membership and current fundamentals.

> The interface is presented in Portuguese. This README keeps established
> quantitative terms in English where they are commonly used by practitioners.

---

## The strategy

A long **setup** is confirmed at a candle's **close** when **both** conditions hold:

1. **RSI(2)** is below the entry threshold (default **10**), and
2. the candle is a **bullish reversal pattern** (default: **Hammer**).

### Modes

- **Single asset** — backtest one ticker with full per-trade detail.
- **Per-asset (independent)** — load many tickers and backtest each one
  **independently with the full capital** (no shared pool). The results view is an
  **aggregate trades panorama pooled across all assets** (ticker-agnostic): total
  trades, win/loss rate, winning/losing counts, profit factor, expectancy per
  trade, average gain/loss, best/worst trade, average holding period, a histogram
  of all trade returns, and a **table of every operation** (with its ticker) plus a
  CSV download. Use it to judge the strategy's overall edge across a universe.
- **Backtest Log** — every run (in any mode) is **saved automatically** under
  `backtest_app/logs/`: a `runs.csv` index (one summary row per run) plus a
  per-run folder with `summary.json` (full config + metrics) and the result
  tables as CSV (trades, equity, positions, all-operations, or optimization
  results). This mode lists the run history, lets you inspect/download any run's
  tables, and can clear the log. (The `logs/` folder is git-ignored.)
- **Optimizer (per-asset grid)** — grid-search the strategy's parameters over a
  universe of assets. Pick which variables to sweep (RSI period, RSI entry/exit
  thresholds, time stop, profit target, stop loss, SMA period, hammer ratios) and
  their min/max/step ranges; every combination runs the per-asset pooled backtest.
  Trades are split by entry date into **in-sample (train)** and **out-of-sample
  (test)** sets, and the objective (Sharpe per trade, expectancy, profit factor,
  win rate, or total P&L) is reported for both so you can spot overfitting (a great
  in-sample score with a poor out-of-sample score). Results include the best
  parameters, a sortable table of every combination, a heatmap when exactly two
  parameters are swept, and a CSV download. A safety cap limits the grid size.
- **Market Screening** — scan an index for tickers **currently firing the entry
  signal** on a chosen timeframe (daily, weekly, monthly). Current constituents
  and Total Return-adjusted OHLC bars come from the local Norgate database, and
  the strategy's own signal logic
  (RSI(2) + percentile hammer + ATR/price filters) is run on each ticker, so the
  screen matches the backtest exactly. Hits are listed (most oversold first) with
  a CSV download. This mode requires Windows, an active Norgate subscription,
  and Norgate Data Updater running.
- **Portfolio (shared capital)** — run the same strategy across many tickers
  sharing **one capital pool** (a real portfolio, not independent backtests).
  Buying power is modelled IBKR-style: `buying_power = equity × leverage`.
  Each position is sized as a fixed **% of equity** (notional); the number of
  simultaneous positions is therefore limited naturally by available buying
  power (plus an optional hard cap). When more signals fire on a bar than there
  is buying power for, the **most oversold names (lowest RSI) are filled first**.

  The optional **market-breadth filter** blocks new entries unless a configurable
  percentage of eligible constituents closes above its own trailing SMA. The
  initial profile uses **Breadth ≥ 50% above SMA(40)**. Existing positions are
  never liquidated by this gate. For Norgate index research, the UI requires the
  complete collection and point-in-time constituent masks so historical breadth
  is not calculated from today's membership.

  Load data either as **one CSV containing many tickers** (via a `ticker`/`symbol`
  column) or as **several single-ticker CSVs at once** (the ticker is inferred
  from each filename). Results include the combined equity curve and drawdown,
  open-positions-over-time, per-ticker P&L contribution, a per-ticker breakdown
  table, and a per-asset price/RSI drill-down.

### Execution (no look-ahead bias)

Because a signal is only known once the candle has *closed*, the realistic
default is:

| Event            | When confirmed | When executed (default) |
| ---------------- | -------------- | ----------------------- |
| Entry setup      | Candle close   | **Next candle open**    |
| Exit setup       | Candle close   | **Next candle open**    |

You may optionally switch execution to *signal close* in the sidebar, but it is
clearly labelled **less realistic** because it assumes you can trade at a price
you only observe after the bar is complete.

### Entry as a limit order (optional)

A third entry mode, **"Limit at signal close (next bar)"**, models a buy limit
order placed at the signal candle's close, valid only for the next candle:

1. the next candle **opens at/below the limit** → fill at the **open** (it gapped
   below your limit, so you buy even cheaper);
2. it **opens above** the limit but the **low retraces to/through the limit**
   (`low <= signal close`) → fill at the **limit price**;
3. it **opens above** and the **low never reaches the limit** → **no trade** (the
   order expires).

A limit order fills at the limit price or better, so **slippage is not applied**
to these fills (commissions still are).

---

## Quick start

### Novo frontend local + Norgate

O frontend redesenhado roda localmente e consulta a mesma instalação do Norgate
Data usada pelo Streamlit. Na primeira execução, instale as dependências:

```powershell
python -m pip install -e ".[api,norgate]"
cd web
npm install
cd ..
```

Com o Norgate Data Updater aberto, inicie frontend e API juntos:

```powershell
.\scripts\start_local.ps1
```

O script abre `http://127.0.0.1:3000`, mantém a API em
`http://127.0.0.1:8000` e encerra ambos com `Ctrl+C`. Os logs locais ficam em
`.local-run/`. A tela **Configurações** permite testar ou alterar o endereço da
API. Backtests, screening, otimização e fundamentos usam o Norgate local; a home
e o histórico exibem somente resultados reais da API. Os preços permanecem neste
computador; o site publicado não consegue ler diretamente o banco local do
Norgate.

### Streamlit (interface original)

```bash
cd backtest_app
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Optional integrations:

```bash
pip install -r requirements-norgate.txt    # Windows + active Norgate subscription
pip install -r requirements-dev.txt        # tests and lint
```

Run quality checks with `pytest` and `ruff check src ui tests app.py`.

### Research safeguards added

- Portfolio exits use each ticker's own bar count and close on that asset's last real bar.
- Optimizer runs train and test independently with fresh test capital and causal warm-up.
- Expanding-window walk-forward validation and parallel grid execution are available.
- Calmar, Ulcer Index, annualized volatility, benchmark comparison and Monte Carlo bootstrap.
- Optional raw-data dividends/splits and margin-interest accrual. Do not enable corporate
  actions for adjusted or Total Return series.
- Log retention is opt-in through `RSI2_LOG_MAX_RUNS` and `RSI2_LOG_MAX_AGE_DAYS`.

Streamlit opens the app in your browser. Upload a CSV, pick a ticker and date
range, adjust parameters in the sidebar, and click **Run Backtest**.

### Calls sintéticas ATM ou OTM

As duas interfaces podem manter o backtest original em ações e acrescentar uma
**equivalência em call sintética** para cada operação. O sinal, o Hammer, o
stop, o alvo, a quantidade de trades, o P&L da ação e a curva principal continuam
na periodicidade escolhida pelo usuário.

- O modelo padrão é Black-Scholes-Merton; a árvore binomial CRR é alternativa.
- O strike pode ser ATM exato, ATM arredondado para uma grade ou OTM por
  percentual. No modo OTM, o padrão é aproximadamente 10% acima do spot,
  arredondado para o intervalo de strikes configurado.
- A série escolhida (semanal, diária ou mensal) continua gerando os trades. Uma
  segunda série diária **Capital (apenas splits)** é carregada silenciosamente
  apenas para estimar IV, spot e prêmio da opção.
- A IV é estimada causalmente pela volatilidade realizada até a data da operação.
- Dividend yield histórico da Norgate, spread, comissão e DTE entram no cálculo.
  Não há rolagem: a call encerra na saída da ação ou, se o trade continuar,
  no vencimento pelo valor intrínseco.
- Cada linha mantém as colunas da ação e recebe colunas `option_*` com datas
  econômicas de entrada/saída, strike, DTE, contratos, prêmio, gregos, retorno e
  P&L equivalentes. Cenários de IV baixa, base e alta ficam em uma curva paralela.

Esses resultados são `mark-to-model`: não comprovam que o strike, vencimento,
liquidez ou preço calculado estavam disponíveis para execução no mercado.

---

## CSV format

Required columns (case/spacing-insensitive): `date`, `open`, `high`, `low`, `close`.
Optional: `ticker`/`symbol`, `adj close`/`adjusted close`, `volume`.

Column names are normalised automatically. Recognised variants include:

| Canonical   | Accepted variants                                              |
| ----------- | -------------------------------------------------------------- |
| `date`      | Date, datetime, timestamp, time                                |
| `ticker`    | Ticker, symbol, asset, instrument                              |
| `open`      | Open, o                                                        |
| `high`      | High, h                                                        |
| `low`       | Low, l                                                         |
| `close`     | Close, c, last                                                 |
| `adj_close` | Adj Close, adjusted close, adjusted_close, adj_close           |
| `volume`    | Volume, vol, v                                                 |

The loader sorts chronologically, drops duplicate dates (keeping the first),
coerces numeric types, removes rows with missing/invalid OHLC, and surfaces every
such action as a warning. Files with multiple tickers let you pick one. Daily and
intraday candles are both supported (annualised metrics infer the bar frequency
from the data).

---

## Configurable parameters (sidebar)

- **Indicator / entry**: RSI period, RSI entry threshold.
- **Price filter**: optionally only trade when the signal candle's close is within
  a price band (`>= min` and/or `<= max`, in the data's price units; 0 disables a
  bound). Useful to skip penny stocks or very expensive names.
- **Pattern**: the entry pattern is the **Hammer** (the only supported pattern).
  Tunable thresholds: lower-shadow/body ratio, max upper-shadow/body ratio, body
  position, require-bullish-close, and an optional **ATR range filter** (require
  the candle's range `high − low` to exceed `N × ATR(period)`, keeping only
  above-average-range reversal candles).
- **Execution timing**: next open (default) or signal close, independently for
  entries and exits.
- **Exit rules** (first triggered wins): RSI above threshold (default 70), time
  stop after N bars (default 5), profit target (off), % stop loss (off), close
  above SMA(n) (off), and a **stop at the signal candle's low** (off). The last
  one is a hard **intrabar** stop (unlike the close-confirmed rules): if a bar's
  low pierces the low of the candle that generated the signal, the position exits
  *within that bar* at the stop level — or at the bar's open if it gaps below the
  stop. All other exit rules remain confirmed on the close and executed per the
  chosen execution timing.
- **Position sizing (single asset)**: full equity (default), fixed capital per
  trade, or percent of equity. One open position at a time, no overlapping trades.
- **Portfolio sizing** — two modes:
  - **% of equity per trade**: shared initial capital, a fixed % of equity per
    position, **leverage** (buying-power multiple — 1× cash, ~2× Reg-T overnight,
    ~4× intraday), and an optional cap on simultaneous positions. Cash may go
    negative (margin loan) while total long exposure stays within `equity ×
    leverage`; when buying power is scarce the most oversold names fill first.
  - **Full equity per trade (unlimited margin)**: every signal opens a position at
    **100% of current equity** with **no buying-power limit and no position cap**.
    Many positions can be held at once, so gross exposure can exceed 100% (200%,
    300%, …) and cash can go deeply negative. This is a deliberately aggressive,
    fully-leveraged research setting — a leveraged basket can wipe out the account
    (the app warns if equity hits zero), so results are for study only.
- **Transaction costs** — two commission models (entry and exit each count as one
  order), plus slippage in basis points:
  - **IBKR Pro — Fixed (US stocks)** *(default)*: `USD 0.005/share`, minimum
    `USD 1.00/order`, capped at `1% of trade value` (the cap is applied last, so it
    can pull the charge below the $1 minimum on tiny trades). The per-share rate
    bundles exchange, clearing and regulatory fees. Parameters are editable.
  - **Generic**: a fixed amount per fill + a percentage of notional.

---

## Hammer definition

Percentile-based: with `range = high - low` and
`threshold = high - percentile * range`, a candle qualifies as a hammer when:

- `total_range > 0`
- `open  > threshold` — the open is in the top `percentile` of the range
- `close > threshold` — the close is in the top `percentile` of the range
- optionally `close >= open` (off by default)
- optionally `total_range > atr_multiple * ATR(atr_period)` — the **ATR range
  filter** (on by default, `atr_multiple = 1.0`, `atr_period = 14`), so only
  candles wider than the recent average true range qualify

Both open and close near the high implies a long lower shadow. `percentile`
defaults to **0.33** (≈ the classic "body in the upper third"); smaller values are
stricter (body must hug the high), larger values are looser.

---

## Outputs

- **Performance summary**: total return, CAGR, number of trades, win rate, average
  gain/loss, profit factor, expectancy, max drawdown, average holding period, best
  & worst trade, exposure, Sharpe, Sortino, final equity.
- **Charts**: price with buy/sell markers, RSI with thresholds, equity curve,
  drawdown curve, trade-return histogram, monthly-returns heatmap, yearly-returns
  bar chart.
- **Trade log** with full per-trade detail, plus **CSV downloads** for the trade
  log and the equity curve.

---

## Project structure

```
backtest_app/
  app.py                      # Streamlit UI
  requirements.txt
  README.md
  src/
    types.py                  # config + trade dataclasses (single source of params)
    utils.py                  # formatting / annualisation helpers
    data_loader.py            # CSV load, column normalisation, validation, cleaning
    indicators.py             # manual RSI (Wilder) + SMA, both causal
    candlestick_patterns.py   # objective bullish-reversal detectors
    backtest_engine.py        # single-asset event-driven engine + shared signal builder
    portfolio_engine.py       # multi-asset shared-capital engine (leverage, ranked fills)
    optimizer.py              # per-asset grid search with in/out-of-sample split
    screener.py               # market screening (Norgate constituents + adjusted OHLC)
    logger.py                 # persistent backtest log (runs index + per-run tables)
    performance_metrics.py    # metrics + monthly/yearly aggregations
    charts.py                 # Plotly figure builders
```

---

## Important assumptions & disclaimer

- Signals are generated at **candle close**.
- Default **entries and exits occur at the next candle's open** to avoid
  look-ahead bias.
- Profit-target and stop-loss rules are evaluated on the **close** (the price we
  can confirm), consistent with the close-confirmation design; they are then
  executed per the chosen execution timing.
- Any position still open at the end of the data is closed at the final candle's
  close for accounting purposes.
- **Backtest results are hypothetical. Past performance does not guarantee future
  results.** Always test a strategy **out-of-sample** before any real use. This
  software is for research and education only and is **not** investment advice.
