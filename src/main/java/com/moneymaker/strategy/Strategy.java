package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;

import java.time.LocalDateTime;
import java.util.Set;

/**
 * Contract for trading strategy implementations.
 * Each strategy is identified by an integer id that maps to
 * {@code TradeConfig#stratergyId}.
 */
public interface Strategy {

    /**
     * @return the id this strategy handles (matches
     * {@link com.moneymaker.entity.TradeConfig#getStratergyId()}).
     */
    int getId();

    /**
     * Execute the strategy for the given combined trade configuration.
     *
     * @param asOf the moment being evaluated — the backtest tick, or wall-clock
     *             in live. A strategy must not act on a bar that belongs to an
     *             earlier session than this: the candle series spans the whole
     *             SMA lookback, so the newest <i>settled</i> bar of a coarse
     *             timeframe is still the previous session's close until that
     *             timeframe's first bucket of the day completes.
     */
    void execute(TradeConfigCombinedDTO config, LocalDateTime asOf);

    /**
     * Candle widths (minutes) this strategy reads <i>in addition to</i> the
     * config's own {@code sma_timeframe} rows — a confirmation series it
     * consults but does not trade on. {@code AnalysisScheduler} fetches and
     * SMA-stamps every width named here for each of the config's legs, keyed
     * exactly like the traded intervals, so a rule can find the leg's coarser
     * series in {@code SharedData} by swapping the interval segment of its own
     * cache key. Empty by default: strategies 1-4 read only what they trade.
     */
    default Set<Integer> confirmationTimeframes() {
        return Set.of();
    }

    /**
     * True when a {@code STOP_LOSS} exit closes this strategy's book on that
     * config for the rest of the session — no further entries that day.
     * Enforced by {@code OrderService.handleSignal} alongside the other
     * per-(config, strategy) caps, so it holds identically live and in replay.
     * False by default: strategies 1-4 re-enter freely after a stop.
     */
    default boolean stopLossLocksBookForDay() {
        return false;
    }
}

