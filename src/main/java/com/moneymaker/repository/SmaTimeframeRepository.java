package com.moneymaker.repository;

import com.moneymaker.entity.SmaTimeframe;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface SmaTimeframeRepository extends JpaRepository<SmaTimeframe, Integer> {

    List<SmaTimeframe> findByTradeConfigId(Integer tradeConfigId);
}
