package com.moneymaker.backtesting.support;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Loads a SQL fixture file from the test classpath into the active datasource.
 *
 * <p>Each fixture is a complete .sql script — instrument rows, trade_config
 * rows, market_data rows, sma_timeframe rows. The loader splits on {@code ;}
 * and executes statements one at a time so a failing row in the middle of
 * a fixture is identifiable in the test output (vs. a single batch failure
 * that hides the offending statement).
 *
 * <p>Skeleton in PR M0.1 — used in M0.2 once fixtures are captured.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class FixtureLoader {

    private final JdbcTemplate jdbcTemplate;

    /**
     * Loads a single .sql fixture file from {@code src/test/resources/fixtures/}.
     * @param classpathLocation path relative to classpath, e.g. {@code fixtures/data/configs.sql}
     */
    public void load(String classpathLocation) {
        ClassPathResource resource = new ClassPathResource(classpathLocation);
        String script;
        try {
            script = new String(resource.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read fixture: " + classpathLocation, e);
        }

        int stmtNum = 0;
        for (String raw : script.split(";")) {
            String stmt = stripComments(raw).trim();
            if (stmt.isEmpty()) continue;
            stmtNum++;
            try {
                jdbcTemplate.execute(stmt);
            } catch (RuntimeException ex) {
                throw new IllegalStateException(
                        "Fixture " + classpathLocation + " statement #" + stmtNum + " failed: " + stmt, ex);
            }
        }
        log.info("[fixture] loaded {} ({} statements)", classpathLocation, stmtNum);
    }

    /**
     * Strips {@code --} line comments. SQL block comments {@code /* ... &#42;/}
     * are left intact — Liquibase is the only writer that uses those and we
     * don't run Liquibase scripts through this loader.
     */
    private static String stripComments(String sql) {
        StringBuilder out = new StringBuilder(sql.length());
        for (String line : sql.split("\\r?\\n")) {
            int dashIdx = line.indexOf("--");
            out.append(dashIdx >= 0 ? line.substring(0, dashIdx) : line).append('\n');
        }
        return out.toString();
    }
}
