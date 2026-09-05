package com.moneymaker.repository;

import com.moneymaker.entity.HistoricalOptionCandle;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.data.domain.PageRequest;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Executes {@link HistoricalOptionCandleRepository#findRecentCandlesUpToForStrikes},
 * which backs the dashboard's averaged ATM±N panes.
 *
 * <p>{@code RepositoryQueryBootstrapTest} already proves the JPQL translates.
 * What it cannot prove is the part this query actually leans on: that
 * {@code strike_price IN :strikePrices} matches <b>numerically</b>. The column is
 * {@code DECIMAL(12,4)} and reads back as {@code 24450.0000}, while the ladder
 * the service builds carries plain {@code 24450}. Those are not
 * {@code BigDecimal.equals}-equal, so if the {@code IN} compared like Java does,
 * every averaged pane would come back empty and look like missing data.</p>
 */
@DataJpaTest(properties = {
        "spring.liquibase.enabled=false",
        "spring.jpa.hibernate.ddl-auto=create-drop",
        // application.properties pins the MySQL8 dialect for the real datasource.
        // Left in place here, Hibernate emits MySQL DDL at an H2 database, fails
        // to create a single table, and — since hbm2ddl does not halt on error —
        // hands the test an empty schema rather than a failure.
        "spring.jpa.database-platform=org.hibernate.dialect.H2Dialect"
})
class HistoricalOptionCandleStrikeLadderQueryTest {

    private static final String STOCK = "NIFTY";
    private static final String EXCHANGE = "NFO";
    private static final String RIGHT = "CE";
    private static final LocalDate EXPIRY = LocalDate.of(2024, 6, 13);
    private static final LocalDateTime OPEN = LocalDateTime.of(2024, 6, 6, 9, 15);

    @Autowired
    HistoricalOptionCandleRepository repository;

    @BeforeEach
    void seed() {
        repository.deleteAll();
        // Three strikes on the NIFTY grid, two bars each.
        for (String strike : List.of("24450", "24500", "24550")) {
            for (int bar = 0; bar < 2; bar++) {
                repository.save(candle(new BigDecimal(strike), OPEN.plusMinutes(5L * bar)));
            }
        }
        // A neighbour outside the ladder, to prove the IN really filters.
        repository.save(candle(new BigDecimal("24600"), OPEN));
        // A PE at an in-ladder strike, to prove option_right still applies.
        HistoricalOptionCandle pe = candle(new BigDecimal("24500"), OPEN);
        pe.setOptionRight("PE");
        repository.save(pe);
    }

    private HistoricalOptionCandle candle(BigDecimal strike, LocalDateTime at) {
        HistoricalOptionCandle candle = new HistoricalOptionCandle();
        candle.setStockCode(STOCK);
        candle.setExchangeCode(EXCHANGE);
        candle.setExpiryDate(EXPIRY);
        candle.setStrikePrice(strike);
        candle.setOptionRight(RIGHT);
        candle.setDateTime(at);
        candle.setOpen(new BigDecimal("100.00"));
        candle.setHigh(new BigDecimal("110.00"));
        candle.setLow(new BigDecimal("90.00"));
        candle.setClose(new BigDecimal("105.00"));
        return candle;
    }

    @Test
    @DisplayName("a scale-0 ladder matches the DECIMAL(12,4) strikes stored")
    void matchesAcrossScales() {
        List<BigDecimal> ladder = List.of(
                new BigDecimal("24450"), new BigDecimal("24500"), new BigDecimal("24550"));

        List<HistoricalOptionCandle> found = repository.findRecentCandlesUpToForStrikes(
                STOCK, EXCHANGE, EXPIRY, ladder, RIGHT, OPEN.plusHours(6), PageRequest.of(0, 100));

        // Three strikes x two bars. Had the IN compared the way
        // BigDecimal.equals does, this would be zero.
        assertThat(found).hasSize(6);
        assertThat(found).extracting(HistoricalOptionCandle::getStrikePrice)
                .allSatisfy(strike -> assertThat(strike).isNotEqualByComparingTo("24600"));
    }

    @Test
    @DisplayName("the ladder filters: a strike outside it and the other right are excluded")
    void filtersStrikeAndRight() {
        List<HistoricalOptionCandle> found = repository.findRecentCandlesUpToForStrikes(
                STOCK, EXCHANGE, EXPIRY, List.of(new BigDecimal("24500")),
                RIGHT, OPEN.plusHours(6), PageRequest.of(0, 100));

        assertThat(found).hasSize(2);
        assertThat(found).allSatisfy(candle -> {
            assertThat(candle.getStrikePrice()).isEqualByComparingTo("24500");
            assertThat(candle.getOptionRight()).isEqualTo(RIGHT);
        });
    }

    @Test
    @DisplayName("newest first, so the page keeps the most recent bars of the window")
    void ordersNewestFirst() {
        // Descending order is what makes the LIMIT keep the bars nearest the
        // selected date rather than the oldest ones in the table.
        List<HistoricalOptionCandle> found = repository.findRecentCandlesUpToForStrikes(
                STOCK, EXCHANGE, EXPIRY, List.of(new BigDecimal("24500")),
                RIGHT, OPEN.plusHours(6), PageRequest.of(0, 100));

        assertThat(found).extracting(HistoricalOptionCandle::getDateTime)
                .containsExactly(OPEN.plusMinutes(5), OPEN);
    }

    @Test
    @DisplayName("candles after the window's end are excluded")
    void respectsTheUpperBound() {
        List<HistoricalOptionCandle> found = repository.findRecentCandlesUpToForStrikes(
                STOCK, EXCHANGE, EXPIRY, List.of(new BigDecimal("24500")),
                RIGHT, OPEN, PageRequest.of(0, 100));

        assertThat(found).extracting(HistoricalOptionCandle::getDateTime).containsExactly(OPEN);
    }
}
