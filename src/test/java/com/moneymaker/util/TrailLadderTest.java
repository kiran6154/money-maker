package com.moneymaker.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * Pins the {@code trade_config.trail_ladder} contract.
 *
 * <p>The ladder decides where a winning trade exits, and it does so only on the
 * minority of trades that get far enough to reach a rung — the ones nobody is
 * watching tick by tick. So the failure mode this class guards against is not a
 * crash but a silently wrong floor: a dropped rung, a ladder that loosens as the
 * trade improves, or a rung that closes the trade the instant it arms.</p>
 */
class TrailLadderTest {

    private static BigDecimal bd(String v) {
        return new BigDecimal(v);
    }

    @Test
    @DisplayName("parses the canonical form into ascending rungs")
    void parsesCanonical() {
        List<TrailLadder.Rung> rungs = TrailLadder.parse("25:2,50:25,75:50");

        assertThat(rungs).hasSize(3);
        assertThat(rungs.get(0).trigger()).isEqualByComparingTo("25");
        assertThat(rungs.get(0).lock()).isEqualByComparingTo("2");
        assertThat(rungs.get(2).trigger()).isEqualByComparingTo("75");
        assertThat(rungs.get(2).lock()).isEqualByComparingTo("50");
    }

    @Test
    @DisplayName("blank and null mean no trailing, not an error")
    void blankMeansNoTrailing() {
        // Callers read empty as "fixed stop only", which is the pre-036 behaviour
        // every config had. It must not throw — most rows legitimately have none.
        assertThat(TrailLadder.parse(null)).isEmpty();
        assertThat(TrailLadder.parse("")).isEmpty();
        assertThat(TrailLadder.parse("   ")).isEmpty();
        assertThat(TrailLadder.canonical(null)).isNull();
    }

    @Test
    @DisplayName("tolerates whitespace and stray separators typed by hand")
    void tolerantOfHandEditing() {
        assertThat(TrailLadder.canonical(" 25 : 2 , 50:25 ,")).isEqualTo("25:2,50:25");
    }

    @Test
    @DisplayName("canonical strips trailing zeros so a round-trip reads as typed")
    void canonicalStripsZeros() {
        // DECIMAL(12,4) reads back as 25.0000; the column should not accumulate
        // that noise every time a config is saved.
        assertThat(TrailLadder.canonical("25.0000:2.0000")).isEqualTo("25:2");
    }

    @Test
    @DisplayName("rejects a rung that locks ABOVE its own trigger")
    void rejectsLockAboveTrigger() {
        // The floor would sit above the peak that armed it, so the trade would
        // exit at a P&L it has never reached. Not a trailing stop under any
        // reading.
        assertThatThrownBy(() -> TrailLadder.parse("25:30"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("locks above its own trigger");
    }

    @Test
    @DisplayName("ACCEPTS lock == trigger — a give-back trail, not a take-profit")
    void acceptsLockEqualToTrigger() {
        // This used to be rejected on the grounds that "the trade would exit the
        // moment the rung arms". That was wrong about this codebase:
        // PositionService.handleOne arms rungs AFTER its breach check, so the bar
        // whose excursion earns the rung cannot also exit on it, and the earliest
        // a lock == trigger floor can fire is the next bar.
        //
        // The distinction from target_at_entry is real: a target books +25 on the
        // way UP, this books +25 only on the way BACK DOWN from a higher peak. A
        // trade that runs to +60 and retraces exits here at +25 having reached
        // +60; on a target it would have exited at +25 without ever seeing it.
        //
        // Required by the Pressure strategy's "arm at +25, exit on a fall back to
        // +25" trail. See docs/PRESSURE_STRATEGY.md.
        List<TrailLadder.Rung> rungs = TrailLadder.parse("25:25");
        assertThat(rungs).hasSize(1);
        assertThat(rungs.get(0).trigger()).isEqualByComparingTo("25");
        assertThat(rungs.get(0).lock()).isEqualByComparingTo("25");

        // And it resolves as a floor once the peak reaches it.
        assertThat(TrailLadder.lockFor("25:25", new java.math.BigDecimal("25"))).isEqualByComparingTo("25");
        assertThat(TrailLadder.lockFor("25:25", new java.math.BigDecimal("60"))).isEqualByComparingTo("25");
        assertThat(TrailLadder.lockFor("25:25", new java.math.BigDecimal("24"))).isNull();
    }

    @Test
    @DisplayName("rejects descending triggers")
    void rejectsDescendingTriggers() {
        assertThatThrownBy(() -> TrailLadder.parse("50:25,25:2"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must ascend");
    }

    @Test
    @DisplayName("rejects a ladder that loosens as the trade improves")
    void rejectsLooseningLock() {
        // A ratchet cannot go backwards: locking less at 75 than at 50 would drop
        // the floor precisely as the trade got better.
        assertThatThrownBy(() -> TrailLadder.parse("50:25,75:10"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must not decrease");
    }

    @Test
    @DisplayName("rejects malformed rungs rather than skipping them")
    void rejectsMalformed() {
        // Deliberately unlike StrategyIds, which skips bad fragments: a dropped
        // strategy id stops trades visibly, a dropped rung changes exits invisibly.
        assertThatThrownBy(() -> TrailLadder.parse("25:2,abc"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> TrailLadder.parse("25:2,50:xyz"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("non-numeric");
        assertThatThrownBy(() -> TrailLadder.parse("25"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("trigger:lock");
        assertThatThrownBy(() -> TrailLadder.parse("0:-5"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("non-positive trigger");
    }

    @Test
    @DisplayName("a negative lock is legal — tightening a stop while still red")
    void negativeLockIsLegal() {
        // "20:-30" on a 60-point stop halves the risk once the trade has shown
        // 20 points of profit but before it is safe. That is risk reduction, not
        // profit protection, and there is no reason to forbid it.
        assertThatCode(() -> TrailLadder.parse("20:-30,50:25")).doesNotThrowAnyException();
        assertThat(TrailLadder.lockFor("20:-30,50:25", bd("30"))).isEqualByComparingTo("-30");
    }

    @Test
    @DisplayName("no rung reached yields null, not zero")
    void noRungYieldsNull() {
        // Null is what tells PositionService the fixed stop still owns the trade.
        // Zero would be a floor at breakeven and would close trades on its own.
        assertThat(TrailLadder.lockFor("25:2,50:25", bd("24.99"))).isNull();
        assertThat(TrailLadder.lockFor("25:2,50:25", BigDecimal.ZERO)).isNull();
        assertThat(TrailLadder.lockFor("25:2,50:25", bd("-10"))).isNull();
        assertThat(TrailLadder.lockFor("25:2", null)).isNull();
    }

    @Test
    @DisplayName("a rung arms exactly at its trigger")
    void armsAtTrigger() {
        assertThat(TrailLadder.lockFor("25:2,50:25", bd("25"))).isEqualByComparingTo("2");
        assertThat(TrailLadder.lockFor("25:2,50:25", bd("50"))).isEqualByComparingTo("25");
    }

    @Test
    @DisplayName("a jump past several rungs lands on the highest one reached")
    void jumpLandsOnHighestRung() {
        // A candle can gap from +5 to +80. The ladder must not walk one rung per
        // tick — the floor the trade earned is the +50 one, immediately.
        assertThat(TrailLadder.lockFor("25:2,50:25,75:50,100:75", bd("80")))
                .isEqualByComparingTo("50");
        assertThat(TrailLadder.lockFor("25:2,50:25,75:50,100:75", bd("500")))
                .isEqualByComparingTo("75");
    }
}
