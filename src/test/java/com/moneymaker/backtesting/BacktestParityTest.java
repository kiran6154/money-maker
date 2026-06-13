package com.moneymaker.backtesting;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Golden-master parity test for the backtest pipeline.
 *
 * <h3>M0.1 + M0.1.5 — current state</h3>
 * <ul>
 *   <li>Spring context boots against H2 in MySQL-compat mode (see
 *       {@code application-test.properties}).</li>
 *   <li>Liquibase runs against H2; failures here indicate a changeset that
 *       isn't portable.</li>
 *   <li>The original {@code canary_must_fail()} test was removed in M0.1.5
 *       once the broader test suite (~100 tests across 11 files) provided
 *       sufficient proof the harness can report failures.</li>
 * </ul>
 *
 * <h3>What lands later</h3>
 * <ul>
 *   <li><b>M0.2</b> — {@code MarketDataCaptureCli} + six fixture date files.</li>
 *   <li><b>M0.3</b> — the seven scenario tests in diagnostic mode (log diffs,
 *       no assertions).</li>
 *   <li><b>M1</b> — reproducibility fixes so diagnostic snapshots are stable
 *       across consecutive runs.</li>
 *   <li><b>M2</b> — golden expected JSON committed; {@code assertEquals}
 *       turned on; this class becomes <b>load-bearing</b> (every PR must
 *       keep it green; intentional behaviour changes require the matching
 *       expected fixture to be regenerated in the same commit with
 *       justification in the message).</li>
 * </ul>
 */
@SpringBootTest
@ActiveProfiles("test")
class BacktestParityTest {

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
