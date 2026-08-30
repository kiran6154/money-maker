package com.moneymaker.journal;

import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.shared.data.SharedData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * Assembles an {@link ObservationContext} from the caches the pipeline has
 * already populated.
 *
 * <h3>Why this exists as its own type</h3>
 * The {@code SharedData} strike key —
 * {@code token|interval|optionType|strike|optionToken|itmDepth|otmDepth} — is
 * already parsed by hand in {@code AbstractSmaCrossStrategy},
 * {@code BacktestingPositionMonitorService} and {@code OrderService.ParsedKey}.
 * Every chokepoint that journalled would have added another copy, and the format
 * has changed before. One lookup helper, used by all three, is the alternative.
 *
 * <p>It also keeps the chokepoints thin: a call site passes what it already has
 * (an order, or a leg identity) and gets back a context, so journalling never
 * grows into the trading code.
 *
 * <h3>Series are read, never fetched</h3>
 * The candle lists come from {@code SharedData}, which {@code AnalysisScheduler}
 * fills identically in live and backtest, and which
 * {@code MarketDataService.dropIncompleteBars} has already narrowed to settled
 * bars. This class must never call {@code MarketDataService} itself: fetching a
 * wider window here would let a feature see past the moment being described.
 *
 * <p>Returns {@code null} when the series are not cached — a missing observation
 * is preferable to one describing a leg the pipeline was not actually looking at.
 */
@Slf4j
@Component
public class ObservationContextFactory {

    /** Segment index of the option token inside a SharedData strike key. */
    private static final int KEY_OPTION_TOKEN = 4;

    /** Segment index of the interval ("5minute") inside a SharedData strike key. */
    private static final int KEY_INTERVAL = 1;

    /** A cached leg series together with the bar width it was cached at. */
    private record Series(List<MarketData> candles, Integer intervalMinutes) {
        static final Series EMPTY = new Series(List.of(), null);
    }

    /**
     * Context for an order that already exists (ENTRY / MONITOR / EXIT).
     *
     * @param intervalMinutes the timeframe the observation belongs to, when the
     *                        caller knows it (the signal's, at ENTRY). Null lets
     *                        the leg's finest cached series answer — see
     *                        {@link #forOpenPosition}.
     */
    public ObservationContext forOrder(ObservationKind kind,
                                       TradeOrder order,
                                       LocalDateTime observedAt,
                                       Integer intervalMinutes) {
        if (order == null || observedAt == null) {
            return null;
        }
        Series series = seriesForOptionToken(order.getOptionToken(), intervalMinutes);
        Integer resolvedInterval = intervalMinutes != null ? intervalMinutes : series.intervalMinutes();
        return new ObservationContext(
                kind,
                observedAt,
                order.getStrategyId(),
                order.getTradeConfigId(),
                order,
                order.getInstrumentName(),
                order.getOptionToken(),
                order.getOptionType(),
                order.getOptionStrike(),
                resolvedInterval,
                series.candles(),
                underlyingSeries(resolvedInterval),
                "SELL".equalsIgnoreCase(order.getEntryDirection()));
    }

    /**
     * Context for a position being monitored — the MONITOR / EVENT case.
     *
     * <h3>Why the finest cached interval</h3>
     * {@code TradeOrder} carries no timeframe: the signal's interval is known at
     * entry and then not persisted, so a monitor tick has no config-supplied
     * answer and must not invent one. The finest cached bar is the right choice
     * rather than an arbitrary one because it is exactly what the monitor priced
     * the tick off — {@code SharedData.latestCachedCandle} documents the same
     * reasoning: live hands the monitor a real LTP, so the closest backtest
     * analogue is the shortest bar available. Describing a tick with a coarser
     * series would report structure the monitor's own quote had already moved
     * past.
     *
     * <p>The resolved width is stamped on the row's {@code interval_minutes}, so
     * analysis can see which series a MONITOR row describes instead of guessing.
     */
    public ObservationContext forOpenPosition(TradeOrder order, LocalDateTime observedAt) {
        return forOrder(ObservationKind.MONITOR, order, observedAt, null);
    }

    /**
     * Context for a leg that was merely evaluated — the CANDIDATE case, which is
     * what makes counterfactual analysis possible.
     *
     * @param entryIsSell the direction this config would have taken, since no
     *                    order exists to read it from
     */
    public ObservationContext forCandidate(LocalDateTime observedAt,
                                           Integer strategyId,
                                           Integer tradeConfigId,
                                           String instrumentName,
                                           String optionToken,
                                           String optionType,
                                           Integer strike,
                                           Integer intervalMinutes,
                                           List<MarketData> optionCandles,
                                           boolean entryIsSell) {
        if (observedAt == null || optionCandles == null || optionCandles.isEmpty()) {
            return null;
        }
        return new ObservationContext(
                ObservationKind.CANDIDATE,
                observedAt,
                strategyId,
                tradeConfigId,
                null,
                instrumentName,
                optionToken,
                optionType,
                strike,
                intervalMinutes,
                optionCandles,
                underlyingSeries(intervalMinutes),
                entryIsSell);
    }

    /**
     * The cached series for one option leg, found by scanning strike keys for a
     * matching option-token segment.
     *
     * <p>A scan rather than a direct lookup because the key carries the config's
     * itm/otm depths, which the caller does not have. The map holds a few dozen
     * entries per tick, so this is cheap.
     *
     * <p><b>The interval has to be chosen, not taken first.</b> The same leg is
     * cached once per interval any config asked for, so taking the first
     * option-token hit is {@code ConcurrentHashMap} iteration order — the same
     * defect {@code SharedData.latestCachedCandle} was fixed for. When the caller
     * knows the timeframe the observation belongs to (the signal's, at ENTRY)
     * that series is used, so the row describes what the strategy actually read;
     * otherwise the finest cached series wins, which is what a monitor tick
     * prices off. Ties between two configs caching the same (token, interval)
     * need no tie-break: those series are fetched with identical arguments.
     */
    private Series seriesForOptionToken(String optionToken, Integer preferredInterval) {
        if (optionToken == null) {
            return Series.EMPTY;
        }
        Map<String, List<MarketData>> cache = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) {
            return Series.EMPTY;
        }
        Series finest = Series.EMPTY;
        int finestWidth = Integer.MAX_VALUE;
        for (Map.Entry<String, List<MarketData>> e : cache.entrySet()) {
            String[] parts = e.getKey().split("\\|");
            if (parts.length <= KEY_OPTION_TOKEN || !optionToken.equals(parts[KEY_OPTION_TOKEN])) {
                continue;
            }
            List<MarketData> candles = e.getValue();
            if (candles == null || candles.isEmpty()) {
                continue;
            }
            Integer width = intervalMinutes(parts[KEY_INTERVAL]);
            if (preferredInterval != null && preferredInterval.equals(width)) {
                return new Series(candles, width);
            }
            int rank = width == null ? Integer.MAX_VALUE : width;
            if (rank < finestWidth) {
                finestWidth = rank;
                finest = new Series(candles, width);
            }
        }
        return finest;
    }

    /**
     * Bar width in minutes for an interval segment such as {@code "5minute"}, or
     * null when it is not of that shape — a malformed key must not win the
     * finest-interval comparison, and must not be stamped on a row as a width.
     */
    private static Integer intervalMinutes(String interval) {
        if (interval == null) {
            return null;
        }
        String normalized = interval.trim().toLowerCase(java.util.Locale.ROOT);
        if (!normalized.endsWith("minute")) {
            return null;
        }
        try {
            return Integer.valueOf(normalized.substring(0, normalized.length() - "minute".length()));
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    /**
     * The underlying series for an interval. There is normally one underlying in
     * play, so the first entry matching the interval suffix is it.
     */
    private List<MarketData> underlyingSeries(Integer intervalMinutes) {
        Map<String, List<MarketData>> cache = SharedData.marketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) {
            return List.of();
        }
        String suffix = intervalMinutes == null ? null : "|" + intervalMinutes + "minute";
        for (Map.Entry<String, List<MarketData>> e : cache.entrySet()) {
            if (suffix == null || e.getKey().endsWith(suffix)) {
                return e.getValue() == null ? List.of() : e.getValue();
            }
        }
        return List.of();
    }
}
