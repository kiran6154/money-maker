package com.moneymaker.market.service;

import com.moneymaker.repository.HistoricalSpotCandleRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.NavigableSet;
import java.util.Objects;
import java.util.TreeSet;

/**
 * Trading days taken from the imported underlying candles: a date is a session
 * if {@code historical_spot_candles} has candles for it.
 *
 * <p>For a replay this is not an approximation of the calendar — it <i>is</i> the
 * calendar. A date with no candles cannot be replayed whatever the day of week
 * says, and a date with candles was a session whatever the day of week says.
 * Both cases occur in January 2024 alone: Saturday 2024-01-20 has candles (NSE's
 * special session) and Monday 2024-01-22 has none (holiday).
 *
 * <p>{@code @Primary} so it wins over {@link WeekdayTradingCalendar} wherever a
 * single {@link TradingCalendar} is injected.
 *
 * <h3>Loading</h3>
 * The date set is read once, lazily, and kept — a few hundred entries. Lazily
 * rather than in a {@code @PostConstruct} because the CSV import usually happens
 * <em>after</em> startup, so eager loading would cache an empty set on a fresh
 * database. For the same reason an empty result is not cached: it is retried on
 * the next call, so the calendar starts working as soon as data lands without
 * needing a restart.
 */
@Slf4j
@Service
@Primary
@ConditionalOnProperty(name = "backtest.data-source", havingValue = "HISTORICAL_ICICI")
public class HistoricalTradingCalendar implements TradingCalendar {

    public static final String NAME = "HISTORICAL_ICICI";

    private final HistoricalSpotCandleRepository spotCandleRepository;

    /** Null until first successfully loaded with at least one date. */
    private volatile NavigableSet<LocalDate> tradingDays;

    public HistoricalTradingCalendar(HistoricalSpotCandleRepository spotCandleRepository) {
        this.spotCandleRepository = Objects.requireNonNull(
                spotCandleRepository, "spotCandleRepository must not be null");
        log.info("TradingCalendar: {} (sessions come from historical_spot_candles)", NAME);
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public boolean isTradingDay(LocalDate date) {
        return date != null && days().contains(date);
    }

    @Override
    public LocalDate nextTradingDay(LocalDate date) {
        // higher(), not ceiling() — "strictly after", so calling this on a
        // trading day does not return that same day.
        return date == null ? null : days().higher(date);
    }

    private NavigableSet<LocalDate> days() {
        NavigableSet<LocalDate> cached = tradingDays;
        if (cached != null) {
            return cached;
        }

        NavigableSet<LocalDate> loaded = new TreeSet<>();
        for (java.sql.Date row : spotCandleRepository.findDistinctTradingDates()) {
            if (row != null) {
                loaded.add(row.toLocalDate());
            }
        }

        if (loaded.isEmpty()) {
            // Not cached — see the class Javadoc. Warn rather than fail: an empty
            // calendar means every date reports "not a trading day", and a
            // backtest that silently does nothing is worth one loud line.
            log.warn("[trading-calendar] historical_spot_candles has no rows — every date will be treated as a "
                    + "non-trading day and backtests will replay nothing. Import the underlying (SPOT) CSVs.");
            return loaded;
        }

        log.info("[trading-calendar] loaded {} trading days from historical_spot_candles ({} .. {})",
                loaded.size(), loaded.first(), loaded.last());
        tradingDays = loaded;
        return loaded;
    }
}
