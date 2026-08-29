package com.moneymaker.market.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.time.DayOfWeek;
import java.time.LocalDate;

/**
 * Mon–Fri. The default calendar, and the one the broker data source keeps using.
 *
 * <p>It does not know about market holidays or special sessions, which is why
 * {@link HistoricalTradingCalendar} takes over whenever imported data is
 * available to answer the question properly. Registered with
 * {@code matchIfMissing = true} so it is present unless the historical source is
 * active — mirroring how {@code ZerodhaMarketDataProvider} defaults.
 */
@Slf4j
@Service
@ConditionalOnProperty(name = "backtest.data-source", havingValue = "BROKER", matchIfMissing = true)
public class WeekdayTradingCalendar implements TradingCalendar {

    public static final String NAME = "WEEKDAY";

    public WeekdayTradingCalendar() {
        log.info("TradingCalendar: {} (Mon-Fri; market holidays are not known to this calendar)", NAME);
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public boolean isTradingDay(LocalDate date) {
        if (date == null) {
            return false;
        }
        DayOfWeek day = date.getDayOfWeek();
        return day != DayOfWeek.SATURDAY && day != DayOfWeek.SUNDAY;
    }

    @Override
    public LocalDate nextTradingDay(LocalDate date) {
        if (date == null) {
            return null;
        }
        LocalDate next = date.plusDays(1);
        while (!isTradingDay(next)) {
            next = next.plusDays(1);
        }
        return next;
    }
}
