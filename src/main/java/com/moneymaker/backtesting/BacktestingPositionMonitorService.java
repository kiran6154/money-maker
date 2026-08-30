package com.moneymaker.backtesting;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.position.service.PositionMonitorService;
import com.moneymaker.shared.data.SharedData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Backtest position-monitor: pulls the latest cached candle for the option's
 * {@code optionToken} via {@link SharedData#latestCachedCandle}.
 * The cache is populated each backtest tick by {@code AnalysisScheduler}, so
 * "latest candle" naturally tracks the current tick. The candle's
 * {@link MarketData#getTimestamp() timestamp} becomes the {@link Quote#asOf()},
 * giving the position ledger the right "as of" time even though the backtest
 * is running on wall-clock.
 */
@Slf4j
@Service
public class BacktestingPositionMonitorService implements PositionMonitorService {

    public static final String NAME = "BACKTESTING";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public Quote currentQuote(TradeOrder order) {
        if (order == null || order.getOptionToken() == null) return null;

        // Delegated so this monitor and OrderService's force-close read the cache
        // through one rule. Resolving it here by scanning for the option token and
        // taking the first hit made the interval whatever hashed first, so a target
        // or stop could be checked against a 10- or 15-minute bar whose close is up
        // to fifteen minutes of price that had not happened at the timestamp then
        // written to exit_time. See SharedData.latestCachedCandle.
        MarketData md = SharedData.latestCachedCandle(order.getOptionToken(), null);
        if (md == null) {
            log.debug("Backtest monitor: no cached candle for optionToken={} (orderId={})",
                    order.getOptionToken(), order.getId());
            return null;
        }
        // High/low ride along for the resting-order stop model: a floor is an
        // SL order at the broker, so a bar that touches it intra-bar fills it
        // even when the close bounces back above (S4 decision 2026-08-31).
        return new Quote(md.getClose(), md.getTimestamp(), md.getHigh(), md.getLow());
    }
}
