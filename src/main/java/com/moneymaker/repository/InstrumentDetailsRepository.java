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

    @Query("""
        SELECT i 
        FROM InstrumentDetails i
        WHERE LOWER(i.tradingSymbol) LIKE LOWER(CONCAT('%', :symbol, '%'))
          AND i.expiry = :expiry
          AND i.strike = :strike
          AND i.instrumentType = :instrumentType
    """)
    Optional<InstrumentDetails> findByCriteria(
            @Param("symbol") String symbol,
            @Param("expiry") String expiry,
            @Param("strike") BigDecimal strike,
            @Param("instrumentType") String instrumentType
    );
}
