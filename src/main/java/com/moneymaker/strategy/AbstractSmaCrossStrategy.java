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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/**
 * The SMA-cross scanning engine shared by every strategy in this package.
 *
 * <p>Everything that decides <i>which</i> legs get scanned and in what order —
 * cache-key matching, premium sort, the SMA-cross gate, the entry price band —
 * lives here. What a subclass supplies is its {@link #getId() id} and,
 * optionally, a different set of {@link TradeRules} per SMA period.</p>
 *
 * <p>A subclass that wants to <b>narrow</b> the baseline should wrap
 * {@code super.sellRulesFor(...)} / {@code super.buyRulesFor(...)} rather than
 * rebuild them, and must pass a fully-empty {@link TradeRules} straight through:
 * empty means "nobody wrote rules for this SMA period" and {@link RuleEngine}
 * deliberately fails it closed. Appending a required rule onto an empty pair
 * would silently turn "never trade this period" into "trade it whenever my one
 * extra rule passes" — see {@link TradeRules#empty()}.</p>
 */
public abstract class AbstractSmaCrossStrategy implements Strategy {

    /**
     * Bound to the concrete subclass rather than to this file, so a
     * {@code [signal]} / {@code [tick]} line names the strategy that actually
     * emitted it. With the usual {@code @Slf4j} static logger every strategy's
     * output would be attributed to this base class — precisely the distinction
     * you need when two strategies scan the same day.
     */
    protected final Logger log = LoggerFactory.getLogger(getClass());

    /**
     * Same resolver {@code AnalysisScheduler} used to build the cache keys, so
     * the prefix matched here is guaranteed to be the prefix that was written.
     * Deriving it from {@code instrumentDetails} instead would silently match
     * nothing whenever the symbol is not a broker token.
     */
    protected final OptionInstrumentResolver instrumentResolver;

    /**
     * Source of the close-signal time handed to {@code RuleContext}. Optional
     * ({@code required = false}) so a manually constructed strategy — unit
     * tests — leaves it null and {@code CommonRules.isMarketCloseTime} degrades
     * to its legacy 15:15 fallback instead of failing to construct.
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    protected com.moneymaker.market.service.MarketHoursService marketHours;

    protected AbstractSmaCrossStrategy(OptionInstrumentResolver instrumentResolver) {
        this.instrumentResolver = instrumentResolver;
    }

    @Override
    public void execute(TradeConfigCombinedDTO config, LocalDateTime asOf) {
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

        // Legs are scanned highest-premium first, so under the
        // numberOfTradesPerDay / numberOfParallelTrades caps the most expensive
        // leg wins the entry. This used to be approximated by sorting on strike
        // (ascending for CE, descending for PE, on the assumption that deeper
        // ITM is always dearer). Premium is now compared directly: the strike
        // proxy breaks down near expiry and across the itm/otm span a single
        // config scans, which is exactly where the price band matters.

        // The exact segments AnalysisScheduler pinned into the keys this config
        // wrote — see keyMatches. A null side means it fetched nothing at all
        // (the writer refuses an unresolved trading_side), so there is nothing
        // here for this config to scan.
        final String optionType = resolveOptionType(config);
        if (optionType == null) {
            log.warn("[strategy{}] tradeConfigId={} has no usable trading_side — nothing to scan",
                    getId(), tradeConfigId);
            return;
        }
        final String itmDepth = depthOf(config, true);
        final String otmDepth = depthOf(config, false);

        for (SmaTimeframe tf : timeframes) {
            if (tf == null || tf.getTimePeriod() == null || tf.getSma() == null) continue;

            final Integer primarySma = tf.getSma();
            final String interval = tf.getTimePeriod() + "minute";
            final TradeRules sellRules = sellRulesFor(primarySma);
            final TradeRules buyRules  = buyRulesFor(primarySma);

            List<Map.Entry<String, List<MarketData>>> sortedStrikes = strikeMarketData.entrySet().stream()
                    .filter(e -> keyMatches(e.getKey(), instrumentToken, interval,
                                            optionType, itmDepth, otmDepth))
                    .filter(e -> e.getValue() != null && !e.getValue().isEmpty())
                    .sorted(premiumComparator())
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
                log.debug("[strikes] tradeConfigId={} tf={} {} scan-order (premium desc): {}",
                        tradeConfigId, interval, optionType, sb);
            }

            for (Map.Entry<String, List<MarketData>> entry : sortedStrikes) {
                String key = entry.getKey();
                List<MarketData> dataList = entry.getValue();

                SmaTrendCalculator.compute(dataList, 0);

                MarketData lastCandle = dataList.get(dataList.size() - 1);

                // A settled bar from an earlier session is not a decision bar.
                //
                // dataList spans the whole SMA lookback and ends at the newest bar
                // that has *finished forming* by asOf. For a coarse timeframe that
                // is still the previous session's close until the day's first
                // bucket completes: on a 15-minute series the 09:15 bucket only
                // settles at 09:30, so the two backtest ticks before it see
                // yesterday's 15:15 bar as "latest". Acting on it emitted a signal
                // carrying yesterday's timestamp and yesterday's price — an exit
                // stamped before its own entry, or an entry that looked like an
                // overnight hold in an intraday system.
                //
                // Only the decision is suppressed; the bars behind it still feed
                // the SMA. "This timeframe has no settled bar yet today" is the
                // honest answer, and it is what live does too — a broker asked for
                // a 15-minute series over a multi-day window at 09:20 also returns
                // yesterday's last bar as the newest.
                if (asOf != null && lastCandle.getTimestamp() != null
                        && !lastCandle.getTimestamp().toLocalDate().equals(asOf.toLocalDate())) {
                    log.debug("[tick] tf={} {} SKIP — newest settled bar {} is from an earlier session (asOf={})",
                            interval, parseStrikeLabel(key), lastCandle.getTimestamp(), asOf);
                    continue;
                }

                double smaVal = CommonRules.smaValue(lastCandle, primarySma);
                double open   = lastCandle.getOpen()  != null ? lastCandle.getOpen().doubleValue()  : 0d;
                double close  = lastCandle.getClose() != null ? lastCandle.getClose().doubleValue() : 0d;
                boolean sellGate = smaVal > 0 && open > smaVal && close < smaVal;
                boolean buyGate  = false; // raw buy-cross intentionally disabled

                RuleContext ctx = new RuleContext(lastCandle, dataList.size() - 1,
                        dataList, primarySma, config, asOf,
                        marketHours != null ? marketHours.closeSignalTime() : null);
                RuleEngine.Decision decision = RuleEngine.decide(ctx, sellRules, buyRules);

                String strikeLabel = parseStrikeLabel(key);
                log.debug("[tick] tf={} {} ts={} open={} close={} sma{}={} sellGate={} buyGate={} → {} ({})",
                        interval, strikeLabel, lastCandle.getTimestamp(),
                        open, close, primarySma, smaVal,
                        sellGate, buyGate, decision.action(), decision.reason());

                if (decision.action() != TradeAction.NONE) {
                    if (outsidePriceBand(config, decision.action(), lastCandle.getClose())) {
                        log.debug("[signal] SUPPRESSED {} {} tf={} premium={} outside band [{}, {}] time={}",
                                decision.action(), strikeLabel, interval, lastCandle.getClose(),
                                priceBoundOf(config, true), priceBoundOf(config, false),
                                lastCandle.getTimestamp());
                        continue;
                    }
                    log.info("[signal] {} {} tf={} sma{}={} open={} close={} time={}",
                            decision.action(), strikeLabel, interval,
                            primarySma, smaVal, open, close, lastCandle.getTimestamp());
                    SharedData.tradeSignals.add(new TradeSignal(
                            key, decision.action(), tradeConfigId, getId(),
                            lastCandle.getTimestamp(), primarySma, interval,
                            lastCandle.getClose()));
                }
            }
        }
    }

    /**
     * True when this signal would OPEN a trade on a leg whose premium falls
     * outside the config's {@code minOptionPrice} / {@code maxOptionPrice} band.
     *
     * <p>Bounds are inclusive and independent — either may be null, meaning
     * unbounded on that side, so a config that sets neither behaves exactly as
     * before.</p>
     *
     * <p><b>Only entry signals are filtered.</b> A strategy here is one-sided:
     * an entry carries the config's own {@code transactionType} and the opposite
     * direction is exit-only — the same rule {@code OrderService} applies when it
     * decides whether a signal opens or closes. Filtering exits too would be
     * actively harmful on a SELL config, where a falling premium <i>is</i> the
     * profit: a {@code minOptionPrice} would then suppress precisely the winning
     * exits and strand the position until stop-loss or the end-of-day
     * force-close.</p>
     *
     * <p>Evaluated against the premium at signal time rather than at strike
     * selection, because a leg that is out of band in the morning can be in band
     * by noon.</p>
     */
    private boolean outsidePriceBand(TradeConfigCombinedDTO config, TradeAction action, BigDecimal premium) {
        if (config == null || config.getTradeConfig() == null || premium == null) return false;

        String txn = config.getTradeConfig().getTransactionType();
        boolean isEntry = txn == null || txn.isBlank()
                || txn.trim().equalsIgnoreCase(action.name());
        if (!isEntry) return false;

        BigDecimal min = config.getTradeConfig().getMinOptionPrice();
        BigDecimal max = config.getTradeConfig().getMaxOptionPrice();
        if (min != null && premium.compareTo(min) < 0) return true;
        return max != null && premium.compareTo(max) > 0;
    }

    /** Band edge for the suppression log; {@code null} renders as "-". */
    private String priceBoundOf(TradeConfigCombinedDTO config, boolean lower) {
        if (config == null || config.getTradeConfig() == null) return "-";
        BigDecimal v = lower
                ? config.getTradeConfig().getMinOptionPrice()
                : config.getTradeConfig().getMaxOptionPrice();
        return v == null ? "-" : v.toPlainString();
    }

    /**
     * The config's leg type, {@code "CE"} / {@code "PE"}, or null when
     * {@code trading_side} does not resolve.
     *
     * <p>Deliberately mirrors {@code AnalysisScheduler.resolveOptionType} — it is
     * what produced the {@code optionType} segment of the cache keys, so any
     * disagreement here would silently match nothing. Returning null rather than
     * defaulting to CE matters: the writer skips the fetch entirely for an
     * unresolved side, so a default would have this config scanning some other
     * config's legs.</p>
     */
    private String resolveOptionType(TradeConfigCombinedDTO config) {
        if (config == null || config.getTradeConfig() == null) return null;
        String side = config.getTradeConfig().getTradingSide();
        if (side == null) return null;
        String up = side.toUpperCase();
        if (up.contains("CE") || up.contains("C")) return "CE";
        if (up.contains("PE") || up.contains("P")) return "PE";
        return null;
    }

    /**
     * Scan order: highest current premium first, so the dearest leg gets the
     * entry when a cap allows only one.
     *
     * <p>Premium is the last candle's close — the same value the signal carries
     * and that becomes {@code entry_price}, so the ordering reflects what the
     * trade would actually be worth rather than inferring it from strike
     * distance.</p>
     *
     * <p>Ties break on the key string. Without an explicit tie-breaker a stable
     * sort falls back to {@code ConcurrentHashMap} iteration order, which is not
     * deterministic across runs — the original cause of "same config, different
     * strike each run". Entries with no usable close sort last rather than
     * throwing.</p>
     */
    private Comparator<Map.Entry<String, List<MarketData>>> premiumComparator() {
        return (a, b) -> {
            BigDecimal pa = lastClose(a.getValue());
            BigDecimal pb = lastClose(b.getValue());
            if (pa == null || pb == null) {
                if (pa != null) return -1;
                if (pb != null) return 1;
                return a.getKey().compareTo(b.getKey());
            }
            int cmp = pb.compareTo(pa);            // descending premium
            return cmp != 0 ? cmp : a.getKey().compareTo(b.getKey());
        };
    }

    private BigDecimal lastClose(List<MarketData> candles) {
        if (candles == null || candles.isEmpty()) return null;
        return candles.get(candles.size() - 1).getClose();
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

    /**
     * True when this cache entry is one <i>this</i> config contributed.
     *
     * <p>{@code SharedData.strikeMarketDataByInstrumentAndInterval} is global —
     * every config for the day writes its legs into the same map, keyed
     * {@code instrumentToken|interval|optionType|strike|optionToken|itmDepth|otmDepth}
     * by {@code AnalysisScheduler.toStrikeMarketDataKey}. The read therefore has
     * to match every segment the write pinned, not just the first two.</p>
     *
     * <p>Matching only {@code instrumentToken|interval} let a CE config scan the
     * PE config's legs and vice versa. Since a CE + PE config pair per day is the
     * normal shape, every signal fired once under each config and the ledger
     * recorded each trade <b>twice</b> — with half the rows carrying an option
     * type that contradicts their own config's {@code trading_side}. The
     * per-config {@code trading_side} reached this class only as the sort
     * direction, never as a filter. Depths leak the same way between sibling
     * configs that differ only in {@code itm_depth} / {@code otm_depth}.</p>
     */
    private boolean keyMatches(String key, String instrumentToken, String interval,
                               String optionType, String itmDepth, String otmDepth) {
        if (key == null || interval == null) return false;
        String[] p = key.split("\\|");
        if (p.length < 7) return false;
        if (instrumentToken != null && !instrumentToken.equals(p[0])) return false;
        return interval.equals(p[1])
                && optionType.equals(p[2])
                && itmDepth.equals(p[5])
                && otmDepth.equals(p[6]);
    }

    /**
     * Depth segment as the writer rendered it — plain string concatenation of the
     * {@code Integer}, so a null depth becomes the literal {@code "null"} on both
     * sides and still matches.
     */
    private String depthOf(TradeConfigCombinedDTO config, boolean itm) {
        if (config == null || config.getTradeConfig() == null) return "null";
        return String.valueOf(itm
                ? config.getTradeConfig().getItmDepth()
                : config.getTradeConfig().getOtmDepth());
    }

    // ------------------------------------------------------------------
    // Baseline rules. Wrap lambdas with TradeRule.named(...) so the
    // [tick] log can name the failing rule instead of just printing an index.
    // ------------------------------------------------------------------

    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        if (primarySmaPeriod == null) return TradeRules.empty();
        switch (primarySmaPeriod) {
            //case 20:  return sellRulesFor20();
            case 50:  return sellRulesFor50();
            case 100: return sellRulesFor100();
            case 200: return sellRulesFor200();
            case 500: return sellRulesFor500();
            default:  return TradeRules.empty();
        }
    }

    protected TradeRules buyRulesFor(Integer primarySmaPeriod) {
        if (primarySmaPeriod == null) return TradeRules.empty();
        switch (primarySmaPeriod) {
            //case 20:  return buyRulesFor20();
            case 50:  return buyRulesFor50();
            case 100: return buyRulesFor100();
            case 200: return buyRulesFor200();
            case 500: return buyRulesFor500();
            default:  return TradeRules.empty();
        }
    }

    protected TradeRules sellRulesFor20() {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma20DownTrending",
                ctx -> ctx.candle.isSma20DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);
    }

    protected TradeRules buyRulesFor20()  {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    protected TradeRules sellRulesFor50() {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma50DownTrending",
                ctx -> ctx.candle.isSma50DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);
    }

    protected TradeRules buyRulesFor50()  {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    protected TradeRules sellRulesFor100() {

        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma100DownTrending",
                ctx -> ctx.candle.isSma100DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);

    }

    protected TradeRules buyRulesFor100() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    protected TradeRules sellRulesFor200() {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma200DownTrending",
                ctx -> ctx.candle.isSma200DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);
    }

    protected TradeRules buyRulesFor200() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }

    protected TradeRules sellRulesFor500() {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma500DownTrending",
                ctx -> ctx.candle.isSma500DownTrending()));
        List<TradeRule> anyOf = new ArrayList<>();
        return new TradeRules(required, anyOf);
    }

    protected TradeRules buyRulesFor500() {
        List<TradeRule> required = new ArrayList<>();
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(required, anyOf);
    }
}
