package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
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

        Map<String, List<MarketData>> strikeMarketData = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (strikeMarketData == null || strikeMarketData.isEmpty()) {
            return;
        }

        List<SmaTimeframe> timeframes = config != null ? config.getTimeframes() : null;
        if (timeframes == null || timeframes.isEmpty()) {
            return;
        }

        String instrumentToken = (config.getInstrumentDetails() != null
                && config.getInstrumentDetails().getInstrumentToken() != null)
                ? config.getInstrumentDetails().getInstrumentToken().toString()
                : null;

        for (SmaTimeframe tf : timeframes) {
            if (tf == null || tf.getTimePeriod() == null || tf.getSma() == null) continue;

            final Integer primarySma = tf.getSma();
            final String interval = tf.getTimePeriod() + "minute";
            final TradeRules sellRules = sellRulesFor(primarySma);
            final TradeRules buyRules  = buyRulesFor(primarySma);

            strikeMarketData.forEach((key, dataList) -> {
                if (!keyMatches(key, instrumentToken, interval)) return;
                if (dataList == null || dataList.isEmpty()) return;

                SmaTrendCalculator.compute(dataList, 0);

                MarketData lastCandle = dataList.get(dataList.size() - 1);
                double smaVal = CommonRules.smaValue(lastCandle, primarySma);
                double open   = lastCandle.getOpen()  != null ? lastCandle.getOpen().doubleValue()  : 0d;
                double close  = lastCandle.getClose() != null ? lastCandle.getClose().doubleValue() : 0d;
                boolean sellGate = smaVal > 0 && open > smaVal && close < smaVal;
                boolean buyGate  = false; // raw buy-cross intentionally disabled

                RuleContext ctx = new RuleContext(lastCandle, dataList.size() - 1,
                        dataList, primarySma, config);
                RuleEngine.Decision decision = RuleEngine.decide(ctx, sellRules, buyRules);

                String strikeLabel = parseStrikeLabel(key);
                log.debug("[tick] tf={} {} ts={} open={} close={} sma{}={} sellGate={} buyGate={} → {} ({})",
                        interval, strikeLabel, lastCandle.getTimestamp(),
                        open, close, primarySma, smaVal,
                        sellGate, buyGate, decision.action(), decision.reason());

                if (decision.action() != TradeAction.NONE) {
                    log.info("[signal] {} {} tf={} sma{}={} open={} close={} time={}",
                            decision.action(), strikeLabel, interval,
                            primarySma, smaVal, open, close, lastCandle.getTimestamp());
                    SharedData.tradeSignals.add(new TradeSignal(
                            key, decision.action(), tradeConfigId,
                            lastCandle.getTimestamp(), primarySma, interval,
                            lastCandle.getClose()));
                }
            });
        }
    }

    /**
     * Key shape: {@code <instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|<itm>|<otm>}.
     * Returns a compact "23700 CE" label for the tick log.
     */
    private String parseStrikeLabel(String key) {
        if (key == null) return "?";
        String[] parts = key.split("\\|");
        if (parts.length < 4) return key;
        return parts[3] + " " + parts[2];
    }

    private boolean keyMatches(String key, String instrumentToken, String interval) {
        if (key == null || interval == null) return false;
        if (instrumentToken != null) {
            return key.startsWith(instrumentToken + "|" + interval + "|");
        }
        return key.contains("|" + interval + "|");
    }

    // ------------------------------------------------------------------
    // Strategy-specific rules. Wrap lambdas with TradeRule.named(...) so the
    // [tick] log can name the failing rule instead of just printing an index.
    // ------------------------------------------------------------------

    private TradeRules sellRulesFor(Integer primarySmaPeriod) {
        if (primarySmaPeriod == null) return TradeRules.empty();
        switch (primarySmaPeriod) {
            case 20:  return sellRulesFor20();
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
            case 20:  return buyRulesFor20();
            case 50:  return buyRulesFor50();
            case 100: return buyRulesFor100();
            case 200: return buyRulesFor200();
            case 500: return buyRulesFor500();
            default:  return TradeRules.empty();
        }
    }

    private TradeRules sellRulesFor20() {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma50DownTrending",
                ctx -> ctx.candle.isSma50DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);
    }

    private TradeRules buyRulesFor20()  {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    private TradeRules sellRulesFor50() {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma50DownTrending",
                ctx -> ctx.candle.isSma50DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);
    }

    private TradeRules buyRulesFor50()  {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    private TradeRules sellRulesFor100() {
        return TradeRules.empty();
    }

    private TradeRules buyRulesFor100() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    private TradeRules sellRulesFor200() { return TradeRules.empty(); }

    private TradeRules buyRulesFor200() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    private TradeRules sellRulesFor500() { return TradeRules.empty(); }

    private TradeRules buyRulesFor500() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }
}
