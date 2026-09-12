# Performance and Benchmark Methodology

Audited: 2026-09-12. Applies to the React benchmark, dashboard and performance
views, and the shared growth/XIRR/regression functions in `pme.py`.

## Shared Ledger

`build_asset_value_growth` reconstructs positions in execution-time order.
Closed positions remain in performance history. Purchases, sales, remaining
average-cost basis and cash dividends are recorded separately. Missing quotes
or sales without sufficient purchase history do not produce a fabricated loss.

Prices use Yahoo Close with `auto_adjust=False` (split-adjusted, not dividend-
adjusted). Pipeline trade quantities/prices are normalized for splits. Cash
dividends are added once. Imported dividends take precedence for a symbol;
otherwise estimates use shares held BEFORE the ex-dividend date. Historical
USD dividends are converted at the event-date exchange rate.

For the SPY equivalent, a purchase invests the same KRW contribution. A sale
withdraws the same fraction of the portfolio's pre-sale market value from SPY.
This is a proportional-withdrawal PME, NOT identical cash withdrawals. SPY's
own sales proceeds must therefore be used for its profit and return. Retained
dividends are cash, not reinvested shares.

## Return Definitions

For a selected interval, let V0 be value just before its first date, Vt its
current value (including retained dividends), B cumulative purchases within
the interval, and S cumulative sales proceeds within the interval.

$$ ROI = (V_t + S - V_0 - B) / (V_0 + B) $$

For inception-to-date, V0 is zero. Sales never reduce the denominator. This
is a cumulative gross-capital ROI, not an annualized return and not TWR.
Reinvesting sales proceeds counts as another purchase. Each comparison side
uses its own V0 and S. A nonpositive denominator yields no return, not zero.

Remaining basis C provides the identities:

$$ Unrealized = V - Dividends - C $$
$$ Realized = S - (B - C) $$
$$ Profit = Unrealized + Realized + Dividends $$

Period profit components are changes from the opening snapshot. The displayed
FX component is the difference between price profit with actual FX and with
fixed purchase FX, so price profit + FX profit + dividends = total profit.

Daily TWR assumes end-of-day external cash flows:

$$ 1+r_t = (V_t + S_t - B_t) / V_{t-1} $$

When no capital was previously invested, the initial factor is (Vt+St)/Bt;
days with no capital or contributions have factor 1. No arbitrary return
clipping is applied. Period TWR compounds only that interval's daily factors.
This is a daily approximation, not exact intraday flow-timestamp valuation.

XIRR solves NPV=0 for purchases (-), sales (+), an opening valuation (-) for
period analysis, and the final valuation (+). Dividends already in final cash
are not added again. Same-day-only flows have no annualized rate. The current
solver searches rates between -99.99% and 10,000%; a missing bracket returns
no value. Non-conventional cash flows can have multiple IRRs.

## Options and Statistics

- Dividend inclusion applies to both the portfolio and SPY.
- FX inclusion uses historical USD/KRW at valuation/flow dates. Exclusion
  fixes each purchase's FX, carrying a quantity-weighted average through sales.
  This applies to both unrealized value and realized sales, not just principal.
- KRW-listed, unhedged US ETFs are approximated as USD exposures by dividing
  their KRW prices by USD/KRW. Known ETF brands and US-index names are required;
  hedged funds and non-US country/global funds are not assumed USD-exposed.
  This is an exposure approximation, not the fund manager's exact FX attribution.
- Period and symbol filters apply to summary ROI, TWR, monthly excess return,
  risk statistics and the per-stock table. Monthly labels represent month-end
  samples, including the latest partial month; calculations use daily data.
- Monthly excess return is portfolio monthly TWR minus SPY monthly TWR, in pp.
- Beta is Cov(rp,rm)/Var(rm), using weekday observations and at least 20 samples.
  Rolling beta uses up to 60 such observations within the selected interval.
- Annualized regression alpha is 252 * [(mean(rp)-rf) - beta*(mean(rm)-rf)].
  Daily rf = (1.035)^(1/252)-1. Sharpe uses sqrt(252)*(mean(rp)-rf)/std(rp).
  Cumulative excess ROI, annualized regression alpha and XIRR spread are distinct.
- Relative alpha/beta contributions use ending position values and normalize
  by absolute weighted contributions. They are not an exact historical
  attribution of a dynamically rebalanced portfolio.
- Statistics with insufficient data or zero variance are unavailable, not 0.
  Display rounding may cause a 0.01 pp difference when subtracting visible ROI.
- The lump-sum simulation compares the same starting capital invested in the
  portfolio strategy (TWR) versus buy-and-hold SPY. Later deposits/withdrawals
  do not give one side additional capital. Its start is restricted to the
  selected period and available history.
- Projection uses inception-to-date XIRR as the automatic assumed annual rate.
  Monthly contributions are end-of-month ordinary-annuity payments. It is a
  scenario, not a forecast guarantee; selecting a short chart window must not
  annualize the entire historical profit over that short window.

## Limits

The model covers KRW/USD long-only trades. It does not separately model fees,
withholding taxes, bid/ask spreads, financing or exact intraday NAV. Imported
net dividends versus SPY gross estimates may differ in tax treatment. Missing
imports, price corrections and split metadata require reconciliation with the
broker. The primary source is a 10-year history, with FX fallback to the supplied
rate when historical FX is unavailable. Korean and US same-date closes are not
simultaneous; daily beta can be affected by market-hour lead/lag and must not be
interpreted as a causal measure or forced to an expected value. Account cash and
live holdings quotes can differ from historical-close performance valuations.

This audit does not certify every parser, legacy export, AI recommendation or
external data source. Real-account checks verify execution and finite results,
not reconciliation of every source transaction against brokerage statements.

## Verification

Run `python -m unittest discover -s tests -v` with the project's envPM interpreter.
Coverage includes sales, dividends, FX, dates, XIRR, missing prices, profit
identities, identical-asset beta/alpha and 48 option combinations across APIs.
Frontend gates: `tsc --noEmit` and `npm run build` in the React directory.

`tests/fixture_app.py` is a LOCAL TEST-ONLY application with synthetic data and
mocked authentication/data access. Never deploy it. Run from the repository root:
`python -m uvicorn fixture_app:app --app-dir tests --host 127.0.0.1 --port 8001`.
The production entrypoint remains `webapp:app`.

Browser checks covered 48 option combinations, chart modes, ETF selection,
rapid toggling and 390px/1440px layouts. A gated-response interception test did
not complete in the browser tool; actual rapid-click cancellation was verified.