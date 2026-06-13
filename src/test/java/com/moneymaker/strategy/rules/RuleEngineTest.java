package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for {@link RuleEngine}. The orchestrator that combines the
 * SMA-cross gate with strategy-supplied {@link TradeRules}. The decision
 * matrix is small but every cell matters for live trading.
 */
class RuleEngineTest {

    @Nested
    class ResolvePrimarySmaPeriod {

        @Test
        void returns_first_non_null_sma_from_timeframes() {
            TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
            SmaTimeframe tf1 = new SmaTimeframe();
            tf1.setSma(null);
            SmaTimeframe tf2 = new SmaTimeframe();
            tf2.setSma(50);
            SmaTimeframe tf3 = new SmaTimeframe();
            tf3.setSma(200);
            dto.setTimeframes(List.of(tf1, tf2, tf3));

            assertThat(RuleEngine.resolvePrimarySmaPeriod(dto)).isEqualTo(50);
        }

        @Test
        void returns_null_for_null_config() {
            assertThat(RuleEngine.resolvePrimarySmaPeriod(null)).isNull();
        }

        @Test
        void returns_null_when_timeframes_list_is_null() {
            TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
            // timeframes left null
            assertThat(RuleEngine.resolvePrimarySmaPeriod(dto)).isNull();
        }

        @Test
        void returns_null_when_all_timeframes_have_null_sma() {
            TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
            SmaTimeframe tf = new SmaTimeframe();
            tf.setSma(null);
            dto.setTimeframes(List.of(tf));
            assertThat(RuleEngine.resolvePrimarySmaPeriod(dto)).isNull();
        }

        @Test
        void tolerates_null_entries_in_list() {
            TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
            SmaTimeframe tf = new SmaTimeframe();
            tf.setSma(100);
            List<SmaTimeframe> list = new ArrayList<>();
            list.add(null);
            list.add(tf);
            dto.setTimeframes(list);
            assertThat(RuleEngine.resolvePrimarySmaPeriod(dto)).isEqualTo(100);
        }
    }

    @Nested
    class Decide {

        @Test
        void NONE_when_primary_sma_period_is_null() {
            MarketData c = candle(100, 99);
            RuleContext ctx = new RuleContext(c, 0, List.of(c), null, new TradeConfigCombinedDTO());
            RuleEngine.Decision d = RuleEngine.decide(ctx, TradeRules.empty(), TradeRules.empty());
            assertThat(d.action()).isEqualTo(TradeAction.NONE);
            assertThat(d.reason()).contains("primarySma=null");
        }

        @Test
        void NONE_when_sma_value_is_unavailable() {
            MarketData c = candle(100, 99);
            // SMA fields all null → smaValue returns 0 → "<= 0" → "N/A".
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, new TradeConfigCombinedDTO());
            RuleEngine.Decision d = RuleEngine.decide(ctx, TradeRules.empty(), TradeRules.empty());
            assertThat(d.action()).isEqualTo(TradeAction.NONE);
            assertThat(d.reason()).contains("sma50=N/A");
        }

        @Test
        void SELL_when_sellGate_passes_and_sell_rules_pass() {
            // open > sma > close — sellGate triggers.
            MarketData c = candle(110, 95);
            c.setSmaValue50(100.0);
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, new TradeConfigCombinedDTO());
            // Empty rules = pass.
            RuleEngine.Decision d = RuleEngine.decide(ctx, TradeRules.empty(), TradeRules.empty());
            assertThat(d.action()).isEqualTo(TradeAction.SELL);
            assertThat(d.reason()).contains("sellGate=true").contains("OK");
        }

        @Test
        void NONE_when_sellGate_passes_but_sell_rules_fail() {
            MarketData c = candle(110, 95);
            c.setSmaValue50(100.0);
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, new TradeConfigCombinedDTO());
            TradeRules failingSell = new TradeRules(
                    List.of(TradeRule.named("always-false", x -> false)),
                    List.of());
            RuleEngine.Decision d = RuleEngine.decide(ctx, failingSell, TradeRules.empty());
            assertThat(d.action()).isEqualTo(TradeAction.NONE);
            assertThat(d.reason()).contains("sellGate=true").contains("FAIL").contains("always-false");
        }

        @Test
        void BUY_when_sellGate_fails_and_buy_rules_pass() {
            // sellGate requires open > sma > close. Use open == close = sma → sellGate false.
            MarketData c = candle(100, 100);
            c.setSmaValue50(100.0);
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, new TradeConfigCombinedDTO());
            // Empty buy rules = pass.
            RuleEngine.Decision d = RuleEngine.decide(ctx, TradeRules.empty(), TradeRules.empty());
            assertThat(d.action()).isEqualTo(TradeAction.BUY);
            assertThat(d.reason()).contains("sellGate=false").contains("rawBuyGate").contains("OK");
        }

        @Test
        void NONE_when_sellGate_fails_and_buy_rules_fail() {
            MarketData c = candle(100, 100);
            c.setSmaValue50(100.0);
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, new TradeConfigCombinedDTO());
            TradeRules failingBuy = new TradeRules(
                    List.of(TradeRule.named("always-false", x -> false)),
                    List.of());
            RuleEngine.Decision d = RuleEngine.decide(ctx, TradeRules.empty(), failingBuy);
            assertThat(d.action()).isEqualTo(TradeAction.NONE);
            assertThat(d.reason()).contains("FAIL");
        }
    }

    @Nested
    class Evaluate {

        @Test
        void null_rules_returns_true() {
            assertThat(RuleEngine.evaluate(ctx(), null)).isTrue();
        }

        @Test
        void fully_empty_rules_returns_true() {
            assertThat(RuleEngine.evaluate(ctx(), TradeRules.empty())).isTrue();
        }

        @Test
        void all_required_passing_with_no_anyOf_returns_true() {
            TradeRules r = new TradeRules(
                    List.of(TradeRule.named("a", x -> true), TradeRule.named("b", x -> true)),
                    List.of());
            assertThat(RuleEngine.evaluate(ctx(), r)).isTrue();
        }

        @Test
        void any_failing_required_returns_false() {
            TradeRules r = new TradeRules(
                    List.of(TradeRule.named("ok", x -> true), TradeRule.named("fail", x -> false)),
                    List.of());
            assertThat(RuleEngine.evaluate(ctx(), r)).isFalse();
        }

        @Test
        void required_pass_plus_one_anyOf_pass_returns_true() {
            TradeRules r = new TradeRules(
                    List.of(TradeRule.named("ok", x -> true)),
                    List.of(TradeRule.named("a", x -> false),
                            TradeRule.named("b", x -> true)));
            assertThat(RuleEngine.evaluate(ctx(), r)).isTrue();
        }

        @Test
        void required_pass_plus_all_anyOf_fail_returns_false() {
            TradeRules r = new TradeRules(
                    List.of(TradeRule.named("ok", x -> true)),
                    List.of(TradeRule.named("a", x -> false),
                            TradeRule.named("b", x -> false)));
            assertThat(RuleEngine.evaluate(ctx(), r)).isFalse();
        }
    }

    /* ---------------- helpers ---------------- */

    private static RuleContext ctx() {
        MarketData c = candle(0, 0);
        return new RuleContext(c, 0, List.of(c), 50, new TradeConfigCombinedDTO());
    }

    private static MarketData candle(double open, double close) {
        MarketData c = new MarketData();
        c.setOpen(BigDecimal.valueOf(open));
        c.setClose(BigDecimal.valueOf(close));
        c.setHigh(BigDecimal.valueOf(Math.max(open, close)));
        c.setLow(BigDecimal.valueOf(Math.min(open, close)));
        c.setTimestamp(LocalDateTime.of(2026, 4, 1, 9, 30));
        c.setInstrumenttoken("TEST");
        return c;
    }
}
