package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.RuleEngine;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * {@link Strategy7} is Strategy 6 plus the first-hour gate. Pinned here: the
 * ATR-normalised first-hour move (sign per side, session roll-up), the
 * threshold on both sides of the line, the checkpoint (before 10:15 the rule
 * is unknown and allows), the unknown cases, and that everything Strategy 6
 * does is inherited unchanged.
 */
class Strategy7RulesTest {

    private static final String UNDERLYING_KEY = "HIST:NIFTY:NSE:SPOT|5minute";
    private static final String KEY_5M = UNDERLYING_KEY + "|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";
    private static final LocalDate DAY = LocalDate.of(2026, 9, 7);

    private final Strategy7 strategy = new Strategy7(null);

    @AfterEach
    void tearDown() {
        SharedData.marketDataByInstrumentAndInterval.clear();
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.strikeMarketDataTick.clear();
    }

    // ------------------------------------------------------------ fixtures

    private static MarketData bar(LocalDateTime ts, double o, double h, double l, double c) {
        MarketData m = new MarketData();
        m.setTimestamp(ts);
        m.setOpen(BigDecimal.valueOf(o)); m.setHigh(BigDecimal.valueOf(h));
        m.setLow(BigDecimal.valueOf(l)); m.setClose(BigDecimal.valueOf(c));
        return m;
    }

    /**
     * Underlying series: 15 prior sessions each with a true range of 200 (one
     * bar per session, close 24000), then today's first hour from 09:15 to
     * 10:10 moving {@code firstHourMove} points, then a flat 10:10..10:30.
     */
    private static void underlying(double firstHourMove) {
        List<MarketData> s = new ArrayList<>();
        for (int k = 20; k >= 1; k--) {
            LocalDate dte = DAY.minusDays(k);
            if (dte.getDayOfWeek().getValue() >= 6) continue;
            s.add(bar(dte.atTime(9, 15), 24000, 24100, 23900, 24000));
        }
        double open = 24000;
        for (int i = 0; i < 12; i++) {           // 09:15 .. 10:10
            double a = open + firstHourMove * i / 12.0, b = open + firstHourMove * (i + 1) / 12.0;
            s.add(bar(DAY.atTime(9, 15).plusMinutes(5L * i), a, Math.max(a, b), Math.min(a, b), b));
        }
        for (int i = 12; i < 16; i++) {          // 10:15 .. 10:30, flat
            double v = open + firstHourMove;
            s.add(bar(DAY.atTime(9, 15).plusMinutes(5L * i), v, v, v, v));
        }
        SharedData.marketDataByInstrumentAndInterval.put(UNDERLYING_KEY, s);
    }

    private static TradeConfigCombinedDTO config(String side) {
        TradeConfig tc = new TradeConfig();
        tc.setId(7); tc.setTradingSide(side); tc.setTransactionType("SELL");
        return new TradeConfigCombinedDTO(tc, new Instrument(), null, List.of(), 7);
    }

    /** A cross-down signal bar with the down flag set and a flat SMA-20 (Strategy 2 passes). */
    private RuleContext ctx(LocalDateTime signalBar, String side) {
        MarketData p = new MarketData();
        p.setTimestamp(signalBar.minusMinutes(5)); p.setOpen(new BigDecimal("112")); p.setClose(new BigDecimal("111"));
        p.setSmaValue50(101.0); p.setSmaValue20(100.0);
        MarketData c = new MarketData();
        c.setTimestamp(signalBar); c.setOpen(new BigDecimal("110")); c.setClose(new BigDecimal("95"));
        c.setSmaValue50(100.0); c.setSma50DownTrending(true); c.setSmaValue20(100.0);
        return new RuleContext(c, 1, List.of(p, c), 50, config(side), signalBar.plusMinutes(5), LocalTime.of(15, 15), KEY_5M);
    }

    private RuleEngine.Decision decide(LocalDateTime signalBar, String side) {
        return RuleEngine.decide(ctx(signalBar, side), strategy.sellRulesFor(50), strategy.buyRulesFor(50));
    }

    // ------------------------------------------------------------ the measure

    @Test
    @DisplayName("first-hour move is signed per side and divided by the session ATR")
    void measureIsSignedAndAtrNormalised() {
        underlying(+100);   // market rose 100 = 0.5 ATR in the first hour
        LocalDateTime bar = DAY.atTime(10, 20);

        Double ce = CommonRules.firstHourMoveInFavourAtr(ctx(bar, "CE"), Strategy7.FIRST_HOUR_CHECKPOINT);
        Double pe = CommonRules.firstHourMoveInFavourAtr(ctx(bar, "PE"), Strategy7.FIRST_HOUR_CHECKPOINT);

        assertThat(ce).isCloseTo(-0.5, within(1e-9));
        assertThat(pe).isCloseTo(+0.5, within(1e-9));
    }

    // ------------------------------------------------------------ the gate

    @Test
    @DisplayName("market rose 0.5 ATR in the first hour → a CE entry after 10:15 is blocked, a PE entry is allowed")
    void againstBlocksInFavourAllows() {
        underlying(+100);
        LocalDateTime bar = DAY.atTime(10, 20);

        RuleEngine.Decision ce = decide(bar, "CE");
        assertThat(ce.action()).isEqualTo(TradeAction.NONE);
        assertThat(ce.reason()).contains("firstHourNotAgainstOrUnknown");

        assertThat(decide(bar, "PE").action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("the threshold: −0.2 ATR against is still allowed, −0.21 is not")
    void thresholdEdges() {
        underlying(+40);    // 0.20 ATR against a CE short
        assertThat(decide(DAY.atTime(10, 20), "CE").action()).isEqualTo(TradeAction.SELL);

        underlying(+42);    // 0.21 ATR
        assertThat(decide(DAY.atTime(10, 20), "CE").action()).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("before the 10:15 checkpoint the first hour is unfinished → unknown, entry allowed")
    void beforeCheckpointAllows() {
        underlying(+200);   // a full ATR against, but the signal bar is 09:45
        assertThat(decide(DAY.atTime(9, 45), "CE").action()).isEqualTo(TradeAction.SELL);
        assertThat(decide(DAY.atTime(10, 10), "CE").action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("no underlying series cached → unknown, entry allowed")
    void noUnderlyingAllows() {
        assertThat(decide(DAY.atTime(10, 20), "CE").action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("too few prior sessions for an ATR → unknown, entry allowed")
    void tooFewSessionsAllows() {
        List<MarketData> s = new ArrayList<>();
        s.add(bar(DAY.minusDays(1).atTime(9, 15), 24000, 24100, 23900, 24000));
        for (int i = 0; i < 16; i++) {
            double v = 24000 + 20.0 * i;
            s.add(bar(DAY.atTime(9, 15).plusMinutes(5L * i), v, v + 20, v, v + 20));
        }
        SharedData.marketDataByInstrumentAndInterval.put(UNDERLYING_KEY, s);

        assertThat(decide(DAY.atTime(10, 20), "CE").action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("session's first bar missing (day starts at 10:00) → not an open, unknown, entry allowed")
    void missingOpenAllows() {
        List<MarketData> s = new ArrayList<>();
        for (int k = 20; k >= 1; k--) {
            LocalDate dte = DAY.minusDays(k);
            if (dte.getDayOfWeek().getValue() >= 6) continue;
            s.add(bar(dte.atTime(9, 15), 24000, 24100, 23900, 24000));
        }
        s.add(bar(DAY.atTime(10, 0), 24000, 24200, 24000, 24200));
        s.add(bar(DAY.atTime(10, 5), 24200, 24200, 24200, 24200));
        SharedData.marketDataByInstrumentAndInterval.put(UNDERLYING_KEY, s);

        assertThat(decide(DAY.atTime(10, 20), "CE").action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("no trading side on the config → unknown, entry allowed")
    void noSideAllows() {
        underlying(+200);
        assertThat(decide(DAY.atTime(10, 20), null).action()).isEqualTo(TradeAction.SELL);
    }

    // ------------------------------------------------------------ inheritance

    @Test
    @DisplayName("rule order: Strategy 6's four rules first, the first-hour gate last")
    void ruleOrder() {
        List<String> names = strategy.sellRulesFor(50).required.stream().map(r -> r.name()).toList();

        assertThat(names).containsExactly("isSma50DownTrending", "sma20SlopeNotUp",
                "htf15Sma50DownOrUnknown", "entryAtOrBefore1445", "firstHourNotAgainstOrUnknown");
    }

    @Test
    @DisplayName("Strategy 6's gates still bite: a 14:50 signal is blocked even when the first hour favoured the leg")
    void cutoffInherited() {
        underlying(-200);   // market fell a full ATR: perfect for a CE short
        RuleEngine.Decision d = decide(DAY.atTime(14, 50), "CE");

        assertThat(d.action()).isEqualTo(TradeAction.NONE);
        assertThat(d.reason()).contains("entryAtOrBefore1445");
    }

    @Test
    @DisplayName("declarations: id 7, 15-minute confirmation and stop-loss lock inherited, period 20 fail-closed")
    void declarations() {
        assertThat(strategy.getId()).isEqualTo(7);
        assertThat(strategy.confirmationTimeframes()).containsExactly(15);
        assertThat(strategy.stopLossLocksBookForDay()).isTrue();
        assertThat(strategy.sellRulesFor(20).required).isEmpty();
    }
}
