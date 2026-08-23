package com.moneymaker.market.exception;

/**
 * Thrown by {@code HistoricalIciciMarketDataProvider} when a requested candle
 * series is entirely absent from {@code historical_spot_candles} /
 * {@code historical_option_candles}.
 *
 * <p>Backtests exist to be trusted, so a missing series is a hard error rather
 * than a warning: a run that silently traded on half its strikes produces a
 * plausible-looking but meaningless P&amp;L. {@code BacktestAnalysisService}
 * deliberately lets this type escape its per-tick and per-day catch blocks so
 * the whole run aborts naming the missing series.
 *
 * <p>This signals a <em>wholly</em> missing series, not a gap inside one.
 * Illiquid deep-ITM strikes genuinely have no candles for part of a session
 * (19500 CE has nothing before 09:55 on 2023-12-29) and must not trip it.
 */
public class HistoricalDataMissingException extends RuntimeException {

    public HistoricalDataMissingException(String message) {
        super(message);
    }
}
