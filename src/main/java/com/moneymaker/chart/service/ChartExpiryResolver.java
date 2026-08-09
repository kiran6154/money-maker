package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.IndexSymbol;
import com.moneymaker.entity.ExpiryDates;
import com.moneymaker.repository.ExpiryDatesRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

/**
 * Resolves the nearest valid weekly expiry for the chart dashboard.
 *
 * <p>Current schema exposes no symbol/index discriminator on
 * {@code expiry_dates}, so the resolver reads future expiries and applies the
 * weekly weekday rule in-memory:
 * <ul>
 *   <li>NIFTY â†’ Tuesday</li>
 *   <li>BANKNIFTY â†’ Wednesday</li>
 * </ul>
 *
 * <p>If the schema later adds an index-specific discriminator, this class is
 * intentionally small so the repository call can be tightened without
 * affecting dashboard callers.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ChartExpiryResolver {

    private final ExpiryDatesRepository expiryDatesRepository;

    public Optional<LocalDate> resolve(LocalDate selectedDate, IndexSymbol indexSymbol) {
        if (selectedDate == null || indexSymbol == null) {
            return Optional.empty();
        }

        DayOfWeek targetWeekday = targetWeekday(indexSymbol);
        List<ExpiryDates> candidates = expiryDatesRepository
                .findByExpiryDateGreaterThanEqualOrderByExpiryDateAsc(selectedDate);

        return candidates.stream()
                .map(ExpiryDates::getExpiryDate)
                .filter(date -> date != null && date.getDayOfWeek() == targetWeekday)
                .findFirst()
                .or(() -> {
                    log.info("[chart-expiry] no {} expiry found on/after {}", indexSymbol, selectedDate);
                    return Optional.empty();
                });
    }

    private DayOfWeek targetWeekday(IndexSymbol indexSymbol) {
        return switch (indexSymbol) {
            case NIFTY -> DayOfWeek.TUESDAY;
            case BANKNIFTY -> DayOfWeek.WEDNESDAY;
        };
    }
}
