package com.moneymaker.strategy.rules;

@FunctionalInterface
public interface TradeRule {
    boolean test(RuleContext ctx);
}
