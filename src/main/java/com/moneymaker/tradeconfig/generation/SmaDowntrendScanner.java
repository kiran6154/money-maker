package com.moneymaker.tradeconfig.generation;

import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaDowntrendRule;
import com.moneymaker.indicator.IndicatorConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.strategy.rules.SmaTrendCalculator;
import com.moneymaker.util.IntCsv;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * The shipped {@link EodTrendScanner}: the SMA down-trend grid walk
 * ({@code indicator_type='SMA_DOWNTREND'}), extracted from
 * {@link EodDowntrendDetectionService} when the grid became per-rule data
 * (changeset 039).
 *
 * <p>The grid is the rule's own {@code sma_periods} × {@code timeframes_minutes}
 * (defaults {@code 50,100,200,500} × {@code 5,15} — the old hardcoded values),
 * so skipping a period is an UPDATE, not a redeploy. Periods are capped to
 * {@link #SUPPORTED_PERIODS}: those are the flags {@code MarketData} carries and
 * {@link SmaTrendCalculator} tracks, and a period outside the set is dropped
 * with a WARN rather than silently trend-tested against a flag that can never
 * be set. Extending that set is a code change — the flag fields, the
 * calculator, and {@link #smaDownFlag} move together.</p>
 */
@Slf4j
@Component
public class SmaDowntrendScanner implements EodTrendScanner {

    public static final String TYPE = "SMA_DOWNTREND";

    private static final LocalTime MARKET_CLOSE = LocalTime.of(15, 20);
    private static final LocalTime MARKET_OPEN  = LocalTime.of(9, 15);

    /** Tradable minutes in one NSE session (09:15–15:30). Used only to size the
     *  SMA lookback window — see {@link #lookbackCalendarDays}. */
    private static final int SESSION_MINUTES = 375;

    /** The old hardcoded grid — what a rule with blank columns falls back to.
     *  Public because {@code DowntrendRuleAdminService} normalises a blanked
     *  form field to it, so the UI and the scanner agree on what blank means. */
    public static final List<Integer> DEFAULT_SMA_PERIODS = List.of(50, 100, 200, 500);
    public static final List<Integer> DEFAULT_TIMEFRAMES_MINUTES = List.of(5, 15);

    /** The periods {@code MarketData} has trend flags for. A rule may select a
     *  subset; anything else needs the flag/calculator code extended first.
     *  Public so the rules UI can reject an unsupported period at save time
     *  instead of leaving it to this scanner's run-time WARN-and-drop. */
    public static final Set<Integer> SUPPORTED_PERIODS = Set.of(20, 50, 100, 200, 500);

    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;

    public SmaDowntrendScanner(MarketDataService marketDataService,
                               IndicatorService indicatorService) {
        this.marketDataService = marketDataService;
        this.indicatorService = indicatorService;
    }

    @Override
    public String indicatorType() {
        return TYPE;
    }

    /**
     * Returns the list of {@code [sma, timeframe-minutes]} pairs whose last-candle
     * down-trend flag is on for the given strike on {@code tradingDay}.
     * <p>The strike series is fetched <i>once per timeframe</i> and every selected
     * SMA is computed on it before {@link SmaTrendCalculator} runs.</p>
     *
     * <p><b>The fetch spans {@link #lookbackCalendarDays} calendar days, not
     * just {@code tradingDay}.</b> SMAs must be continuous across sessions to match
     * what the trader sees on a chart — a 15-minute chart carries ~25 candles per
     * session, so a single day cannot even produce SMA(50), let alone SMA(500), and
     * {@code SMAIndicatorImpl} returns null whenever {@code period > series.size()}.
     * Fetching one day silently reduced the whole grid to its shortest period and
     * made every longer one permanently unreachable.
     * {@code AnalysisScheduler} already fetches with a lookback for exactly this
     * reason; this method matches it.</p>
     *
     * <p>Widening the window does <i>not</i> leak prior sessions into the verdict:
     * the {@code startTime} trim below is a time-of-day filter, and
     * {@link SmaTrendCalculator} resets its deviation counters on every new day, so
     * the flags read off the final candle still describe {@code tradingDay} alone —
     * only the SMA values themselves carry the wider history.</p>
     *
     * <p><b>A period the broker cannot cover is dropped, not approximated.</b> The
     * fetch window is only a request; what matters is how much history actually came
     * back for this leg. Each period is admitted only if a full {@code period}-wide
     * window has already closed by the first judged candle. A newly listed strike, a
     * thin leg, or a broker that trims history therefore contributes fewer combos —
     * or none — instead of a trend read off a partial average.</p>
     */
    @Override
    public List<int[]> scan(String optionToken, LocalDate tradingDay, SmaDowntrendRule rule) {
        List<int[]> passing = new ArrayList<>();

        List<Integer> periods = usablePeriods(rule);
        List<Integer> timeframes = timeframes(rule);
        if (periods.isEmpty() || timeframes.isEmpty()) {
            return passing;
        }

        LocalDateTime to = LocalDateTime.of(tradingDay, MARKET_CLOSE);

        for (int tfMinutes : timeframes) {
            String interval = tfMinutes + "minute";

            LocalDateTime from = LocalDateTime.of(tradingDay, MARKET_OPEN)
                    .minusDays(lookbackCalendarDays(tfMinutes, periods));

            List<MarketData> series = marketDataService.fetchHistoricalData(optionToken, from, to, interval);
            if (series == null || series.isEmpty()) {
                continue;
            }

            // Populate sma_value{...} for every selected period on every candle.
            // Unselected periods keep a null SMA, so SmaTrendCalculator leaves
            // their flags false and no combo can be produced for them — skipping
            // a period is exactly "never compute it".
            for (int period : periods) {
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

            for (int period : periods) {
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
     * The rule's selected SMA periods, capped to {@link #SUPPORTED_PERIODS}.
     * Blank column = the default grid (disabling a rule is {@code enabled=false},
     * not a blanked column). An unsupported period is dropped with a WARN naming
     * it — {@code MarketData} has no flag for it, so trend-testing it can only
     * ever fail silently.
     */
    // Package-private for the unit test — the grid resolution is the part of
    // this scanner that changed in 039, and the part hand-edited SQL can break.
    List<Integer> usablePeriods(SmaDowntrendRule rule) {
        List<Integer> selected = IntCsv.parse(rule.getSmaPeriods());
        if (selected.isEmpty()) {
            return DEFAULT_SMA_PERIODS;
        }
        List<Integer> usable = new ArrayList<>(selected.size());
        for (Integer period : selected) {
            if (SUPPORTED_PERIODS.contains(period)) {
                usable.add(period);
            } else {
                log.warn("[EOD-downtrend] rule id={} — sma_periods contains {}, which has no "
                                + "MarketData trend flag; dropping it. Supported: {}. Adding a new "
                                + "period is a code change (MarketData flags + SmaTrendCalculator).",
                        rule.getId(), period, SUPPORTED_PERIODS.stream().sorted().toList());
            }
        }
        if (usable.isEmpty()) {
            log.warn("[EOD-downtrend] rule id={} — no usable period in sma_periods='{}', "
                    + "rule scans nothing", rule.getId(), rule.getSmaPeriods());
        }
        return usable;
    }

    /** The rule's selected timeframes in minutes; blank column = the default {@code 5,15}. */
    List<Integer> timeframes(SmaDowntrendRule rule) {
        List<Integer> selected = IntCsv.parse(rule.getTimeframesMinutes());
        return selected.isEmpty() ? DEFAULT_TIMEFRAMES_MINUTES : selected;
    }

    /**
     * How far back to ask the broker so the longest <i>selected</i> period has a
     * full window for every judged candle at {@code tfMinutes}.
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
     * {@link #scan} by counting the candles the broker really returned. A short
     * fetch drops that period rather than trend-testing a partial average. This is
     * a data-sufficiency calculation, not a trading-behaviour knob — which is also
     * why a rule that skips SMA(500) now fetches a proportionally shorter window.</p>
     */
    private int lookbackCalendarDays(int tfMinutes, List<Integer> periods) {
        int maxPeriod = 0;
        for (int p : periods) {
            maxPeriod = Math.max(maxPeriod, p);
        }
        int candlesPerSession = Math.max(1, SESSION_MINUTES / tfMinutes);
        int candlesNeeded = maxPeriod + candlesPerSession;

        double tradingDays = (double) candlesNeeded / candlesPerSession;
        return (int) Math.ceil(tradingDays * 7.0 / 5.0) + 5;
    }

    /**
     * Period → the entity's down-trend flag. Reached only for periods in
     * {@link #SUPPORTED_PERIODS}; {@code default: false} makes an unmapped
     * period fail closed either way.
     */
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
}
