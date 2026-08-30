package com.moneymaker.repository;

import com.moneymaker.entity.ChargeRate;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;

@Repository
public interface ChargeRateRepository extends JpaRepository<ChargeRate, Integer> {

    /**
     * Every rate row for a segment that had come into force on or before
     * {@code asOf}, newest first.
     *
     * <p>Returns all of them rather than one per type because "the rate in force"
     * is the first row per {@code charge_type} in this ordering — resolving that
     * in memory keeps it to a single query for a whole ledger's worth of trades.
     */
    @Query("""
        SELECT r
        FROM ChargeRate r
        WHERE r.segment = :segment
          AND r.effectiveFrom <= :asOf
        ORDER BY r.chargeType ASC, r.effectiveFrom DESC
    """)
    List<ChargeRate> findInForce(@Param("segment") String segment, @Param("asOf") LocalDate asOf);

    /** All rows, used to build the date-keyed resolver once per request. */
    List<ChargeRate> findBySegmentOrderByChargeTypeAscEffectiveFromAsc(String segment);
}
