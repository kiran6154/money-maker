package com.moneymaker.repository;

import com.moneymaker.entity.ExpiryDates;
import com.moneymaker.entity.Instrument;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

@Repository
public interface ExpiryDatesRepository extends JpaRepository<ExpiryDates, Integer> {

    Optional<ExpiryDates> findFirstByInstrumentAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(
            Instrument instrument,
            LocalDate expiryDate
    );

    List<ExpiryDates> findByInstrumentAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(
            Instrument instrument,
            LocalDate expiryDate
    );

    /**
     * Future expiries across every instrument. The future chart resolver can
     * use this when no symbol/index discriminator exists on expiry_dates and
     * it needs to apply weekday rules (Tuesday for NIFTY, Wednesday for
     * BANKNIFTY) itself.
     */
    List<ExpiryDates> findByExpiryDateGreaterThanEqualOrderByExpiryDateAsc(
            LocalDate expiryDate
    );

    List<ExpiryDates> findByInstrumentAndExpiryDateBetween(
            Instrument instrument,
            LocalDate from,
            LocalDate to
    );
}
