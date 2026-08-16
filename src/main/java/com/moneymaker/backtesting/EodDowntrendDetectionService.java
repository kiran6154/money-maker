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

    /** Tradable minutes in one NSE session (09:15–15:30). Used only to size the
     *  SMA lookback window — see {@link #lookbackCalendarDays(int)}. */
    private static final int SESSION_MINUTES = 375;

    /** Fixed SMA grid the detector evaluates. Add a period here AND extend
     *  {@code SmaTrendCalculator} / {@code MarketData} to track its flag. */
    static final int[] SMA_PERIODS = {20, 50, 100, 200, 500};

    /** Fixed candle timeframes the detector evaluates (minutes). */
    static final int[] TIMEFRAMES_MINUTES = {5, 15};

    /** Safety rails on the ATR-derived strike band — see {@link #strikeDepthFor}. */
    private static final int MIN_STRIKE_DEPTH = 2;
    private static final int MAX_STRIKE_DEPTH = 6;

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

        // Strike band width, from how far the underlying can plausibly travel in a
        // session. This is not cosmetic: AnalysisScheduler only fetches candles for
        // the strikes it derives from the live ATM, so a band narrower than the day's
        // movement orphans an open position the moment spot crosses a strike boundary
        // — its cached series stops refreshing and PositionService then evaluates
        // target/SL against a frozen quote.
        int strikeDepth = strikeDepthFor(
                computeAtr(instrument.getInsId(), tradingDay, rule.getAtrPeriods()),
                instrument.getStrikePoints());

        int written = 0;
        for (String side : new String[]{"CE", "PE"}) {
            InstrumentDetails option = resolveOptionInstrument(instrument, expiry, atmStrike, side);
            if (option == null || option.getInstrumentToken() == null) {
                log.warn("[EOD-downtrend] rule id={} {} — no option instrument for ATM strike={} expiry={}",
                        rule.getId(), side, atmStrike, expiry);
                continue;
            }
            String optionToken = option.getInstrumentToken().toString();

            List<int[]> passing = scanSide(optionToken, tradingDay, rule);
            if (passing.isEmpty()) {
                log.debug("[EOD-downtrend] rule id={} {} ATM={} — nothing trending down",
                        rule.getId(), side, atmStrike);
                continue;
            }

            // ATR is measured on the option leg, not the underlying, and is therefore
            // per-side. target/stop_loss end up on trade_order and are compared by
            // PositionService against per-share option-premium P&L, so an ATR taken on
            // the index would be in the wrong unit entirely: NIFTY ATR(14) runs ~180
            // points while an ATM premium is ~100, which made target unreachable for a
            // short leg — max profit on a SELL is the premium itself.
            BigDecimal atr = computeAtr(optionToken, tradingDay, rule.getAtrPeriods());
            if (atr == null || atr.signum() <= 0) {
                log.warn("[EOD-downtrend] rule id={} {} — ATR unavailable for token={} on {}, skipping side",
                        rule.getId(), side, optionToken, tradingDay);
                continue;
            }

            insertAutoTradeConfig(rule, defaults, nextDay, side, atr, passing, instrument, strikeDepth);
            written++;
        }
        return written;
    }

    /**
     * Returns the list of {@code [sma, timeframe-minutes]} pairs whose last-candle
     * down-trend flag is on for the given strike on {@code tradingDay}.
     * <p>The strike series is fetched <i>once per timeframe</i> and all SMAs are
     * computed on it before {@link SmaTrendCalculator} runs.</p>
     *
     * <p><b>The fetch spans {@link #lookbackCalendarDays(int)} calendar days, not
     * just {@code tradingDay}.</b> SMAs must be continuous across sessions to match
     * what the trader sees on a chart — a 15-minute chart carries ~25 candles per
     * session, so a single day cannot even produce SMA(50), let alone SMA(500), and
     * {@code SMAIndicatorImpl} returns null whenever {@code period > series.size()}.
     * Fetching one day silently reduced the whole grid to SMA(20) (plus SMA(50) at
     * 5-minute) and made every longer period permanently unreachable.
     * {@code AnalysisScheduler} already fetches with a lookback for exactly this
     * reason; this method now matches it.</p>
     *
     * <p>Widening the window does <i>not</i> leak prior sessions into the verdict:
     * the {@code startTime} trim below is a time-of-day filter, and
     * {@link SmaTrendCalculator} resets its deviation counters on every new day, so
     * the flags read off the final candle still describe {@code tradingDay} alone —
     * only the SMA values themselves now carry the correct history.</p>
     *
     * <p><b>A period the broker cannot cover is dropped, not approximated.</b> The
     * fetch window is only a request; what matters is how much history actually came
     * back for this leg. Each period is admitted only if a full {@code period}-wide
     * window has already closed by the first judged candle. A newly listed strike, a
     * thin leg, or a broker that trims history therefore contributes fewer combos —
     * or none — instead of a trend read off a partial average.</p>
     */
    private List<int[]> scanSide(String optionToken, LocalDate tradingDay, SmaDowntrendRule rule) {
        List<int[]> passing = new ArrayList<>();

        LocalDateTime to = LocalDateTime.of(tradingDay, MARKET_CLOSE);

        for (int tfMinutes : TIMEFRAMES_MINUTES) {
            String interval = tfMinutes + "minute";

            LocalDateTime from = LocalDateTime.of(tradingDay, MARKET_OPEN)
                    .minusDays(lookbackCalendarDays(tfMinutes));

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

            // First candle that actually gets judged: on tradingDay, at/after start_time.
            // Its index is also the count of candles preceding it, i.e. the warm-up the
            // broker actually supplied — which is what decides SMA sufficiency below.
            int evalStartIdx = -1;
            for (int i = 0; i < series.size(); i++) {
                MarketData c = series.get(i);
                if (c.getTimestamp() == null) continue;
                if (!c.getTimestamp().toLocalDate().equals(tradingDay)) continue;
                if (c.getTimestamp().toLocalTime().isBefore(rule.getStartTime())) continue;
                evalStartIdx = i;
                break;
            }
            if (evalStartIdx < 0) {
                log.debug("[EOD-downtrend] token={} tf={} — no candles on {} at/after {}",
                        optionToken, interval, tradingDay, rule.getStartTime());
                continue;
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
                // Sufficiency gate. ta4j's SMAIndicator averages however many bars it
                // has rather than returning null, so a period with too little history
                // still yields a number — a partial average that looks like a real SMA
                // and would be silently trend-tested. Require a full period-wide window
                // to already be closed at the first judged candle; if the broker did not
                // return that much history for this leg, the period contributes no combo.
                if (evalStartIdx < period - 1) {
                    log.debug("[EOD-downtrend] token={} tf={} SMA{} — insufficient history: "
                                    + "{} candles before {} {}, need {}; period dropped",
                            optionToken, interval, period, evalStartIdx, tradingDay,
                            rule.getStartTime(), period - 1);
                    continue;
                }
                if (smaDownFlag(last, period)) {
                    passing.add(new int[]{period, tfMinutes});
                }
            }
        }
        return passing;
    }

    /**
     * How far back to ask the broker so the longest period in {@link #SMA_PERIODS}
     * has a full window for every judged candle at {@code tfMinutes}.
     *
     * <p>Stated in candles first, because that is the real requirement:
     * {@code maxPeriod} candles of warm-up (SMA(500) at 15-minute needs 500) plus
     * one session's worth, so the SMA is already full-window at the day's first
     * candle and stays full-window to its last. That count is converted to calendar
     * days via {@link #SESSION_MINUTES}, the 7/5 factor for weekends, and {@code +5}
     * for holidays.</p>
     *
     * <p>This only sizes the <i>request</i>. It is deliberately generous and never
     * decides anything: whether a period is actually usable is settled in
     * {@code scanSide} by counting the candles the broker really returned. A short
     * fetch drops that period rather than trend-testing a partial average. This is
     * a data-sufficiency calculation, not a trading-behaviour knob.</p>
     */
    private int lookbackCalendarDays(int tfMinutes) {
        int maxPeriod = 0;
        for (int p : SMA_PERIODS) {
            maxPeriod = Math.max(maxPeriod, p);
        }
        int candlesPerSession = Math.max(1, SESSION_MINUTES / tfMinutes);
        int candlesNeeded = maxPeriod + candlesPerSession;

        double tradingDays = (double) candlesNeeded / candlesPerSession;
        return (int) Math.ceil(tradingDays * 7.0 / 5.0) + 5;
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

    /**
     * ATR(N) over daily candles of {@code token}.
     *
     * <p><b>Pass the option leg's token, not the underlying's.</b> The result lands
     * on {@code trade_config.target} / {@code stop_loss}, which
     * {@code PositionService.thresholdBreach} compares against per-share option
     * <i>premium</i> P&amp;L. An ATR taken on the index is denominated in index
     * points and is not comparable: NIFTY ATR(14) sits near 180 while an ATM
     * premium is nearer 100, so the target exceeded the most a short leg can ever
     * earn (premium decaying to zero) and could never trigger.</p>
     */
    private BigDecimal computeAtr(String token, LocalDate tradingDay, Integer periods) {
        if (token == null || token.isBlank()) return null;
        int n = periods == null || periods <= 0 ? 14 : periods;

        LocalDateTime from = LocalDateTime.of(tradingDay.minusDays(Math.max(n * 2L + 10, 30)), LocalTime.MIDNIGHT);
        LocalDateTime to   = LocalDateTime.of(tradingDay, LocalTime.of(23, 59));

        List<MarketData> daily = marketDataService.fetchHistoricalData(token, from, to, "day");
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

    /**
     * Strike-band half-width in strikes, derived from the underlying's ATR:
     * {@code ceil(ATR / strikePoints)}, clamped to
     * {@link #MIN_STRIKE_DEPTH}..{@link #MAX_STRIKE_DEPTH}.
     *
     * <p>Sizing this from ATR is what keeps an open position observable. The band
     * is recomputed from the live ATM on every tick, so if the underlying moves
     * further than the band is wide, the strike a position was opened on drops out
     * of the fetch set and its cached candles stop advancing — the monitor then
     * reads a frozen quote and target/SL can never trigger. A band as wide as a
     * typical day's travel keeps the entry strike covered.</p>
     *
     * <p>The clamp is a safety rail, not a trading rule: the floor keeps a band
     * around ATM on unusually quiet days, and the ceiling stops a volatility spike
     * from fanning out into dozens of broker fetches per tick.</p>
     */
    private int strikeDepthFor(BigDecimal underlyingAtr, BigDecimal strikePoints) {
        if (underlyingAtr == null || underlyingAtr.signum() <= 0
                || strikePoints == null || strikePoints.signum() <= 0) {
            return MIN_STRIKE_DEPTH;
        }
        int depth = underlyingAtr.divide(strikePoints, 0, RoundingMode.CEILING).intValue();
        return Math.max(MIN_STRIKE_DEPTH, Math.min(MAX_STRIKE_DEPTH, depth));
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
                                       List<int[]> passing,
                                       Instrument instrument,
                                       int strikeDepth) {
        TradeConfig tc = new TradeConfig();
        tc.setTradingDate(nextDay);
        tc.setTradingSide(side);
        tc.setInstrument(rule.getInstrument());
        tc.setStratergyId(rule.getStrategyId());
        tc.setSource(SOURCE_AUTO);

        // ATR is the option leg's, so these are premium points — the same unit
        // PositionService compares against. See computeAtr.
        tc.setTarget(atr.multiply(rule.getTargetMultiplier()).setScale(2, RoundingMode.HALF_UP));
        tc.setStopLoss(atr.multiply(rule.getSlMultiplier()).setScale(2, RoundingMode.HALF_UP));

        tc.setTransactionType(defaults.transactionType());
        tc.setMaxLoss(defaults.maxLoss());
        tc.setNumberOfTradesPerDay(defaults.noOfTrades());
        tc.setNumberOfParallelTrades(defaults.noOfParallelTrades());

        // Order quantity goes to the broker verbatim, and NFO only accepts whole
        // lots — so it comes from the contract, not from a strategy constant.
        // strategyDefaults' value is a last-resort fallback.
        Integer lotQty = instrument == null ? null : instrument.getLotQty();
        tc.setLotQuantity(lotQty != null && lotQty > 0 ? lotQty : defaults.lotQuantity());

        // Symmetric band around ATM, sized by strikeDepthFor(...).
        //
        // NOTE: 0 does NOT mean "ATM" — AnalysisScheduler.calculateStrikesForCandles
        // builds a strike list only when itmDepth > 0 or otmDepth > 0, and never reads
        // atmDepth at all, so 0/0/0 yields an EMPTY strike list and the config can
        // never trade. The ITM loop starts at i=0, whose first element is the base
        // (ATM) strike, so itmDepth already includes ATM.
        tc.setItmDepth(strikeDepth);
        tc.setOtmDepth(strikeDepth);
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
