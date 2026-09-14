# Performance and Benchmark Methodology

Audited: 2026-09-14. Applies to the React benchmark, dashboard and performance
views, and the shared growth/XIRR/regression functions in `pme.py`.

## Current Account Balances

The dashboard's `accountBalances` response separates `cash`, `invested` and
`total`. Each includes `krw` (native KRW), `usd` (native USD) and `totalKrw`
(KRW conversion at the response's `fxRate`). Total native balances are cash
plus investments in the same currency; conversion is KRW + USD * fxRate.

Cash comes from the connected brokerage's `cashBuyingPower` values for each
currency. The UI identifies this as cash available for orders, which need not
equal a bank withdrawal balance or settled deposit balance. Imported trade and
holding files do not establish a cash balance. Disconnected accounts, failed
queries and missing cash fields are unavailable, distinct from an actual zero.
If one cash currency is unavailable, its cash conversion and combined total
remain unavailable; known cash and investment amounts can still be shown.

Investments are current holding market values, not purchase principal. Native
values from the brokerage and imported holdings are preserved through merging.
Legacy USD holdings with only a KRW valuation are converted back only when a
valid FX rate is present. KRW-listed overseas ETFs count as KRW holdings here,
regardless of their underlying FX exposure for performance attribution.

This section always covers all current holdings and connected-account cash.
Dividend/FX performance toggles, selected symbols and historical periods do
not filter it or replace current FX with purchase FX. It is separate from the
period-end valuation and profit metrics below it. Native USD is displayed to
the cent, and KRW conversions to the won; rounding can cause small differences
between displayed components and aggregates derived from unrounded values.

## Shared Ledger

`build_asset_value_growth` reconstructs positions in execution-time order.
Closed positions remain in performance history. Purchases, sales, remaining
average-cost basis and cash dividends are recorded separately. Korean stock
codes use the KRX listing's market to select .KS (KOSPI) or .KQ (KOSDAQ), unless
the caller explicitly specifies the market or Yahoo ticker.

Imported holdings are processed chronologically, using remaining average cost:
a sale removes its quantity's share of cost, and full liquidation resets cost to
zero. A subsequent purchase must not inherit the cost of previously sold shares.
Displayed holding average prices likewise use remaining cost / remaining shares,
not the average of all historical purchases.

Cost pools are keyed by broker, account identifier, currency and symbol. A sale
only removes average cost and purchase FX from its own pool; the resulting
realized profit and remaining cost are then summed for symbol/portfolio display.
Other accounts' low-cost purchases cannot subsidize a sale. Full liquidation
clears that pool before any subsequent purchase. This applies to the daily
ledger, performance summary, holdings breakdown and fixed-FX valuations.

Toss orders carry the queried broker/account through edits and split adjustments.
Imported trades and holding snapshots accept an optional `계좌` string column;
CSV, Excel and the transaction editor preserve it, including leading zeros.
Use stable account labels rather than credentials. Legacy files without that
column use a separate unspecified-account pool within each broker. Missing
identifiers are not inferred to refer to an explicitly identified account;
multiple accounts with the same unspecified label cannot be distinguished.
Transfers require matched source records and opening cost, not a sale funded
by unrelated accounts. An unmatched sale is unavailable, not zero profit.

The FX screen's average purchase rate now uses remaining USD cost after each
account's sales, rather than all historical purchases including closed lots.
Aggregated dividend events without account provenance use the remaining-share
weighted purchase FX for the symbol when FX is excluded.

Realized profit remains before commissions and taxes. Conversion uses historical
market USD/KRW rates, not a broker's actual FX execution or settlement rate;
these analytics are not a tax-basis or brokerage-statement reconciliation.

A missing quote, insufficient history or unmatched sale excludes that symbol's
entire transaction ledger from the aggregate, including its purchases, sales
and dividends. Healthy symbols continue to be analyzed against the same subset
of SPY contributions. Quotes are never invented or backfilled before a symbol's
available history just to produce a metric.

Dashboard and benchmark responses carry an `analysis` object with `status`,
`includedSymbols`, `excludedSymbols` and `warnings`. Partial metrics are labelled
as a subset, while account total assets retain their original account scope.
Selecting an unavailable symbol yields null performance values, not zero or
old values from another calculation. An interval after full liquidation with
no remaining assets or new purchases is `no_period_data`, even if its calendar
dates exist in the historical frame. Partial XIRR is not automatically applied
to the full account's asset projection; a manual scenario rate remains available.

Prices use Yahoo Close with `auto_adjust=False` (split-adjusted, not dividend-
adjusted). Pipeline trade quantities/prices are normalized for splits. Cash
dividends are added once. Imported dividends take precedence for a symbol;
otherwise estimates use shares held BEFORE the ex-dividend date. Historical
USD dividends are converted at the event-date exchange rate.

The valuation calendar ends at the latest available date among the included
securities and SPY, subject to an explicitly selected end date. A new Korean
trading session is not discarded just because the US session has not started.
On dates without a new quote, each asset carries its last known close forward.
`analysis.priceDates` and `analysis.benchmarkAsOf` identify actual quote dates;
`analysis.asOf` identifies the ledger's valuation date. Live quotes can change
intraday and may differ slightly from a recently cached historical quote.

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

The holdings table and editor also show **holding return**, a separate measure:

$$ HoldingReturn = (HoldingValue - RemainingCost) / RemainingCost $$

It excludes realized profit and dividends and uses the closing position's cost,
not cumulative purchases. For example, buying 10 shares at 100, selling them
at 100, then buying another 10 at 100 and valuing them at 80 produces a -20%
holding return but a -10% gross-capital ROI. The difference is a denominator
choice, not missing losses. Date-range selection changes period profit/ROI;
holding return remains the closing position's return (year-end for a past year).
`holdingUnrealizedPnL` and `holdingReturnPct` are separate API fields, while
`returnPct` continues to mean the selected period's gross-capital ROI.

Remaining basis C provides the identities:

$$ Unrealized = V - Dividends - C $$
$$ Realized = S - (B - C) $$
$$ Profit = Unrealized + Realized + Dividends $$

Period profit components are changes from the opening snapshot. The displayed
FX component is the difference between price profit with actual FX and with
fixed purchase FX, so price profit + FX profit + dividends = total profit.

The dashboard and performance summaries separately display realized profit,
unrealized profit and dividend profit for the selected interval in KRW. These
use the existing ledger components; FX is already reflected according to the
FX option and is not added a second time. Dividend exclusion shows zero with
an excluded label; unavailable components remain unavailable rather than zero.
Amounts are rounded to whole won for display, so component rounding can differ
from a rounded total by one won. For a bounded interval, unrealized profit is
the change in unrealized P&L, not the separate closing-position holding P&L.

Daily TWR assumes end-of-day external cash flows:

$$ 1+r_t = (V_t + S_t - B_t) / V_{t-1} $$

When no capital was previously invested, the initial factor is (Vt+St)/Bt;
days with no capital or contributions have factor 1. No arbitrary return
clipping is applied. Period TWR compounds only that interval's daily factors.
This is a daily approximation, not exact intraday flow-timestamp valuation.

XIRR solves NPV=0 for purchases (-), sales (+), an opening valuation (-) for
period analysis, and the final valuation (+). Dividends already in final cash
are not added again. It measures this ledger's investment strategy with retained
cash dividends, not every cash movement in the brokerage account.

The solver is PyXIRR (Actual/365 Fixed, initial guess 0.1). Cash flows on the
same calendar day are combined with compensated summation and normalized by
their largest absolute amount. Thus changing the currency unit does not change
the solution. Nonfinite amounts/invalid dates, same-day-only or one-sign flows,
and non-convergent/nonfinite solutions return no value. The previous fixed
10,000% annual-rate cap and absolute-currency convergence test were removed.
Non-conventional cash flows can have multiple IRRs; a converged root is not a
guarantee of uniqueness. XIRR is always annualized, including partial calendar
years and short holdings; a large annualized rate is not a realized one-year gain.

$$ \sum_i CF_i / (1+r)^{(d_i-d_0)/365} = 0 $$

## Calendar Years

The UI option `YOY` is labelled **Yearly (YoY)** and implements the user's
chosen calendar-year view, not a percentage-change-versus-prior-year calculation.
Select a year from the first recorded trade year through the current year.
`period=YOY&year=2025`, for example, analyzes 2025-01-01 through 2025-12-31;
the current year stops at the latest available valuation date. `analysis.asOf`
shows that actual closing date. `1Y` remains a rolling twelve-month window.

An existing position enters the calendar year at its previous December 31
value as an opening outflow; only that year's new purchases/sales are external
flows. The selected year's closing value is the terminal inflow. Trades after
year-end are excluded BEFORE validating and building the ledger, so later sales
or data errors cannot affect the historical year's profit or XIRR. Calendar
days, including leap day, are retained; 366-day growth annualizes over 366/365.

The year selection applies to ROI, XIRR, risk statistics, monthly charts,
per-stock performance and the lump-sum simulation across the three analysis
pages. Account total assets, current price/quantity and future asset projection
remain current and are labelled separately from period-end values. Automatic
projection assumptions use inception-to-date XIRR, not a past year's XIRR.
Selecting a historical year does not update daily comparison snapshots.

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

## Growth-Risk Diagnosis

The **Performance Diagnosis** page below Benchmark uses method `twr-risk-v1`.
It evaluates four separate axes instead of a weighted score: growth,
drawdown defense, variability, and efficiency of active returns. This is a
descriptive view of historical results, not a recommendation or prediction.
The endpoint is `GET /api/app/diagnosis`; authentication, dividend/FX options,
symbol selection, calendar-year boundaries and partial-data coverage are the
same as the benchmark page. The account's uninvested buying power is not part
of this strategy return; retained dividends follow the existing ledger.

All metrics derive from the existing daily TWR, not from changes in raw
portfolio value or purchase principal. Let W0=1 and Wt be the compounded daily
TWR factors within the selected interval:

$$ W_t = \prod_{i=1}^{t}(1+r_i) $$
$$ AnnualizedTWR = W_T^{365/D} - 1 $$
$$ Drawdown_t = W_t / \max(1,W_1,\ldots,W_t) - 1 $$
$$ Volatility = s(r_p)\sqrt{252} $$
$$ TrackingError = s(r_p-r_b)\sqrt{252} $$
$$ InformationRatio = \overline{(r_p-r_b)} / s(r_p-r_b)\sqrt{252} $$

Here D is actual calendar days from opening valuation to the last exposed
date, with a minimum of 365 days for annualized TWR. For an initial purchase,
elapsed time starts on that purchase date; if already invested, the prior
valuation supplies the opening date. Empty days before initial investment or
after complete withdrawal do not lengthen the observation window. Calendar
gaps inside the window remain part of elapsed time.

Drawdown includes the initial baseline, so a first-day loss is not missed.
Maximum drawdown is the daily minimum, not the minimum of monthly samples.
Both full-resolution TWR and drawdown paths are returned; the initial chart
point is a baseline rather than an additional return observation.

Risk statistics use the sample standard deviation (`ddof=1`) of weekdays
with opening/closing capital or cash-flow activity. Volatility needs at least
20 observations; information ratio and tracking error need at least 60.
Information ratio is unavailable when daily active standard deviation is no
greater than 1e-12. It uses arithmetic daily active returns, whereas cumulative
excess TWR is the difference of two compounded returns. They are not the same
calculation. Public-holiday forward fills and Korea/US close timing still
affect the observations; this is not an exchange-calendar synchronized model.

Monthly returns compound those same daily factors. Start/end months with only
partial coverage remain visible and marked partial, but are excluded from the
monthly outperformance frequency. The numerator is strictly outperforming
complete months (difference > 1e-10 pp to ignore numerical noise); ties count
in the denominator but are not wins. Months without exposure are not counted.

The comparison headline reports the signs of cumulative excess TWR and the
difference in maximum drawdown. A 0.005 pp display tolerance labels effectively
equal values as similar; there is no hidden aggregation or optimized weight.
Insufficient samples return null, not a neutral score. Nonfinite daily factors
or daily returns below -100% produce an unavailable diagnostic with a warning.
Existing cash-flow valuation assumptions and source-data limitations still apply.

Tests cover known drawdowns and recovery, contributions/withdrawals without
market gains, calendar-day annualization (including leap years), independently
calculated information ratios, zero variance, partial months, liquidation,
invalid inputs and 48 API option combinations. The UI includes both comparison
charts, monthly results, formula tooltips, method assumptions and retry/empty
states, with no changes to the pre-existing performance metrics.

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

XIRR accuracy tests include the known irregular-flow result 37.33625335%,
10%/-25%/0% annual gains across amount scales, one-day annualization, invalid
inputs, leap-year opening/closing balances and generated deposit/withdrawal
schedules with known target rates. Calendar-year API tests cover two years,
both dividend/FX flags, total/individual holdings, future-year validation,
pre-inception empty years and exclusion of later transactions.

At this audit, real-account inception and 2021-2026 annual XIRRs were independently
checked with trade-derived cash flows, a separate NPV expression and bisection.
The largest absolute NPV residual was below KRW 0.004 and the largest difference
from the reference annual rate was below 0.000001 percentage points. This checks
numerical accuracy for those inputs, not the completeness of brokerage imports.

`tests/fixture_app.py` is a LOCAL TEST-ONLY application with synthetic data and
mocked authentication/data access. Never deploy it. Run from the repository root:
`python -m uvicorn fixture_app:app --app-dir tests --host 127.0.0.1 --port 8001`.
The production entrypoint remains `webapp:app`.

To exercise mixed quote availability in the UI, use the same test server with
`fixture_app:incomplete_app --factory`. This fixture intentionally removes NVDA
quotes and retains a healthy synthetic ETF. Regression tests cover 72 mixed-data
option combinations in addition to the 48 complete-data combinations, and
KOSDAQ routing, unmatched sales, empty periods and liquidation boundaries.

Transaction-preprocessing regressions cover full liquidation and re-entry,
partial sales followed by additional purchases, displayed cost reconciliation,
buy-only averages, Korean quotes newer than the latest US session, explicit
historical end dates, and holding return versus period ROI under dividend
and date-range options. Real-account spot checks compared imported and API
trades, split/override stages and independently reconstructed average cost.

Browser checks covered 48 option combinations, chart modes, ETF selection,
rapid toggling and 390px/1440px layouts. A gated-response interception test did
not complete in the browser tool; actual rapid-click cancellation was verified.
Yearly-view browser checks covered 72 combinations (two years, dividend/FX
flags, total/individual scope and three pages), XIRR/card consistency, matching
year labels on charts, retained year selection across pages, and mobile layout.