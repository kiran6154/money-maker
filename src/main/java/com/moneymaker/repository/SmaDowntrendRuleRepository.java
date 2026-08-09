package com.moneymaker.repository;

import com.moneymaker.entity.SmaDowntrendRule;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface SmaDowntrendRuleRepository extends JpaRepository<SmaDowntrendRule, Integer> {

    /** All currently-enabled rules. EOD detector iterates this list per day. */
    List<SmaDowntrendRule> findByEnabledTrue();
}
