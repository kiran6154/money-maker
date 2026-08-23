# Historical Chart Data Plan

This document captures the agreed design and implemented backend shape for
using ICICI Direct historical CSV data in the chart dashboard.

---

## Final Decision

Use the existing ICICI-style CSV exports as the source format.

Do not change the other project if it continues producing the same CSV shape.
Do not convert ICICI data into Zerodha-style tokens. Do not require
`instrumenttoken`, `instrument`, or `instrument_details` for historical charting.

The historical chart flow should use natural keys:

- spot: `stock_code + exchange_code + datetime`
- option: `stock_code + exchange_code + expiry_date + strike_price + right + datetime`

---

## Source CSV Files

The existing separate files are acceptable.

Examples:

- `NIFTY_2024-01-04_SPOT_5minute.csv`
- `NIFTY_2024-01-04_CE_5minute.csv`
- `NIFTY_2024-01-04_PE_5minute.csv`

Keeping separate SPOT, CE, and PE files is part of the agreed design.

---

## Required CSV Formats

### Spot CSV

Required header:

```csv
datetime,stock_code,exchange_code,open,high,low,close,volume
```

Example:

```csv
2023-12-29 09:15:00,NIFTY,NSE,21754.0,21770.3,21703.9,21716.2,10819194
```

### Option CSV

Required header:

```csv
datetime,stock_code,exchange_code,expiry_date,strike_price,right,open,high,low,close,volume,open_interest
```

Example:

```csv
2023-12-29 09:15:00,NIFTY,NFO,2024-01-04,19500,PE,2.35,2.85,1.7,1.95,383700,1664550
```

---

## Format Rules

The importer is deliberately tolerant, because the upstream exporter is not
consistent — the sample files under `docs/` ship in both shapes:

- `datetime` may be `yyyy-MM-dd HH:mm[:ss]` **or** `dd-MM-yyyy HH:mm[:ss]`
- `expiry_date` may be `yyyy-MM-dd` **or** `dd-MM-yyyy`
- the CE/PE column may be headed `right` **or** `option_right`
- `stock_code` should be canonical, for example `NIFTY` or `BANKNIFTY`
- the CE/PE value must be `CE` or `PE`
- candles must be 5-minute candles
- OHLC values must be numeric
- `volume` and `open_interest` should be numeric when present

Anything the parser cannot read is rejected with a `400` naming the column, the
line number, and the offending value. Rows are upserted on the natural key in
chunks, resolving each chunk's existing rows one *series* at a time.

---

## Historical Tables

Separate historical tables are used for ICICI-style chart data.

Do not force this data into the existing token-based `market_data` chart flow.

### historical_spot_candles

Purpose:

- Stores underlying/index 5-minute candles.

Columns:

```text
id
datetime
stock_code
exchange_code
open
high
low
close
volume
```

Unique key:

```text
stock_code, exchange_code, datetime
```

### historical_option_candles

Purpose:

- Stores option 5-minute candles.

Columns:

```text
id
datetime
stock_code
exchange_code
expiry_date
strike_price
option_right
open
high
low
close
volume
open_interest
```

Unique key:

```text
stock_code, exchange_code, expiry_date, strike_price, option_right, datetime
```

---

## Import Scope

Import all CSV rows that the dashboard should be able to chart.

For spot data:

- import all required `NIFTY` and `BANKNIFTY` 5-minute spot candles
- include prior-day history for SMA lookback

For option data:

- import all required expiries
- import all strikes that may become ATM
- import both CE and PE
- include prior-day history for option SMA lookback

Minimum data for one dashboard date:

- spot candles for the selected date
- enough prior spot candles for SMA lookback
- option candles for the resolved expiry
- CE candles for the calculated ATM strike
- PE candles for the calculated ATM strike

---

## Historical Dashboard Lookup Flow

### Underlying Chart

Inputs:

- `date`
- `indexSymbol`
- `timeframe`
- `smaPeriods`

Query:

```text
stock_code = indexSymbol
DATE(datetime) = selected date
```

SMA:

- compute at runtime from spot candle lows and highs (paired SMA)
- include prior-day lookback

### ATM Strike

Use selected date spot candles.

Reference price:

- first available close at or after `09:15`
- if unavailable, first available close for the selected date

Rounding:

- `NIFTY` rounds to nearest `50`
- `BANKNIFTY` rounds to nearest `100`

### Expiry Resolution

Use available `expiry_date` values from `historical_option_candles`.

Recommended rule:

- choose nearest available `expiry_date >= selected date`
- filter by `stock_code`

Important:

- Do not blindly enforce the current Tuesday/Wednesday rule for old historical
  files.
- Historical data can contain older expiry conventions, such as Thursday
  expiries.
- Weekday rules can be added later as an optional mode if needed.

### PE Chart

Query:

```text
stock_code = indexSymbol
expiry_date = resolved expiry
strike_price = calculated ATM strike
right = PE
DATE(datetime) = selected date
```

SMA:

- compute at runtime from PE candle lows and highs (paired SMA)
- include prior-day lookback for the same option series

### CE Chart

Query:

```text
stock_code = indexSymbol
expiry_date = resolved expiry
strike_price = calculated ATM strike
right = CE
DATE(datetime) = selected date
```

SMA:

- compute at runtime from CE candle lows and highs (paired SMA)
- include prior-day lookback for the same option series

---

## Timeframe Rules

Base candle interval:

- 5 minutes

Dashboard timeframes:

- `5m`: use 5-minute candles directly
- `10m`: aggregate from 5-minute candles
- `15m`: aggregate from 5-minute candles

Aggregation:

- open = first candle open
- high = max high
- low = min low
- close = last candle close
- indicators are NOT carried through buckets — they are computed after
  aggregation, on the bars actually drawn (see CHART_DASHBOARD.md)

---

## Existing Token-Based Flow

The existing token-based flow can remain for live or Zerodha-style data.

Historical ICICI charting should not depend on:

- `instrumenttoken`
- `instrument.ins_id`
- `instrument_details.instrument_token`
- synthetic tokens

The frontend response shape can remain the same, but the historical backend
service should read from historical natural-key tables.

---

## Other Project Requirements

The other project does not need structural changes if it keeps exporting the
current CSV formats.

Note: the database column is named `option_right` to avoid SQL keyword
conflicts. The CSV header may be either `right` or `option_right` — the importer
accepts both, so an exporter change is not required either way.

It must continue to guarantee:

- correct headers
- consistent date/time formats
- 5-minute candle interval
- canonical `stock_code`
- valid `right` values
- enough strikes and expiries for ATM lookup
- enough historical rows for SMA lookback

---

## Implemented Backend Pieces

- Liquibase changeset: `018_create_historical_chart_tables.xml`
- Entities: `HistoricalSpotCandle`, `HistoricalOptionCandle`
- Repositories: `HistoricalSpotCandleRepository`, `HistoricalOptionCandleRepository`
- Import service: `HistoricalChartCsvImportService`
- Import controller: `HistoricalChartImportController`
- Historical chart service: `HistoricalIciciChartDashboardService`
- Existing chart API response shape remains unchanged

## Second consumer: backtesting

These tables are no longer dashboard-only. With
`backtest.data-source=HISTORICAL_ICICI`, the backtest pipeline reads its candles
from them too, via `HistoricalIciciMarketDataProvider` and
`HistoricalOptionInstrumentResolver`. The natural-key design carries over intact —
no tokens are introduced; the keys are simply encoded into the pipeline's
`symbol` string by `HistoricalSymbol` (`HIST:NIFTY:NFO:2024-01-04:21700:CE`).

The expiry rule this document recommends — nearest available `expiry_date >=`
selected date, no weekday filter — is exactly what the backtest resolver uses, so
the 2024 Thursday weeklies in the sample files work unchanged.

See [`BACKTESTING.md` → Data source](BACKTESTING.md#data-source).

---

## CSV Import API

Spot import:

```text
POST /api/charts/historical/import/spot
```

Multipart parameter:

```text
file
```

Option import:

```text
POST /api/charts/historical/import/options
```

Multipart parameter:

```text
file
```

Example PowerShell:

```powershell
curl.exe -F "file=@docs/NIFTY_2024-01-04_SPOT_5minute.csv" http://localhost:8080/api/charts/historical/import/spot
curl.exe -F "file=@docs/NIFTY_2024-01-04_CE_5minute.csv" http://localhost:8080/api/charts/historical/import/options
curl.exe -F "file=@docs/NIFTY_2024-01-04_PE_5minute.csv" http://localhost:8080/api/charts/historical/import/options
```

Response:

```json
{
  "inserted": 100,
  "updated": 0
}
```

Existing rows with the same natural key are updated.

---

## Data Source Selection

The dashboard allows choosing between:

- `HISTORICAL_ICICI`
- `TOKEN_BASED`

Default recommendation:

- use `HISTORICAL_ICICI` for backtest and imported ICICI CSV analysis
- use `TOKEN_BASED` for the current live/Zerodha-style data path

The frontend exposes a compact data-source selector near the existing
date/index/timeframe controls.

The backend API accepts a data source request parameter:

```text
dataSource=HISTORICAL_ICICI
```

or:

```text
dataSource=TOKEN_BASED
```

The response shape remains unchanged so chart rendering does not care
which source was used.

---

## Final Review Decision

Use a dual-source chart design.

The dashboard must support both:

- historical ICICI natural-key data
- current token-based data

The two source paths should stay separate internally, but both should return the
same chart response DTOs.
