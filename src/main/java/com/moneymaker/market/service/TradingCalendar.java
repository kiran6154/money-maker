package com.moneymaker.market.service;

import java.time.LocalDate;

/**
 * Which <em>dates</em> the market trades. Complements {@link MarketHoursService},
 * which owns which <em>times</em> within a date it trades.
 *
 * <p>Exists because "weekday" is not the same thing as "trading day", and
 * assuming it is gets January 2024 wrong in both directions:
 *
 * <ul>
 *   <li><b>Saturday 2024-01-20 traded</b> — NSE ran a special live session. A
 *       weekday rule skips it, so a real session gets no configuration and is
 *       silently dropped from a backtest.</li>
 *   <li><b>Monday 2024-01-22 did not</b> — market holiday. A weekday rule targets
 *       it happily, and the day is then "replayed" against whatever candles the
 *       lookback window happens to end on, i.e. the previous session's.</li>
 * </ul>
 *
 * <p>Two implementations, selected the same way {@code OptionInstrumentResolver}
 * is:
 *
 * <ul>
 *   <li>{@link HistoricalTradingCalendar} — the dates actually present in
 *       {@code historical_spot_candles}. Active only when
 *       {@code backtest.data-source=HISTORICAL_ICICI}, where the imported data
 *       <i>is</i> the calendar.</li>
 *   <li>{@link WeekdayTradingCalendar} — Mon–Fri. The default, and what the
 *       broker path keeps using.</li>
 * </ul>
 */
public interface TradingCalendar {

    /** Short name for logs, e.g. {@code WEEKDAY} or {@code HISTORICAL_ICICI}. */
    String getName();

    /** True when {@code date} is a session the market actually held. */
    boolean isTradingDay(LocalDate date);

    /**
     * The first trading day strictly after {@code date}.
     *
     * <p>Returns {@code null} when the calendar knows of none — for the historical
     * implementation that means "the imported data ends here", which is a real
     * answer and not an error: the caller is being asked to generate configuration
     * for a day that will never be replayed.
     */
    LocalDate nextTradingDay(LocalDate date);
}
