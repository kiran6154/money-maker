package com.moneymaker.repository;

import com.moneymaker.entity.InstrumentDetails;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

@Repository
public interface InstrumentDetailsRepository extends JpaRepository<InstrumentDetails, Integer> {

    List<InstrumentDetails> findByStrikeAndInstrumentTypeOrderByExpiryAsc(BigDecimal strike, String instrumentType);

    Optional<InstrumentDetails> findByTradingSymbol(String tradingSymbol);
}
