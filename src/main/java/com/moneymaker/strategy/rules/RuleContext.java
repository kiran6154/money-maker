package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;

import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

/**
 * Bundle of inputs every {@link TradeRule} may need. Public final fields keep
 * lambdas terse: {@code ctx -> ctx.candle.isSma50DownTrending()}.
 */
public final class RuleContext {
    public final MarketData candle;
    public final int index;
    public final List<MarketData> allCandles;
    public final Integer primarySmaPeriod;
    public final TradeConfigCombinedDTO config;

    /**
     * The moment being evaluated — the backtest tick, or wall-clock in live.
     * May be null for callers that predate it. Rules that ask "is it time to do
     * X" must compare against this rather than reading {@code candle} alone: the
     * candle can belong to an earlier session than the one being replayed.
     */
    public final LocalDateTime asOf;

    /**
     * Time-of-day at which the market-close exit signal fires, derived by
     * {@code MarketHoursService.closeSignalTime()} from {@code app.market.*}.
     * May be null for callers that predate it (manual construction in tests);
     * {@code CommonRules.isMarketCloseTime} then falls back to the legacy
     * 15:15 constant, so behaviour degrades rather than changes.
     */
    public final LocalTime closeSignalTime;

    public RuleContext(MarketData candle, int index, List<MarketData> allCandles,
                       Integer primarySmaPeriod, TradeConfigCombinedDTO config) {
        this(candle, index, allCandles, primarySmaPeriod, config, null, null);
    }

    public RuleContext(MarketData candle, int index, List<MarketData> allCandles,
                       Integer primarySmaPeriod, TradeConfigCombinedDTO config,
                       LocalDateTime asOf) {
        this(candle, index, allCandles, primarySmaPeriod, config, asOf, null);
    }

    public RuleContext(MarketData candle, int index, List<MarketData> allCandles,
                       Integer primarySmaPeriod, TradeConfigCombinedDTO config,
                       LocalDateTime asOf, LocalTime closeSignalTime) {
        this.candle = candle;
        this.index = index;
        this.allCandles = allCandles;
        this.primarySmaPeriod = primarySmaPeriod;
        this.config = config;
        this.asOf = asOf;
        this.closeSignalTime = closeSignalTime;
    }
}
