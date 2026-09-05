package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.entity.MarketData;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.RuleEngine;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link Strategy6} is Strategy 2 plus three gates. Two of them are rules on the
 * sell side and are pinned here bar by bar: the 15-minute SMA-50 confirmation
 * (with its "unknown allows" cases, each of which is a real tick the engine
 * produces) and the 14:45 entry cut-off. The third — the stop-loss lock — is a
 * ledger gate and lives in {@code OrderServiceStopLossLockTest}; here only the
 * declaration is checked.
 *
 * <p>The inherited behaviour is asserted too: Strategy 2's slope filter still
 * blocks, a period the baseline fails closed stays closed, and the close-time
 * BUY exit is untouched by the sell-side gates.</p>
 */
class Strategy6RulesTest {

    private static final String KEY_5M  = "HIST:NIFTY:NSE:SPOT|5minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";
    private static final String KEY_15M = "HIST:NIFTY:NSE:SPOT|15minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";

    private final Strategy6 strategy = new Strategy6(null);

    @AfterEach
    void tearDown() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.strikeMarketDataTick.clear();
    }

    // ------------------------------------------------------------ fixtures

    /** A cross-down bar (open above, close below SMA-50) with the down flag set. */
    private static MarketData crossDown(LocalDateTime ts, double sma20) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(new BigDecimal("110"));
        c.setClose(new BigDecimal("95"));
        c.setSmaValue50(100.0);
        c.setSma50DownTrending(true);
        c.setSmaValue20(sma20);
        return c;
    }

    private static MarketData prev(LocalDateTime ts, double sma20) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(new BigDecimal("112"));
        c.setClose(new BigDecimal("111"));
        c.setSmaValue50(101.0);
        c.setSmaValue20(sma20);
        return c;
    }

    /** 15-minute bars for the given day, SMA-50 stamped from {@code sma50s}, one bar per value from 09:15. */
    private static void htfSeries(LocalDateTime day0915, double... sma50s) {
        List<MarketData> series = new ArrayList<>();
        for (int i = 0; i < sma50s.length; i++) {
            MarketData c = new MarketData();
            c.setTimestamp(day0915.plusMinutes(15L * i));
            c.setOpen(BigDecimal.TEN); c.setClose(BigDecimal.TEN);
            c.setSmaValue50(sma50s[i]);
            series.add(c);
        }
        SharedData.strikeMarketDataByInstrumentAndInterval.put(KEY_15M, series);
    }

    private RuleEngine.Decision decide(LocalDateTime signalBar, LocalDateTime asOf, double prevSma20, double currSma20) {
        MarketData p = prev(signalBar.minusMinutes(5), prevSma20);
        MarketData c = crossDown(signalBar, currSma20);
        RuleContext ctx = new RuleContext(c, 1, List.of(p, c), 50, null, asOf, LocalTime.of(15, 15), KEY_5M);
        return RuleEngine.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50));
    }

    private RuleEngine.Decision decideSlopeFlat(LocalDateTime signalBar, LocalDateTime asOf) {
        return decide(signalBar, asOf, 100.0, 100.0);
    }

    // ------------------------------------------------------------ 15-minute confirmation

    @Test
    @DisplayName("cross-down + down flag + 15-min SMA-50 falling all session → SELL")
    void htfDownAdmitsEntry() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 10, 15);
        LocalDateTime asOf = bar.plusMinutes(5);
        htfSeries(LocalDateTime.of(2026, 9, 7, 9, 15), 120, 118, 117, 115);   // 09:15..10:00 buckets
        SharedData.strikeMarketDataTick.put(KEY_15M, asOf);

        RuleEngine.Decision d = decideSlopeFlat(bar, asOf);

        assertThat(d.action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("15-min SMA-50 rose on one bar of the session → the confirmation fails, no entry")
    void htfNotDownBlocksEntry() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 10, 15);
        LocalDateTime asOf = bar.plusMinutes(5);
        htfSeries(LocalDateTime.of(2026, 9, 7, 9, 15), 120, 118, 119, 115);   // one uptick → flag off for the day
        SharedData.strikeMarketDataTick.put(KEY_15M, asOf);

        RuleEngine.Decision d = decideSlopeFlat(bar, asOf);

        assertThat(d.action()).isEqualTo(TradeAction.NONE);
        assertThat(d.reason()).contains("htf15Sma50DownOrUnknown");
    }

    @Test
    @DisplayName("no 15-minute series cached for the leg → unknown, entry allowed")
    void noHtfSeriesAllows() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 10, 15);
        RuleEngine.Decision d = decideSlopeFlat(bar, bar.plusMinutes(5));

        assertThat(d.action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("before 09:30 the newest settled 15-min bar is yesterday's → unknown, the opening-bar entry is allowed")
    void previousSessionHtfBarAllows() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 9, 15);      // the day's first 5-min bar
        LocalDateTime asOf = bar.plusMinutes(5);
        htfSeries(LocalDateTime.of(2026, 9, 4, 14, 45), 120, 121, 122);    // previous session, rising
        SharedData.strikeMarketDataTick.put(KEY_15M, asOf);

        RuleEngine.Decision d = decideSlopeFlat(bar, asOf);

        assertThat(d.action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("a 15-min series not refreshed by this tick (S8 stale key) → unknown, entry allowed")
    void staleHtfKeyAllows() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 10, 15);
        LocalDateTime asOf = bar.plusMinutes(5);
        htfSeries(LocalDateTime.of(2026, 9, 7, 9, 15), 120, 118, 119, 115);   // would block if trusted
        SharedData.strikeMarketDataTick.put(KEY_15M, asOf.minusMinutes(5));

        RuleEngine.Decision d = decideSlopeFlat(bar, asOf);

        assertThat(d.action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("SMA-50 not yet stamped on the 15-min bar (short series) → unknown, entry allowed")
    void unstampedHtfSmaAllows() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 10, 15);
        LocalDateTime asOf = bar.plusMinutes(5);
        List<MarketData> series = new ArrayList<>();
        MarketData c = new MarketData();
        c.setTimestamp(LocalDateTime.of(2026, 9, 7, 10, 0));
        c.setOpen(BigDecimal.TEN); c.setClose(BigDecimal.TEN);   // smaValue50 left null
        series.add(c);
        SharedData.strikeMarketDataByInstrumentAndInterval.put(KEY_15M, series);
        SharedData.strikeMarketDataTick.put(KEY_15M, asOf);

        RuleEngine.Decision d = decideSlopeFlat(bar, asOf);

        assertThat(d.action()).isEqualTo(TradeAction.SELL);
    }

    // ------------------------------------------------------------ entry cut-off

    @Test
    @DisplayName("a 14:45 signal bar is the last admissible entry; 14:50 is blocked")
    void entryCutoffAt1445() {
        LocalDateTime last = LocalDateTime.of(2026, 9, 7, 14, 45);
        assertThat(decideSlopeFlat(last, last.plusMinutes(5)).action()).isEqualTo(TradeAction.SELL);

        LocalDateTime late = LocalDateTime.of(2026, 9, 7, 14, 50);
        RuleEngine.Decision d = decideSlopeFlat(late, late.plusMinutes(5));
        assertThat(d.action()).isEqualTo(TradeAction.NONE);
        assertThat(d.reason()).contains("entryAtOrBefore1445");
    }

    @Test
    @DisplayName("the cut-off follows the close-signal time: with a 15:00 close signal, 14:30 is the last bar")
    void entryCutoffFollowsCloseSignalTime() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 14, 35);
        MarketData p = prev(bar.minusMinutes(5), 100.0);
        MarketData c = crossDown(bar, 100.0);
        RuleContext ctx = new RuleContext(c, 1, List.of(p, c), 50, null, bar.plusMinutes(5), LocalTime.of(15, 0), KEY_5M);

        RuleEngine.Decision d = RuleEngine.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50));

        assertThat(d.action()).isEqualTo(TradeAction.NONE);
    }

    // ------------------------------------------------------------ inherited behaviour

    @Test
    @DisplayName("Strategy 2's slope filter is inherited: SMA-20 rising on the signal bar → no entry")
    void slopeUpStillBlocks() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 10, 15);
        RuleEngine.Decision d = decide(bar, bar.plusMinutes(5), 100.0, 100.5);

        assertThat(d.action()).isEqualTo(TradeAction.NONE);
        assertThat(d.reason()).contains("sma20SlopeNotUp");
    }

    @Test
    @DisplayName("rule order: baseline down-trend, slope, 15-min confirmation, cut-off")
    void ruleOrderIsBaselineFirst() {
        List<String> names = strategy.sellRulesFor(50).required.stream().map(r -> r.name()).toList();

        assertThat(names).containsExactly("isSma50DownTrending", "sma20SlopeNotUp",
                "htf15Sma50DownOrUnknown", "entryAtOrBefore1445");
    }

    @Test
    @DisplayName("a period the baseline fails closed (20) stays fail-closed")
    void baselineDisabledPeriodStaysDisabled() {
        assertThat(strategy.sellRulesFor(20).required).isEmpty();
        assertThat(strategy.sellRulesFor(20).anyOf).isEmpty();
    }

    @Test
    @DisplayName("the close-time BUY exit is not gated: no cross at 15:15 → BUY even after the cut-off")
    void closeTimeExitUntouched() {
        LocalDateTime bar = LocalDateTime.of(2026, 9, 7, 15, 15);
        MarketData c = new MarketData();
        c.setTimestamp(bar);
        c.setOpen(new BigDecimal("105")); c.setClose(new BigDecimal("110"));
        c.setSmaValue50(100.0);
        RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, null, bar.plusMinutes(5), LocalTime.of(15, 15), KEY_5M);

        RuleEngine.Decision d = RuleEngine.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50));

        assertThat(d.action()).isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("declarations: confirmation timeframe 15, stop-loss locks the book; strategy 2 declares neither")
    void declarations() {
        assertThat(strategy.getId()).isEqualTo(6);
        assertThat(strategy.confirmationTimeframes()).containsExactly(15);
        assertThat(strategy.stopLossLocksBookForDay()).isTrue();

        Strategy2 two = new Strategy2(null);
        assertThat(two.confirmationTimeframes()).isEmpty();
        assertThat(two.stopLossLocksBookForDay()).isFalse();
    }
}
