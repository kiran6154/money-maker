package com.moneymaker.repository;

import com.moneymaker.entity.TradeConfig;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;

@Repository
public interface TradeConfigRepository extends JpaRepository<TradeConfig, Integer> {
    List<TradeConfig> findByTradingDate(LocalDate tradingDate);

    @Query(value = "SELECT tc.*, i.*, id.* FROM trade_config tc " +
            "JOIN instrument i ON tc.p_instrument = i.id " +
            "JOIN instrument_details id ON i.ins_id = id.instrument_token " +
            "WHERE DATE(tc.trading_date) = :tradingDate", nativeQuery = true)
    List<Object[]> fetchCombinedByTradingDate(@Param("tradingDate") LocalDate tradingDate);
}
