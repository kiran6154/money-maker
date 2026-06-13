package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.shared.data.SharedData;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for {@link Strategy1}.
 *
 * <p>Strategy1 reads from the static {@link SharedData} maps and writes
 * signals into {@link SharedData#tradeSignals}. Tests carefully wipe both
 * before and after each test so static state from one case can't leak into
 * the next (relevant given M0's reproducibility findings).
 *
 * <p>Coverage:
 * <ol>
 *   <li>{@code getId} returns 1.</li>
 *   <li>Empty / null / no-timeframes inputs short-circuit cleanly.</li>
 *   <li>SELL gate fires when {@code open > sma > close} on a CE config with
 *       a downtrending SMA50.</li>
 *   <li>Cache-key filtering: signals only fire for the configured
 *       instrument-token + interval.</li>
 *   <li>Strike scan order: CE = ascending strike, PE = descending strike
 *       (the determinism fix in the impl that prevents "different strike each
 *       run" — pin via the order of {@code SharedData.tradeSignals}).</li>
 * </ol>
 */
class Strategy1Test {

    private final Strategy1 strategy = new Strategy1();

    @BeforeEach
    void wipeSharedState() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.tradeSignals.clear();
    }

    @AfterEach
    void cleanup() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.tradeSignals.clear();
    }

    @Test
    void id_is_1() {
        assertThat(strategy.getId()).isEqualTo(1);
    }

    @Test
    void execute_with_null_config_is_safe() {
        strategy.execute(null);
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void execute_with_no_shared_data_short_circuits() {
        TradeConfigCombinedDTO config = ceConfig(50);
        strategy.execute(config);
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void execute_with_no_timeframes_short_circuits() {
        TradeConfigCombinedDTO config = ceConfig(50);
        config.setTimeframes(List.of());
        // Even if shared data is populated:
        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "5minute", "CE", 24000, "100", 0, 0),
                List.of(triggerSellCandle()));
        strategy.execute(config);
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void emits_SELL_signal_when_sellGate_passes_and_downtrending() {
        // Single-candle list — first candle of day → isSma50DownTrending = true
        // when SMA50 is set. Open > sma > close → sellGate true.
        TradeConfigCombinedDTO config = ceConfig(50);

        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "5minute", "CE", 24000, "100", 0, 0),
                List.of(triggerSellCandle()));

        strategy.execute(config);

        assertThat(SharedData.tradeSignals).hasSize(1);
        TradeSignal signal = SharedData.tradeSignals.poll();
        assertThat(signal.getAction()).isEqualTo(TradeAction.SELL);
        assertThat(signal.getTradeConfigId()).isEqualTo(config.getTradeConfig().getId());
        assertThat(signal.getPrimarySma()).isEqualTo(50);
        assertThat(signal.getInterval()).isEqualTo("5minute");
        assertThat(signal.getStrikeKey()).contains("|CE|24000|");
    }

    @Test
    void does_not_emit_signal_when_instrument_token_does_not_match() {
        TradeConfigCombinedDTO config = ceConfig(50);  // configured for "256265"

        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                // Wrong instrument token.
                cacheKey("999999", "5minute", "CE", 24000, "100", 0, 0),
                List.of(triggerSellCandle()));

        strategy.execute(config);
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void does_not_emit_signal_when_interval_does_not_match() {
        TradeConfigCombinedDTO config = ceConfig(50);  // 5-minute timeframe

        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "15minute", "CE", 24000, "100", 0, 0),
                List.of(triggerSellCandle()));

        strategy.execute(config);
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void CE_config_scans_strikes_in_ascending_order() {
        // Put two strikes in the cache; both should fire. The signal queue
        // order must reflect ascending strike (most-ITM-first for CE).
        TradeConfigCombinedDTO config = ceConfig(50);

        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "5minute", "CE", 24200, "200", 0, 0),
                List.of(triggerSellCandle()));
        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "5minute", "CE", 24000, "100", 0, 0),
                List.of(triggerSellCandle()));

        strategy.execute(config);

        assertThat(SharedData.tradeSignals).hasSize(2);
        TradeSignal first  = SharedData.tradeSignals.poll();
        TradeSignal second = SharedData.tradeSignals.poll();
        assertThat(first.getStrikeKey()).contains("|24000|");   // lower strike first
        assertThat(second.getStrikeKey()).contains("|24200|");
    }

    @Test
    void PE_config_scans_strikes_in_descending_order() {
        TradeConfigCombinedDTO config = peConfig(50);

        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "5minute", "PE", 24000, "100", 0, 0),
                List.of(triggerSellCandle()));
        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                cacheKey("256265", "5minute", "PE", 24200, "200", 0, 0),
                List.of(triggerSellCandle()));

        strategy.execute(config);

        assertThat(SharedData.tradeSignals).hasSize(2);
        TradeSignal first  = SharedData.tradeSignals.poll();
        TradeSignal second = SharedData.tradeSignals.poll();
        assertThat(first.getStrikeKey()).contains("|24200|");   // higher strike first for PE
        assertThat(second.getStrikeKey()).contains("|24000|");
    }

    /* ---------------- helpers ---------------- */

    private static TradeConfigCombinedDTO ceConfig(int sma) {
        return buildConfig("CE", sma);
    }

    private static TradeConfigCombinedDTO peConfig(int sma) {
        return buildConfig("PE", sma);
    }

    private static TradeConfigCombinedDTO buildConfig(String side, int sma) {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();

        TradeConfig tc = new TradeConfig();
        tc.setId(1);
        tc.setTradingSide(side);
        tc.setTransactionType("SELL");
        dto.setTradeConfig(tc);

        Instrument ins = new Instrument();
        ins.setInsName("NIFTY");
        dto.setInstrument(ins);

        InstrumentDetails details = new InstrumentDetails();
        details.setInstrumentToken(256265);  // NIFTY index token
        dto.setInstrumentDetails(details);

        SmaTimeframe tf = new SmaTimeframe();
        tf.setTimePeriod(5);
        tf.setSma(sma);
        dto.setTimeframes(List.of(tf));

        return dto;
    }

    /**
     * Single candle whose OHLC + SMA50 cause:
     * - sellGate (open > sma50 > close)
     * - first-of-day → isSma50DownTrending=true (so sellRulesFor50 passes)
     */
    private static MarketData triggerSellCandle() {
        MarketData c = new MarketData();
        c.setTimestamp(LocalDateTime.of(2026, 4, 1, 10, 30));
        c.setOpen(BigDecimal.valueOf(110));
        c.setHigh(BigDecimal.valueOf(115));
        c.setLow(BigDecimal.valueOf(90));
        c.setClose(BigDecimal.valueOf(95));    // close < sma < open → sellGate
        c.setSmaValue50(100.0);
        c.setInstrumenttoken("CANDLE-TOKEN");
        return c;
    }

    /** Key shape matches AnalysisScheduler.toStrikeMarketDataKey. */
    private static String cacheKey(String instrumentToken, String interval, String optionType,
                                   int strike, String optionToken, int itm, int otm) {
        return instrumentToken + "|" + interval + "|" + optionType + "|" + strike + "|"
                + optionToken + "|" + itm + "|" + otm;
    }
}
