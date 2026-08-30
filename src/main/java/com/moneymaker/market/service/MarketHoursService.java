package com.moneymaker.market.service;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;

/**
 * Single source of truth for the trading window. Used by the 5-min pipeline
 * schedulers (Analysis / Order / Position) to short-circuit ticks outside
 * market hours, and by {@code DaySummaryScheduler} to anchor end-of-day work
 * at the configured close.
 *
 * <p>Defaults match Indian NFO equity-derivatives hours
 * ({@code 09:15–15:30 IST, MON-FRI}). Override via:</p>
 *
 * <pre>
 *   app.market.open=09:15
 *   app.market.close=15:30
 *   app.market.timezone=Asia/Kolkata
 * </pre>
 */
@Slf4j
@Service
public class MarketHoursService {

    private static final DateTimeFormatter HHMM = DateTimeFormatter.ofPattern("HH:mm");

    @Value("${app.market.open:09:15}")
    private String openStr;

    @Value("${app.market.close:15:30}")
    private String closeStr;

    @Value("${app.market.timezone:Asia/Kolkata}")
    private String timezoneStr;

    /**
     * Minutes before {@code app.market.close} at which the strategies' close
     * signal fires ({@code CommonRules.isMarketCloseTime}). Default 15 → 15:15
     * with the standard 15:30 close, matching the constant it replaced.
     */
    @Value("${app.market.close-signal-offset-minutes:15}")
    private int closeSignalOffsetMinutes;

    /**
     * Minutes after {@code app.market.open} at which a backtest day's first
     * tick fires. Default 5 → 09:20, matching the constant it replaced.
     */
    @Value("${app.market.replay-first-tick-offset-minutes:5}")
    private int replayFirstTickOffsetMinutes;

    /**
     * Minutes before {@code app.market.close} at which a backtest day's loop
     * stops and leftover positions are force-closed — the de-facto broker
     * square-off cutoff for index options. Default 10 → 15:20, matching the
     * constant it replaced.
     */
    @Value("${app.market.replay-last-tick-offset-minutes:10}")
    private int replayLastTickOffsetMinutes;

    private LocalTime open;
    private LocalTime close;
    private ZoneId zone;
    private LocalTime closeSignalTime;
    private LocalTime replayFirstTick;
    private LocalTime replayLastTick;

    @PostConstruct
    void init() {
        this.open = LocalTime.parse(openStr.trim(), HHMM);
        this.close = LocalTime.parse(closeStr.trim(), HHMM);
        this.zone = ZoneId.of(timezoneStr.trim());
        if (!close.isAfter(open)) {
            throw new IllegalStateException(
                    "app.market.close (" + closeStr + ") must be after app.market.open (" + openStr + ")");
        }
        this.closeSignalTime = close.minusMinutes(closeSignalOffsetMinutes);
        this.replayFirstTick = open.plusMinutes(replayFirstTickOffsetMinutes);
        this.replayLastTick = close.minusMinutes(replayLastTickOffsetMinutes);
        if (!replayFirstTick.isBefore(replayLastTick)) {
            throw new IllegalStateException("replay window is empty: first tick " + replayFirstTick
                    + " is not before last tick " + replayLastTick
                    + " (check app.market.replay-*-offset-minutes)");
        }
        if (closeSignalTime.isBefore(open) || closeSignalTime.isAfter(close)) {
            throw new IllegalStateException("close-signal time " + closeSignalTime
                    + " falls outside the session " + open + "-" + close
                    + " (check app.market.close-signal-offset-minutes)");
        }
        log.info("[market-hours] window={}-{} {} (MON-FRI), close-signal={}, replay={}-{}",
                open, close, zone, closeSignalTime, replayFirstTick, replayLastTick);
    }

    /**
     * True when the current wall-clock time (in the configured zone) is on a
     * weekday and falls in {@code [open, close]} inclusive. Inclusive of both
     * boundaries so the 15:30 tick is treated as still within hours — the
     * 15:31 day-summary cron is the first thing to fire after close.
     */
    public boolean isOpenNow() {
        ZonedDateTime now = ZonedDateTime.now(zone);
        DayOfWeek dow = now.getDayOfWeek();
        if (dow == DayOfWeek.SATURDAY || dow == DayOfWeek.SUNDAY) return false;
        LocalTime t = now.toLocalTime();
        return !t.isBefore(open) && !t.isAfter(close);
    }

    /** Today's close moment in the configured zone. */
    public LocalDateTime marketCloseToday() {
        return LocalDate.now(zone).atTime(close);
    }

    /** Today's open moment in the configured zone. */
    public LocalDateTime marketOpenToday() {
        return LocalDate.now(zone).atTime(open);
    }

    public ZoneId zone() {
        return zone;
    }

    /**
     * Configured session open. Used as the anchor when candles are aggregated to
     * a coarser timeframe, so a bar boundary falls on the open exactly as the
     * broker's own intraday bars do.
     */
    public LocalTime open() {
        return open;
    }

    /** Configured session close. */
    public LocalTime close() {
        return close;
    }

    /**
     * The time-of-day at which the strategies' market-close exit signal fires:
     * {@code close − app.market.close-signal-offset-minutes}. 15:15 by default.
     */
    public LocalTime closeSignalTime() {
        return closeSignalTime;
    }

    /**
     * First tick of a replayed backtest day:
     * {@code open + app.market.replay-first-tick-offset-minutes}. 09:20 by default.
     */
    public LocalTime replayFirstTick() {
        return replayFirstTick;
    }

    /**
     * Last tick of a replayed backtest day, after which leftover positions are
     * force-closed: {@code close − app.market.replay-last-tick-offset-minutes}.
     * 15:20 by default.
     */
    public LocalTime replayLastTick() {
        return replayLastTick;
    }
}
