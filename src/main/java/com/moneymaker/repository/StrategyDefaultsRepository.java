package com.moneymaker.repository;

import com.moneymaker.entity.StrategyDefaults;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface StrategyDefaultsRepository extends JpaRepository<StrategyDefaults, Integer> {
}
