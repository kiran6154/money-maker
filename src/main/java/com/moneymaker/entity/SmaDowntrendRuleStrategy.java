package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

/**
 * Tags one {@link SmaDowntrendRule} with a strategy the end-of-day detector
 * should generate configs for. One row per strategy.
 *
 * <p>This is what lets a single detected downtrend produce a single
 * {@code trade_config} whose {@code strategy_ids} column names every strategy,
 * instead of forcing the rule itself to be duplicated once per strategy — which would
 * re-run the expensive SMA-grid scan for an identical answer and reintroduce the
 * config duplication changeset 031 removed.</p>
 *
 * <p>A tagged strategy also needs a {@link StrategyDefaults} row before it
 * generates anything: that carries the {@code transaction_type} / {@code max_loss}
 * / trade-count block the generated config is stamped with.</p>
 *
 * <p>{@code sma_downtrend_rule.strategy_id} is not replaced — it remains the
 * rule's primary strategy and the source the backfill read. See changeset 034.</p>
 */
@Entity
@Table(name = "sma_downtrend_rule_strategy")
@Getter
@Setter
public class SmaDowntrendRuleStrategy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @ManyToOne
    @JoinColumn(name = "rule_id", referencedColumnName = "id")
    private SmaDowntrendRule rule;

    /** Matches {@code Strategy#getId()} and {@link StrategyDefaults#getStrategyId()}. */
    @Column(name = "strategy_id", nullable = false)
    private Integer strategyId;

    /** Whether the detector should generate for this tag. Parks a strategy without losing the row. */
    @Column(name = "enabled", nullable = false)
    private Boolean enabled;
}
