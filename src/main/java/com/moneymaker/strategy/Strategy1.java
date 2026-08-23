package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
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
import java.util.Comparator;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class Strategy1 implements Strategy {

    public static final int ID = 1;

    /**
     * Same resolver {@code AnalysisScheduler} used to build the cache keys, so
     * the prefix matched here is guaranteed to be the prefix that was written.
     * Deriving it from {@code instrumentDetails} instead would silently match
     * nothing whenever the symbol is not a broker token.
     */
    private final OptionInstrumentResolver instrumentResolver;

    public Strategy1(OptionInstrumentResolver instrumentResolver) {
        this.instrumentResolver = instrumentResolver;
    }

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

        // Must match what AnalysisScheduler put at position 0 of the cache key —
        // a broker instrument token normally, a historical natural-key symbol
        // when replaying imported candles.
        String instrumentToken = instrumentResolver.underlyingSymbol(config);

        // CE → ascending strike (lowest = deepest ITM = highest premium).
        // PE → descending strike (highest = deepest ITM = highest premium).
        // Scanning most-ITM first means the most-expensive leg's signal is
        // queued first; under TradeConfig.numberOfTradesPerDay / parallel-trade
        // caps it wins the entry deterministically — re-running the same
        // backtest now always picks the same strike.
        final boolean isCe = isCallSide(config);

        for (SmaTimeframe tf : timeframes) {
            if (tf == null || tf.getTimePeriod() == null || tf.getSma() == null) continue;

            final Integer primarySma = tf.getSma();
            final String interval = tf.getTimePeriod() + "minute";
            final TradeRules sellRules = sellRulesFor(primarySma);
            final TradeRules buyRules  = buyRulesFor(primarySma);

            List<Map.Entry<String, List<MarketData>>> sortedStrikes = strikeMarketData.entrySet().stream()
                    .filter(e -> keyMatches(e.getKey(), instrumentToken, interval))
                    .filter(e -> e.getValue() != null && !e.getValue().isEmpty())
                    .sorted(strikeComparator(isCe))
                    .toList();

            // Diagnostic: show the SCAN ORDER explicitly with each strike's last
            // candle close (≈ current premium). For CE this should be descending
            // premium; for PE ascending strike but also descending premium. If
            // this list looks reversed, the sort is wrong; if it looks right but
            // the trade went to a low-premium strike anyway, the higher-premium
            // strikes didn't fire the gate at this tick.
            if (log.isDebugEnabled()) {
                StringBuilder sb = new StringBuilder();
                for (Map.Entry<String, List<MarketData>> e : sortedStrikes) {
                    List<MarketData> dl = e.getValue();
                    MarketData last = dl.get(dl.size() - 1);
                    String strike = parseStrikeLabel(e.getKey());
                    String close = last.getClose() != null ? last.getClose().toPlainString() : "?";
                    if (sb.length() > 0) sb.append(", ");
                    sb.append(strike).append("(").append(close).append(")");
                }
                log.debug("[strikes] tradeConfigId={} tf={} {} scan-order: {}",
                        tradeConfigId, interval, isCe ? "CE" : "PE", sb);
            }

            for (Map.Entry<String, List<MarketData>> entry : sortedStrikes) {
                String key = entry.getKey();
                List<MarketData> dataList = entry.getValue();

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
            }
        }
    }

    /** True iff the trade config's side resolves to a CE (call) leg. */
    private boolean isCallSide(TradeConfigCombinedDTO config) {
        if (config == null || config.getTradeConfig() == null) return true;
        String side = config.getTradeConfig().getTradingSide();
        if (side == null) return true;
        String up = side.toUpperCase();
        if (up.contains("PE") || up.equals("P")) return false;
        return true;
    }

    /**
     * Comparator over strike-keyed entries. Most-ITM-first: ascending strike
     * for CE, descending for PE. Falls back to key-string compare when strike
     * can't be parsed (defensive — keys always carry an integer strike today).
     */
    private Comparator<Map.Entry<String, List<MarketData>>> strikeComparator(boolean isCe) {
        return (a, b) -> {
            Integer sa = parseStrikeOrNull(a.getKey());
            Integer sb = parseStrikeOrNull(b.getKey());
            if (sa == null || sb == null) return a.getKey().compareTo(b.getKey());
            int strikeCmp = isCe ? Integer.compare(sa, sb) : Integer.compare(sb, sa);
            if (strikeCmp != 0) return strikeCmp;
            // Tie-breaker: lexicographic key. Two cache entries can share the
            // same strike when sibling configs use different itmDepth/otmDepth
            // values (the depths are part of the cache key). Without an
            // explicit tie-breaker the stable sort falls back to ConcurrentHashMap
            // iteration order — which is non-deterministic across runs and is
            // the root cause of "same config, different strike each run".
            return a.getKey().compareTo(b.getKey());
        };
    }

    private Integer parseStrikeOrNull(String key) {
        if (key == null) return null;
        String[] parts = key.split("\\|");
        if (parts.length < 4) return null;
        try { return Integer.parseInt(parts[3]); }
        catch (NumberFormatException ex) { return null; }
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
