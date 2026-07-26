package com.moneymaker.backtesting;

import com.moneymaker.entity.ExpiryDates;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaDowntrendRule;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.indicator.IndicatorConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.repository.ExpiryDatesRepository;
import com.moneymaker.repository.InstrumentDetailsRepository;
import com.moneymaker.repository.SmaDowntrendRuleRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.strategy.rules.SmaTrendCalculator;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

/**
 * End-of-day downtrend detector.
 *
 * <p>At the close of each backtest trading day, for every enabled
 * {@link SmaDowntrendRule} we walk the fixed grid
 * {@link #SMA_PERIODS} × {@link #TIMEFRAMES_MINUTES} against the ATM
 * strike on both CE and PE. Per (side, timeframe) the strike's series is
 * fetched once, all five SMAs computed on it, and
 * {@link SmaTrendCalculator} runs with {@code rule.maxDeviation} starting
 * at {@code rule.startTime}. Every SMA whose last-candle down-trend flag
 * is still on is recorded as a passing combo for that side.</p>
 *
 * <p>For each side with at least one passing combo we insert exactly one
 * {@link TradeConfig} (next trading day, {@code source='AUTO_DOWNTREND'},
 * fields from the {@link #strategyDefaults(int)} block + ATR-derived
 * target/SL) plus one {@link SmaTimeframe} child per passing combo.</p>
 *
 * <p><b>Idempotency:</b> if any {@code trade_config} row with
 * {@code source='AUTO_DOWNTREND'} already exists for the next trading day,
 * the whole write is skipped — first run wins. Delete those rows by hand
 * to force a re-write.</p>
 *
 * <p>Backtest-only today. Service is a Spring bean and the public entry
 * {@link #runForDay(LocalDate)} takes nothing backtest-specific, so a
 * future 15:25 cron can call it unchanged for live mode.</p>
 *
 * <p>See {@code docs/EOD_DOWNTREND.md}.</p>
 */
@Slf4j
@Service
public class EodDowntrendDetectionService {

    private static final String SOURCE_AUTO = "AUTO_DOWNTREND";
    private static final LocalTime MARKET_CLOSE = LocalTime.of(15, 20);
    private static final LocalTime MARKET_OPEN  = LocalTime.of(9, 15);

    /** Fixed SMA grid the detector evaluates. Add a period here AND extend
     *  {@code SmaTrendCalculator} / {@code MarketData} to track its flag. */
    static final int[] SMA_PERIODS = {20, 50, 100, 200, 500};

    /** Fixed candle timeframes the detector evaluates (minutes). */
    static final int[] TIMEFRAMES_MINUTES = {5, 15};

    private final SmaDowntrendRuleRepository ruleRepository;
    private final TradeConfigRepository tradeConfigRepository;
    private final SmaTimeframeRepository smaTimeframeRepository;
    private final InstrumentDetailsRepository instrumentDetailsRepository;
    private final ExpiryDatesRepository expiryDatesRepository;
    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;

    public EodDowntrendDetectionService(SmaDowntrendRuleRepository ruleRepository,
                                        TradeConfigRepository tradeConfigRepository,
                                        SmaTimeframeRepository smaTimeframeRepository,
                                        InstrumentDetailsRepository instrumentDetailsRepository,
                                        ExpiryDatesRepository expiryDatesRepository,
                                        MarketDataService marketDataService,
                                        IndicatorService indicatorService) {
        this.ruleRepository = ruleRepository;
        this.tradeConfigRepository = tradeConfigRepository;
        this.smaTimeframeRepository = smaTimeframeRepository;
        this.instrumentDetailsRepository = instrumentDetailsRepository;
        this.expiryDatesRepository = expiryDatesRepository;
        this.marketDataService = marketDataService;
        this.indicatorService = indicatorService;
    }

    /**
     * Runs every enabled rule against {@code tradingDay}'s close, emitting
     * one next-day {@code trade_config} per side per rule when at least one
     * (sma, timeframe) combo passes.
     */
    public void runForDay(LocalDate tradingDay) {
        if (tradingDay == null) return;

        List<SmaDowntrendRule> rules = ruleRepository.findByEnabledTrue();
        if (rules.isEmpty()) {
            log.debug("[EOD-downtrend] {} — no enabled rules, skipping", tradingDay);
            return;
        }

        LocalDate nextDay = nextTradingDay(tradingDay);

        if (!tradeConfigRepository.findByTradingDateAndSource(nextDay, SOURCE_AUTO).isEmpty()) {
            log.info("[EOD-downtrend] {} — AUTO_DOWNTREND configs already exist for {}, skipping",
                    tradingDay, nextDay);
            return;
        }

        int inserted = 0;
        for (SmaDowntrendRule rule : rules) {
            try {
                inserted += processRule(rule, tradingDay, nextDay);
            } catch (Exception ex) {
                log.error("[EOD-downtrend] {} — rule id={} failed", tradingDay, rule.getId(), ex);
            }
        }
        log.info("[EOD-downtrend] {} — inserted {} AUTO_DOWNTREND trade_config(s) for {}",
                tradingDay, inserted, nextDay);
    }

    // ------------------------------------------------------------------
    // Per-rule pipeline
    // ------------------------------------------------------------------

    private int processRule(SmaDowntrendRule rule, LocalDate tradingDay, LocalDate nextDay) {
        Instrument instrument = rule.getInstrument();
        if (instrument == null || instrument.getInsName() == null) {
            log.warn("[EOD-downtrend] rule id={} has no instrument, skipping", rule.getId());
            return 0;
        }

        StrategyDefaults defaults = strategyDefaults(rule.getStrategyId());
        if (defaults == null) {
            log.warn("[EOD-downtrend] rule id={} — no defaults for strategy {}, skipping",
                    rule.getId(), rule.getStrategyId());
            return 0;
        }

        LocalDate expiry = resolveExpiry(instrument, tradingDay);
        if (expiry == null) {
            log.warn("[EOD-downtrend] rule id={} — no expiry resolved for {} on {}",
                    rule.getId(), instrument.getInsName(), tradingDay);
            return 0;
        }

        Integer atmStrike = computeAtmStrike(instrument, tradingDay);
        if (atmStrike == null) {
            log.warn("[EOD-downtrend] rule id={} — cannot determine ATM strike for {} on {}",
                    rule.getId(), instrument.getInsName(), tradingDay);
            return 0;
        }

        BigDecimal atr = computeAtr(instrument, tradingDay, rule.getAtrPeriods());
        if (atr == null || atr.signum() <= 0) {
            log.warn("[EOD-downtrend] rule id={} — ATR unavailable for {} on {}, skipping",
                    rule.getId(), instrument.getInsName(), tradingDay);
            return 0;
        }

        int written = 0;
        for (String side : new String[]{"CE", "PE"}) {
            InstrumentDetails option = resolveOptionInstrument(instrument, expiry, atmStrike, side);
            if (option == null || option.getInstrumentToken() == null) {
                log.warn("[EOD-downtrend] rule id={} {} — no option instrument for ATM strike={} expiry={}",
                        rule.getId(), side, atmStrike, expiry);
                continue;
            }

            List<int[]> passing = scanSide(option.getInstrumentToken().toString(), tradingDay, rule);
            if (passing.isEmpty()) {
                log.debug("[EOD-downtrend] rule id={} {} ATM={} — nothing trending down",
                        rule.getId(), side, atmStrike);
                continue;
            }

            insertAutoTradeConfig(rule, defaults, nextDay, side, atr, passing);
            written++;
        }
        return written;
    }

    /**
     * Returns the list of {@code [sma, timeframe-minutes]} pairs whose last-candle
     * down-trend flag is on for the given strike on {@code tradingDay}.
     * <p>The strike series is fetched <i>once per timeframe</i> and all SMAs are
     * computed on it before {@link SmaTrendCalculator} runs.</p>
     */
    private List<int[]> scanSide(String optionToken, LocalDate tradingDay, SmaDowntrendRule rule) {
        List<int[]> passing = new ArrayList<>();

        LocalDateTime from = LocalDateTime.of(tradingDay, MARKET_OPEN);
        LocalDateTime to   = LocalDateTime.of(tradingDay, MARKET_CLOSE);

        for (int tfMinutes : TIMEFRAMES_MINUTES) {
            String interval = tfMinutes + "minute";

            List<MarketData> series = marketDataService.fetchHistoricalData(optionToken, from, to, interval);
            if (series == null || series.isEmpty()) {
                continue;
            }

            // Populate sma_value{20,50,100,200,500} on every candle in the series.
            for (int period : SMA_PERIODS) {
                try {
                    indicatorService.calculate("SMA", series, IndicatorConfig.of(period, "SMA"));
                } catch (Exception ex) {
                    log.debug("[EOD-downtrend] SMA({}) skipped on token={} tf={}: {}",
                            period, optionToken, interval, ex.getMessage());
                }
            }

            // Trim to candles at/after start_time — deviation counting starts there.
            List<MarketData> windowed = new ArrayList<>();
            for (MarketData c : series) {
                if (c.getTimestamp() == null) continue;
                if (!c.getTimestamp().toLocalTime().isBefore(rule.getStartTime())) {
                    windowed.add(c);
                }
            }
            if (windowed.isEmpty()) continue;

            SmaTrendCalculator.compute(windowed, rule.getMaxDeviation());
            MarketData last = windowed.get(windowed.size() - 1);

            for (int period : SMA_PERIODS) {
                if (smaDownFlag(last, period)) {
                    passing.add(new int[]{period, tfMinutes});
                }
            }
        }
        return passing;
    }

    private boolean smaDownFlag(MarketData c, int period) {
        if (c == null) return false;
        switch (period) {
            case 20:  return c.isSma20DownTrending();
            case 50:  return c.isSma50DownTrending();
            case 100: return c.isSma100DownTrending();
            case 200: return c.isSma200DownTrending();
            case 500: return c.isSma500DownTrending();
            default:  return false;
        }
    }

    // ------------------------------------------------------------------
    // Strike + expiry helpers (ATM only)
    // ------------------------------------------------------------------

    private LocalDate resolveExpiry(Instrument instrument, LocalDate tradingDay) {
        return expiryDatesRepository
                .findFirstByInstrumentAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(instrument, tradingDay)
                .map(ExpiryDates::getExpiryDate)
                .orElse(null);
    }

    /**
     * Rounds the underlying's last 5-minute close on {@code tradingDay} to the
     * nearest {@code instrument.strikePoints}. ATM only — no depth.
     */
    private Integer computeAtmStrike(Instrument instrument, LocalDate tradingDay) {
        if (instrument.getStrikePoints() == null || instrument.getStrikePoints().signum() <= 0) return null;
        if (instrument.getInsId() == null) return null;

        LocalDateTime from = LocalDateTime.of(tradingDay, MARKET_OPEN);
        LocalDateTime to   = LocalDateTime.of(tradingDay, MARKET_CLOSE);

        List<MarketData> underlying = marketDataService.fetchHistoricalData(
                instrument.getInsId(), from, to, "5minute");
        if (underlying == null || underlying.isEmpty()) return null;

        BigDecimal close = underlying.get(underlying.size() - 1).getClose();
        if (close == null) return null;

        BigDecimal step = instrument.getStrikePoints();
        BigDecimal multiplier = close.divide(step, 0, RoundingMode.HALF_UP);
        return multiplier.multiply(step).intValueExact();
    }

    private InstrumentDetails resolveOptionInstrument(Instrument instrument, LocalDate expiry,
                                                      Integer strike, String optionType) {
        List<InstrumentDetails> matches = instrumentDetailsRepository.findByCriteria(
                instrument.getInsName(), expiry.toString(), new BigDecimal(strike), optionType);
        if (matches.isEmpty()) return null;
        return matches.get(0);
    }

    // ------------------------------------------------------------------
    // ATR — daily true range over the last N completed trading days
    // ------------------------------------------------------------------

    private BigDecimal computeAtr(Instrument instrument, LocalDate tradingDay, Integer periods) {
        if (instrument.getInsId() == null) return null;
        int n = periods == null || periods <= 0 ? 14 : periods;

        LocalDateTime from = LocalDateTime.of(tradingDay.minusDays(Math.max(n * 2L + 10, 30)), LocalTime.MIDNIGHT);
        LocalDateTime to   = LocalDateTime.of(tradingDay, LocalTime.of(23, 59));

        List<MarketData> daily = marketDataService.fetchHistoricalData(
                instrument.getInsId(), from, to, "day");
        if (daily == null || daily.size() < 2) return null;

        int startIdx = Math.max(1, daily.size() - n);
        BigDecimal sum = BigDecimal.ZERO;
        int count = 0;
        for (int i = startIdx; i < daily.size(); i++) {
            BigDecimal tr = trueRange(daily.get(i), daily.get(i - 1));
            if (tr == null) continue;
            sum = sum.add(tr);
            count++;
        }
        if (count == 0) return null;
        return sum.divide(BigDecimal.valueOf(count), 4, RoundingMode.HALF_UP);
    }

    private BigDecimal trueRange(MarketData curr, MarketData prev) {
        if (curr == null || prev == null) return null;
        if (curr.getHigh() == null || curr.getLow() == null || prev.getClose() == null) return null;
        BigDecimal hl  = curr.getHigh().subtract(curr.getLow()).abs();
        BigDecimal hpc = curr.getHigh().subtract(prev.getClose()).abs();
        BigDecimal lpc = curr.getLow().subtract(prev.getClose()).abs();
        return hl.max(hpc).max(lpc);
    }

    // ------------------------------------------------------------------
    // Per-strategy defaults for trade_config conventions
    // ------------------------------------------------------------------

    /**
     * Per-strategy fixed-field block applied to the auto-generated
     * {@code trade_config}. Add a new branch when a new strategy starts
     * producing auto-downtrend configs.
     */
    private record StrategyDefaults(String transactionType,
                                    Integer lotQuantity,
                                    BigDecimal maxLoss,
                                    Integer noOfTrades,
                                    Integer noOfParallelTrades) {}

    private StrategyDefaults strategyDefaults(Integer strategyId) {
        if (strategyId == null) return null;
        switch (strategyId) {
            case 1:
                // Strategy 1 (the sell-the-rip strategy).
                return new StrategyDefaults(
                        "SELL",
                        1,
                        BigDecimal.valueOf(200),
                        1,
                        1);
            default:
                return null;
        }
    }

    // ------------------------------------------------------------------
    // Insert the auto-generated trade_config + sma_timeframe rows
    // ------------------------------------------------------------------

    private void insertAutoTradeConfig(SmaDowntrendRule rule,
                                       StrategyDefaults defaults,
                                       LocalDate nextDay,
                                       String side,
                                       BigDecimal atr,
                                       List<int[]> passing) {
        TradeConfig tc = new TradeConfig();
        tc.setTradingDate(nextDay);
        tc.setTradingSide(side);
        tc.setInstrument(rule.getInstrument());
        tc.setStratergyId(rule.getStrategyId());
        tc.setSource(SOURCE_AUTO);

        tc.setTarget(atr.multiply(rule.getTargetMultiplier()).setScale(2, RoundingMode.HALF_UP));
        tc.setStopLoss(atr.multiply(rule.getSlMultiplier()).setScale(2, RoundingMode.HALF_UP));

        tc.setTransactionType(defaults.transactionType());
        tc.setLotQuantity(defaults.lotQuantity());
        tc.setMaxLoss(defaults.maxLoss());
        tc.setNumberOfTradesPerDay(defaults.noOfTrades());
        tc.setNumberOfParallelTrades(defaults.noOfParallelTrades());

        // ATM always — leave all three depth columns at 0.
        tc.setItmDepth(0);
        tc.setOtmDepth(0);
        tc.setAtmDepth(0);

        TradeConfig saved = tradeConfigRepository.save(tc);

        for (int[] combo : passing) {
            SmaTimeframe tf = new SmaTimeframe();
            tf.setTradeConfig(saved);
            tf.setSma(combo[0]);
            tf.setTimePeriod(combo[1]);
            smaTimeframeRepository.save(tf);
        }

        log.info("[EOD-downtrend] inserted AUTO_DOWNTREND trade_config id={} for {} side={} target={} sl={} combos={}",
                saved.getId(), nextDay, side, tc.getTarget(), tc.getStopLoss(), summarise(passing));
    }

    private String summarise(List<int[]> passing) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < passing.size(); i++) {
            if (i > 0) sb.append(", ");
            sb.append(passing.get(i)[1]).append("min/SMA").append(passing.get(i)[0]);
        }
        return sb.append("]").toString();
    }

    /** Skips Sat/Sun. Holidays not modelled — picked up at the next backtest invocation. */
    private LocalDate nextTradingDay(LocalDate day) {
        LocalDate next = day.plusDays(1);
        while (next.getDayOfWeek() == DayOfWeek.SATURDAY || next.getDayOfWeek() == DayOfWeek.SUNDAY) {
            next = next.plusDays(1);
        }
        return next;
    }
}
