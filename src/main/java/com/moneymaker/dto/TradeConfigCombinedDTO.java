package com.moneymaker.dto;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * One configuration as the pipeline sees it, <b>scoped to a single strategy</b>.
 *
 * <p>A {@code trade_config} naming several strategies in its
 * {@code strategy_ids} column (changesets 031/035) produces one instance of this
 * DTO per id — same {@link #tradeConfig}, different
 * {@link #strategyId}. That fan-out happens once, in
 * {@code TradeConfigScheduler.fetchTradeConfigsByDate}, which is why everything
 * downstream still handles exactly one strategy per DTO.</p>
 *
 * <p>{@code (tradeConfig.id, strategyId)} is the pipeline's <b>ledger
 * identity</b>: it is what {@code OrderService} counts trades, parallel
 * positions and realised loss against, and what it matches open positions on.
 * Two strategies sharing a config therefore each get their own caps and their
 * own position on the same leg — they do not compete for one budget.</p>
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TradeConfigCombinedDTO {
    private TradeConfig tradeConfig;
    private Instrument instrument;
    private InstrumentDetails instrumentDetails;
    List<SmaTimeframe> timeframes;

    /**
     * The strategy this DTO is scoped to. Read it through
     * {@link #getStrategyId()} rather than directly — a DTO built before the
     * fan-out existed leaves it null and falls back to the config's primary
     * strategy.
     */
    private Integer strategyId;

    /** Pre-fan-out shape: the config's primary strategy is used. */
    public TradeConfigCombinedDTO(TradeConfig tradeConfig, Instrument instrument,
                                  InstrumentDetails instrumentDetails, List<SmaTimeframe> timeframes) {
        this(tradeConfig, instrument, instrumentDetails, timeframes, null);
    }

    /**
     * The strategy that should run this DTO, falling back to
     * {@code trade_config.stratergy_id} when no tag was attached.
     *
     * <p>The fallback is what keeps an untagged config working: a config whose
     * {@code strategy_ids} column is blank (or a DTO assembled by hand in a test)
     * still dispatches to the single strategy the config names, exactly as before
     * changeset 031.</p>
     */
    public Integer getStrategyId() {
        if (strategyId != null) return strategyId;
        return tradeConfig != null ? tradeConfig.getStratergyId() : null;
    }
}
