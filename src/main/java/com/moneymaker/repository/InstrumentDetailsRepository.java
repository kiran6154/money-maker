package com.moneymaker.repository;

import com.moneymaker.entity.InstrumentDetails;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

@Repository
public interface InstrumentDetailsRepository extends JpaRepository<InstrumentDetails, Integer> {

    List<InstrumentDetails> findByStrikeAndInstrumentTypeOrderByExpiryAsc(BigDecimal strike, String instrumentType);

    Optional<InstrumentDetails> findByTradingSymbol(String tradingSymbol);

    /**
     * Looks up the option-leg row for a given underlying + expiry + strike + type.
     *
     * <p>Uses {@code LIKE '<symbol>%'} (prefix match), not {@code '%<symbol>%'}.
     * The substring variant accidentally matched sibling indices —
     * {@code 'NIFTY'} would catch {@code BANKNIFTY...}, {@code FINNIFTY...},
     * {@code MIDCPNIFTY...} too — producing 2+ rows on a shared expiry/strike
     * and blowing up {@code Optional.uniqueResult()}.
     *
     * <p>Returns a list (still expected to be size 1 in normal data) so the
     * caller can defensively log and pick the first match if anything else
     * sneaks through (e.g. the same symbol listed on two exchanges).
     */
    @Query("""
        SELECT i
        FROM InstrumentDetails i
        WHERE LOWER(i.tradingSymbol) LIKE LOWER(CONCAT(:symbol, '%'))
          AND i.expiry = :expiry
          AND i.strike = :strike
          AND i.instrumentType = :instrumentType
        ORDER BY i.id ASC
    """)
    List<InstrumentDetails> findByCriteria(
            @Param("symbol") String symbol,
            @Param("expiry") String expiry,
            @Param("strike") BigDecimal strike,
            @Param("instrumentType") String instrumentType
    );

    /**
     * Same lookup shape as {@link #findByCriteria(String, String, BigDecimal, String)},
     * but returns the first deterministic candidate directly for read-only chart
     * use cases that only need one token.
     */
    @Query(value = """
        SELECT *
        FROM instrument_details i
        WHERE LOWER(i.tradingsymbol) LIKE LOWER(CONCAT(:symbol, '%'))
          AND i.expiry = :expiry
          AND i.strike = :strike
          AND i.instrument_type = :instrumentType
        ORDER BY i.instrument_token ASC
        LIMIT 1
    """, nativeQuery = true)
    Optional<InstrumentDetails> findFirstByCriteria(
            @Param("symbol") String symbol,
            @Param("expiry") String expiry,
            @Param("strike") BigDecimal strike,
            @Param("instrumentType") String instrumentType
    );
}
