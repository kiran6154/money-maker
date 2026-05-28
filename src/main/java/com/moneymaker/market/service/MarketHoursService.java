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

    @Value("${app.market.force-close-time:15:25}")
    private String forceCloseStr;

    /**
     * M5.3 (GAPS #3): wider window during which {@code LoginScheduler.heartbeat}
     * is active. Outside this window the heartbeat is silent (no broker
     * probe, no Telegram). Default 07:50–15:40 IST — starts before the
     * 08:00 login cron so the heartbeat sees the post-login state quickly;
     * ends 10 min after market close so post-trading reconciliation still
     * has health signal.
     */
    @Value("${app.market.heartbeat-window-start:07:50}")
    private String heartbeatStartStr;

    @Value("${app.market.heartbeat-window-end:15:40}")
    private String heartbeatEndStr;

    private LocalTime open;
    private LocalTime close;
    private LocalTime forceClose;
    private LocalTime heartbeatStart;
    private LocalTime heartbeatEnd;
    private ZoneId zone;

    @PostConstruct
    void init() {
        this.open = LocalTime.parse(openStr.trim(), HHMM);
        this.close = LocalTime.parse(closeStr.trim(), HHMM);
        this.forceClose = LocalTime.parse(forceCloseStr.trim(), HHMM);
        this.heartbeatStart = LocalTime.parse(heartbeatStartStr.trim(), HHMM);
        this.heartbeatEnd = LocalTime.parse(heartbeatEndStr.trim(), HHMM);
        this.zone = ZoneId.of(timezoneStr.trim());
        if (!close.isAfter(open)) {
            throw new IllegalStateException(
                    "app.market.close (" + closeStr + ") must be after app.market.open (" + openStr + ")");
        }
        if (forceClose.isAfter(close) || forceClose.isBefore(open)) {
            throw new IllegalStateException(
                    "app.market.force-close-time (" + forceCloseStr + ") must lie within [open, close]");
        }
        if (!heartbeatEnd.isAfter(heartbeatStart)) {
            throw new IllegalStateException(
                    "app.market.heartbeat-window-end (" + heartbeatEndStr + ") must be after start (" + heartbeatStartStr + ")");
        }
        log.info("[market-hours] trading={}-{} force-close={} heartbeat={}-{} {} (MON-FRI)",
                open, close, forceClose, heartbeatStart, heartbeatEnd, zone);
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

    /**
     * M5.3 (GAPS #3): heartbeat window — wider than the trading window so
     * the heartbeat sees the post-login state at 08:00 and stays active for
     * a few minutes after close for reconciliation. Outside this window
     * {@code LoginScheduler.heartbeat} short-circuits.
     */
    public boolean isWithinHeartbeatWindow() {
        ZonedDateTime now = ZonedDateTime.now(zone);
        DayOfWeek dow = now.getDayOfWeek();
        if (dow == DayOfWeek.SATURDAY || dow == DayOfWeek.SUNDAY) return false;
        LocalTime t = now.toLocalTime();
        return !t.isBefore(heartbeatStart) && !t.isAfter(heartbeatEnd);
    }

    /** Today's close moment in the configured zone. */
    public LocalDateTime marketCloseToday() {
        return LocalDate.now(zone).atTime(close);
    }

    /**
     * Today's force-close moment in the configured zone (default 15:25 IST,
     * 5-min buffer before close). Used by {@code DaySummaryScheduler} to
     * anchor {@code OrderService.forceCloseOpenPositions} — leaving room
     * for the broker exit order to be accepted before the hard 15:30 cliff.
     */
    public LocalDateTime forceCloseToday() {
        return LocalDate.now(zone).atTime(forceClose);
    }

    /** Today's open moment in the configured zone. */
    public LocalDateTime marketOpenToday() {
        return LocalDate.now(zone).atTime(open);
    }

    public ZoneId zone() {
        return zone;
    }
}
