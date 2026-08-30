package com.moneymaker.repository;

import com.moneymaker.entity.SmaDowntrendRuleStrategy;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface SmaDowntrendRuleStrategyRepository extends JpaRepository<SmaDowntrendRuleStrategy, Integer> {

    /**
     * The strategies this rule should generate configs for, ascending so a
     * re-run of the same backtest day writes them in the same order.
     */
    List<SmaDowntrendRuleStrategy> findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(Integer ruleId);
}
