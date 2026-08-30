package com.moneymaker.journal;

import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Everything a {@link FeatureContributor} is allowed to see about one observed
 * leg at one moment.
 *
 * <p>A value object, deliberately: contributors receive it, read it, and return
 * features. Nothing here is mutable state they can disturb, which is what keeps
 * observation from ever changing a trading decision.
 *
 * <p>{@code optionCandles} and {@code underlyingCandles} are the series as the
 * pipeline saw them at {@link #observedAt} — already narrowed to settled bars by
 * {@code MarketDataService}. A contributor must not widen them or fetch its own,
 * or it would see past the moment being described.
 *
 * @param kind              CANDIDATE / ENTRY / MONITOR / EXIT
 * @param observedAt        the tick this observation describes
 * @param order             the trade, for ENTRY / MONITOR / EXIT; null for a
 *                          candidate that was merely evaluated
 * @param optionCandles     the leg's own series, ascending, settled bars only
 * @param underlyingCandles the index series for the same window
 * @param optionType        CE or PE
 * @param entryIsSell       true when the position is (or would be) short premium
 */
public record ObservationContext(
        ObservationKind kind,
        LocalDateTime observedAt,
        Integer strategyId,
        Integer tradeConfigId,
        TradeOrder order,
        String instrumentName,
        String optionToken,
        String optionType,
        Integer strike,
        Integer intervalMinutes,
        List<MarketData> optionCandles,
        List<MarketData> underlyingCandles,
        boolean entryIsSell
) {

    /** Latest settled bar of the leg, or null when the series is empty. */
    public MarketData lastOptionCandle() {
        return last(optionCandles);
    }

    /** Latest settled bar of the index, or null when the series is empty. */
    public MarketData lastUnderlyingCandle() {
        return last(underlyingCandles);
    }

    private static MarketData last(List<MarketData> candles) {
        return (candles == null || candles.isEmpty()) ? null : candles.get(candles.size() - 1);
    }
}
