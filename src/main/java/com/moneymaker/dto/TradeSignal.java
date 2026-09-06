package com.moneymaker.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * A trade intent emitted by a strategy and consumed by the order service.
 *
 * <p>{@link #strikeKey} carries everything the order service needs to act
 * on, encoded as
 * {@code <instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|<itmDepth>|<otmDepth>}.
 * (See {@code AnalysisScheduler.toStrikeMarketDataKey}.)
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TradeSignal {
    private String strikeKey;
    private TradeAction action;
    private Integer tradeConfigId;

    /**
     * The strategy that emitted this signal. Together with
     * {@link #tradeConfigId} it is the ledger identity {@code OrderService}
     * applies every cap and dedupe rule against.
     *
     * <p>Carried on the signal rather than re-derived from the config, because
     * since changeset 031 one {@code trade_config} can be tagged with several
     * strategies and the config alone no longer says which one fired. Stamped by
     * {@code AbstractSmaCrossStrategy} from its own {@code getId()}.</p>
     */
    private Integer strategyId;

    private LocalDateTime signalTime;
    private Integer primarySma;
    private String interval;
    /** Close price of the candle that triggered the signal — used for entry/exit price. */
    private BigDecimal price;

    /**
     * ATR of the signal bar's series, set only by strategies whose exit needs it
     * (Strategy 8's chandelier trail — see {@code trail_atr_distance_at_entry}).
     * Null for every other signal.
     */
    private BigDecimal atr;

    /** The pre-048 shape: every existing caller, no ATR attached. */
    public TradeSignal(String strikeKey, TradeAction action, Integer tradeConfigId, Integer strategyId,
                       LocalDateTime signalTime, Integer primarySma, String interval, BigDecimal price) {
        this(strikeKey, action, tradeConfigId, strategyId, signalTime, primarySma, interval, price, null);
    }
}
