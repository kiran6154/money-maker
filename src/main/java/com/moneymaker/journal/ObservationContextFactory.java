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

    /**
     * Context for an order that already exists (ENTRY / MONITOR / EXIT).
     */
    public ObservationContext forOrder(ObservationKind kind,
                                       TradeOrder order,
                                       LocalDateTime observedAt,
                                       Integer intervalMinutes) {
        if (order == null || observedAt == null) {
            return null;
        }
        List<MarketData> optionCandles = seriesForOptionToken(order.getOptionToken());
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
                intervalMinutes,
                optionCandles,
                underlyingSeries(intervalMinutes),
                "SELL".equalsIgnoreCase(order.getEntryDirection()));
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
     */
    private List<MarketData> seriesForOptionToken(String optionToken) {
        if (optionToken == null) {
            return List.of();
        }
        Map<String, List<MarketData>> cache = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) {
            return List.of();
        }
        for (Map.Entry<String, List<MarketData>> e : cache.entrySet()) {
            String[] parts = e.getKey().split("\\|");
            if (parts.length > KEY_OPTION_TOKEN && optionToken.equals(parts[KEY_OPTION_TOKEN])) {
                return e.getValue() == null ? List.of() : e.getValue();
            }
        }
        return List.of();
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
