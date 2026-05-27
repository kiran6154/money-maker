package com.moneymaker.backtesting;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Golden-master parity test for the backtest pipeline.
 *
 * <h3>M0.1 scaffold — current state</h3>
 * <ul>
 *   <li>Spring context boots against H2 in MySQL-compat mode (see
 *       {@code application-test.properties}).</li>
 *   <li>Liquibase runs against H2; failures here indicate a changeset that
 *       isn't portable.</li>
 *   <li>A single deliberately-failing {@link #canary_must_fail()} test
 *       proves the test infrastructure can in fact report failures. Removed
 *       in M2 once real scenario assertions are turned on.</li>
 * </ul>
 *
 * <h3>What lands later</h3>
 * <ul>
 *   <li><b>M0.2</b> — {@code MarketDataCaptureCli} + six fixture date files.</li>
 *   <li><b>M0.3</b> — the seven scenario tests in diagnostic mode (log diffs,
 *       no assertions).</li>
 *   <li><b>M1</b> — reproducibility fixes so diagnostic snapshots are stable
 *       across consecutive runs.</li>
 *   <li><b>M2</b> — golden expected JSON committed; canary deleted;
 *       {@code assertEquals} turned on.</li>
 * </ul>
 *
 * <p>From M2 onwards this test is <b>load-bearing</b>: every PR must keep it
 * green; intentional behaviour changes require the matching expected fixture
 * to be regenerated in the same commit with justification in the message.
 */
@SpringBootTest
@ActiveProfiles("test")
class BacktestParityTest {

    /**
     * Deliberately failing test that proves the harness can report failures.
     * If this test ever <i>passes</i>, the assertion framework is mis-wired
     * and the rest of the suite cannot be trusted.
     *
     * <p>Removed in M2 once {@link #canary_must_fail} is replaced by real
     * scenario assertions.
     */
    @Test
    void canary_must_fail() {
        assertThat(1)
                .as("canary — must fail until M2; if this passes, the test infrastructure is broken")
                .isEqualTo(2);
    }

    /**
     * Proves the Spring context boots cleanly against the test datasource.
     * Liquibase migrations must succeed against H2 in MySQL-compat mode.
     * Failure here means a changeset used MySQL-only SQL.
     */
    @Test
    void spring_context_boots_against_h2() {
        // The @SpringBootTest annotation alone exercises context startup.
        // If we get here, Liquibase ran successfully against H2.
        assertThat(true).isTrue();
    }
}
