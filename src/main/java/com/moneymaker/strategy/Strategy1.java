package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.RuleEngine;
import com.moneymaker.strategy.rules.SmaTrendCalculator;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class Strategy1 implements Strategy {

    public static final int ID = 1;

    @Override
    public int getId() {
        return ID;
    }

    @Override
    public void execute(TradeConfigCombinedDTO config) {
        Integer tradeConfigId = (config != null && config.getTradeConfig() != null)
                ? config.getTradeConfig().getId()
                : null;
        System.out.println("Executing Strategy1 for tradeConfigId=" + tradeConfigId);

        Map<String, List<MarketData>> strikeMarketData = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (strikeMarketData == null || strikeMarketData.isEmpty()) {
            System.out.println("Strategy1: No strike market data available");
            return;
        }

        Integer primarySma = RuleEngine.resolvePrimarySmaPeriod(config);
        TradeRules sellRules = sellRulesFor(primarySma);
        TradeRules buyRules  = buyRulesFor(primarySma);

        strikeMarketData.forEach((key, dataList) -> {
            if (dataList == null || dataList.isEmpty()) {
                System.out.println("Strategy1: " + key + " — empty");
                return;
            }

            // Compute intra-day trend flags on the real-data list
            SmaTrendCalculator.compute(dataList, 0);

            MarketData lastCandle = dataList.get(dataList.size() - 1);
            RuleContext ctx = new RuleContext(lastCandle, dataList.size() - 1,
                    dataList, primarySma, config);
            TradeAction tradeStart = RuleEngine.decide(ctx, sellRules, buyRules);

            System.out.println("Strategy1: " + key
                    + " | SMA50 down=" + lastCandle.isSma50DownTrending()
                    + " up=" + lastCandle.isSma50UpTrending()
                    + " | SMA100 down=" + lastCandle.isSma100DownTrending()
                    + " up=" + lastCandle.isSma100UpTrending()
                    + " | SMA200 down=" + lastCandle.isSma200DownTrending()
                    + " up=" + lastCandle.isSma200UpTrending()
                    + " | SMA500 down=" + lastCandle.isSma500DownTrending()
                    + " up=" + lastCandle.isSma500UpTrending()
                    + " | last O=" + lastCandle.getOpen() + " C=" + lastCandle.getClose()
                    + " SMA" + primarySma + "=" + CommonRules.smaValue(lastCandle, primarySma)
                    + " | TradeStart=" + tradeStart);
        });
    }

    // ------------------------------------------------------------------
    // Strategy-specific rules
    // ------------------------------------------------------------------
    // The rule engine lives in com.moneymaker.strategy.rules — this class only
    // declares which rules apply to each primary SMA period.
    //
    // How to add a new rule
    // ---------------------
    //  1) If it's reusable across strategies, add it to CommonRules. Otherwise
    //     inline it as a lambda in the relevant builder below, or add a private
    //     boolean helper method that takes a RuleContext.
    //  2) Reference it inside one of the sellRulesForXX() / buyRulesForXX()
    //     builders — either as a "required" rule (must pass) or an "anyOf"
    //     rule (one of several alternative confirmations).
    //
    // SELL fires when:    sellGate AND every required rule passes AND
    //                     (anyOf is empty OR at least one anyOf rule passes).
    // BUY mirrors SELL.

    // ----- Per-primary-SMA rule sets ----------------------------------

    private TradeRules sellRulesFor(Integer primarySmaPeriod) {
        if (primarySmaPeriod == null) return TradeRules.empty();
        switch (primarySmaPeriod) {
            case 50:  return sellRulesFor50();
            case 100: return sellRulesFor100();
            case 200: return sellRulesFor200();
            case 500: return sellRulesFor500();
            default:  return TradeRules.empty();
        }
    }

    private TradeRules buyRulesFor(Integer primarySmaPeriod) {
        if (primarySmaPeriod == null) return TradeRules.empty();
        switch (primarySmaPeriod) {
            case 50:  return buyRulesFor50();
            case 100: return buyRulesFor100();
            case 200: return buyRulesFor200();
            case 500: return buyRulesFor500();
            default:  return TradeRules.empty();
        }
    }

    private TradeRules sellRulesFor50() {
        List<TradeRule> required = new ArrayList<>();
        //required.add(CommonRules::isEndOfDay);                              // sell only at end-of-day
        required.add(CommonRules::isDistanceToNextHigherSmaAboveTarget);    // SMA gap covers profit target
        required.add(ctx -> !ctx.candle.isSma100DownTrending());            // sma100 NOT sloping down

        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(ctx -> !ctx.candle.isSma50DownTrending());                // sma50 NOT sloping down

        return new TradeRules(required, anyOf);
    }

    private TradeRules buyRulesFor50()  {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();

        anyOf.add(CommonRules::isEndOfDay);
        return new TradeRules(required, anyOf);
    }

    private TradeRules sellRulesFor100() {
        return TradeRules.empty();
    }

    private TradeRules buyRulesFor100() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();

        anyOf.add(CommonRules::isEndOfDay);
        return new TradeRules(required, anyOf);
    }

    private TradeRules sellRulesFor200() { return TradeRules.empty(); }

    private TradeRules buyRulesFor200() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();

        anyOf.add(CommonRules::isEndOfDay);
        return new TradeRules(required, anyOf);
    }


    private TradeRules sellRulesFor500() { return TradeRules.empty(); }

    private TradeRules buyRulesFor500() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();

        anyOf.add(CommonRules::isEndOfDay);
        return new TradeRules(required, anyOf);
    }
}
