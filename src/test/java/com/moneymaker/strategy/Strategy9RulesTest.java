package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.entity.MarketData;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.rules.RuleContext;
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

/**
 * {@link Strategy9} = Strategy 8 + three gates, each off when its threshold is
 * null and each allowing when it cannot be judged. Pinned bar by bar on the
 * same synthetic 15-minute series as {@code Strategy8RulesTest}, with the
 * shared caches populated for the volume gate.
 */
class Strategy9RulesTest {

    private static final String TOKEN = "HIST:NIFTY:NSE:SPOT";
    private static final String KEY_CE = TOKEN + "|15minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";
    private static final String KEY_CE_DUP = TOKEN + "|15minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|3|3";
    private static final String KEY_PE = TOKEN + "|15minute|PE|24000|HIST:NIFTY:NFO:2026-09-10:24000:PE|2|2";
    private static final String KEY_FAR = TOKEN + "|15minute|CE|24500|HIST:NIFTY:NFO:2026-09-10:24500:CE|2|2";
    private static final LocalTime CLOSE_SIGNAL = LocalTime.of(15, 15);
    private static final LocalDateTime DAY = LocalDateTime.of(2026, 9, 7, 9, 15);

    /** Resolver-free Strategy 9 whose expiry is whatever the test says. */
    static class Fixed extends Strategy9 {
        LocalDate expiry;
        Fixed() { super(null); }
        @Override protected LocalDate expiryFor(RuleContext ctx, LocalDate day) { return expiry; }
    }

    private final Fixed strategy = new Fixed();

    @AfterEach
    void tearDown() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.strikeMarketDataTick.clear();
        SharedData.marketDataByInstrumentAndInterval.clear();
    }

    // ------------------------------------------------------------ fixtures

    private static MarketData bar(LocalDateTime ts, double close, long volume) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(BigDecimal.valueOf(close + 1)); c.setHigh(BigDecimal.valueOf(close + 2));
        c.setLow(BigDecimal.valueOf(close - 2)); c.setClose(BigDecimal.valueOf(close));
        c.setVolume(volume);
        return c;
    }

    /** Falling premium, 25 bars yesterday + {@code todayBars} today, ±2 around each close, volume 100 per bar. */
    private static List<MarketData> series(double start, int todayBars) {
        List<MarketData> out = new ArrayList<>();
        for (int i = 0; i < 25; i++) out.add(bar(DAY.minusDays(1).plusMinutes(15L * i), start - 2.0 * i, 100));
        for (int i = 0; i < todayBars; i++) out.add(bar(DAY.plusMinutes(15L * i), start - 2.0 * (25 + i), 100));
        return out;
    }

    private static List<MarketData> spot(double firstClose) {
        List<MarketData> out = new ArrayList<>();
        for (int i = 0; i < 8; i++) out.add(bar(DAY.plusMinutes(15L * i), firstClose + i, 0));
        return out;
    }

    private RuleContext ctx(List<MarketData> s, int index) {
        MarketData c = s.get(index);
        return new RuleContext(c, index, s, 50, null, c.getTimestamp().plusMinutes(15), CLOSE_SIGNAL, KEY_CE);
    }

    private static final int SIGNAL = 25 + 4;   // today's 10:15 bar

    /** Caches for a volume-gate scenario: signal-bar volume {@code v} on the CE leg and on the PE leg. */
    private List<MarketData> cachesWithSignalVolume(long v) {
        List<MarketData> ce = series(200, 8); ce.get(SIGNAL).setVolume(v);
        List<MarketData> pe = series(180, 8); pe.get(SIGNAL).setVolume(v);
        List<MarketData> far = series(90, 8); far.get(SIGNAL).setVolume(100_000L);   // 24500: outside ±200, ignored
        SharedData.strikeMarketDataByInstrumentAndInterval.put(KEY_CE, ce);
        SharedData.strikeMarketDataByInstrumentAndInterval.put(KEY_CE_DUP, ce);     // same leg, other depth: counted once
        SharedData.strikeMarketDataByInstrumentAndInterval.put(KEY_PE, pe);
        SharedData.strikeMarketDataByInstrumentAndInterval.put(KEY_FAR, far);
        SharedData.marketDataByInstrumentAndInterval.put(TOKEN + "|15minute", spot(24010));   // session-open ATM 24000
        return ce;
    }

    private TradeAction decide(RuleContext ctx) {
        return strategy.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50)).action();
    }

    // ------------------------------------------------------------ gates

    @Test
    @DisplayName("all thresholds null → trades exactly as Strategy 8")
    void allOffIsStrategy8() {
        strategy.useSettings(new Strategy9.GateSettings(null, null, null));
        List<MarketData> s = cachesWithSignalVolume(100_000);   // spike, candle on its low, 1 DTE — all ignored
        s.get(SIGNAL).setLow(s.get(SIGNAL).getClose()); strategy.expiry = DAY.toLocalDate().plusDays(1);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);
        assertThat(strategy.getId()).isEqualTo(9);
    }

    @Test
    @DisplayName("candle gate: a close on the low is blocked, half-way up the range passes, a doji cannot be judged")
    void candleGate() {
        strategy.useSettings(new Strategy9.GateSettings(null, new BigDecimal("0.25"), null));
        List<MarketData> s = series(200, 8);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);          // close half-way: 0.5
        s.get(SIGNAL).setLow(s.get(SIGNAL).getClose());                           // close == low: 0.0
        assertThat(Strategy9.closePositionInRange(s.get(SIGNAL))).isEqualTo(0.0);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.NONE);
        s.get(SIGNAL).setHigh(s.get(SIGNAL).getClose());                          // doji: high == low
        assertThat(Strategy9.closePositionInRange(s.get(SIGNAL))).isNull();
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("volume gate: a 10× near-ATM spike blocks, 1.5× passes, the far strike and the duplicate key do not count")
    void volumeGate() {
        strategy.useSettings(new Strategy9.GateSettings(new BigDecimal("2.00"), null, null));
        List<MarketData> s = cachesWithSignalVolume(1000);   // (1000 + 1000) / median(100 + 100) = 10
        assertThat(strategy.nearAtmVolumeSurge(ctx(s, SIGNAL))).isEqualTo(10.0);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.NONE);
        s = cachesWithSignalVolume(150);                     // 1.5
        assertThat(strategy.nearAtmVolumeSurge(ctx(s, SIGNAL))).isEqualTo(1.5);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("volume gate cannot be judged without the underlying's session, with too little history, or on a zero median → allows")
    void volumeGateUnknownAllows() {
        strategy.useSettings(new Strategy9.GateSettings(new BigDecimal("2.00"), null, null));
        List<MarketData> s = cachesWithSignalVolume(1000);
        SharedData.marketDataByInstrumentAndInterval.clear();                     // no spot series
        assertThat(strategy.nearAtmVolumeSurge(ctx(s, SIGNAL))).isNull();
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);
        s = cachesWithSignalVolume(1000);
        for (List<MarketData> leg : SharedData.strikeMarketDataByInstrumentAndInterval.values()) {
            for (int i = 0; i < SIGNAL; i++) leg.get(i).setVolume(0L);          // zero median across every leg
        }
        assertThat(strategy.nearAtmVolumeSurge(ctx(s, SIGNAL))).isNull();
        s = cachesWithSignalVolume(1000);
        List<MarketData> shortSeries = new ArrayList<>(s.subList(SIGNAL - 5, SIGNAL + 1));  // 5 prior bars only
        RuleContext ctx = new RuleContext(shortSeries.get(5), 5, shortSeries, 50, null,
                shortSeries.get(5).getTimestamp().plusMinutes(15), CLOSE_SIGNAL, KEY_CE);
        assertThat(strategy.nearAtmVolumeSurge(ctx)).isNull();
    }

    @Test
    @DisplayName("expiry gate: 1 day left is blocked at min 2, 3 days pass, unknown expiry passes")
    void expiryGate() {
        strategy.useSettings(new Strategy9.GateSettings(null, null, 2));
        List<MarketData> s = series(200, 8);
        strategy.expiry = DAY.toLocalDate().plusDays(1);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.NONE);
        strategy.expiry = DAY.toLocalDate().plusDays(3);
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);
        strategy.expiry = null;
        assertThat(decide(ctx(s, SIGNAL))).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("no repository → all gates off (hand-built strategy), and the close-time exit is untouched")
    void noRepositoryOffAndExitUntouched() {
        List<MarketData> s = series(200, 25);
        s.get(25 + 24).setLow(s.get(25 + 24).getClose());
        assertThat(strategy.settingsFor(DAY.toLocalDate())).isEqualTo(Strategy9.GateSettings.OFF);
        assertThat(decide(ctx(s, 25 + 24))).isEqualTo(TradeAction.BUY);   // 15:15 bar
    }
}
