package com.moneymaker.repository;

import com.moneymaker.entity.SmaTimeframe;
import jakarta.transaction.Transactional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;

@Repository
public interface SmaTimeframeRepository extends JpaRepository<SmaTimeframe, Integer> {

    List<SmaTimeframe> findByTradeConfigId(Integer tradeConfigId);

    /**
     * Bulk JPQL delete, deliberately NOT a derived delete. A derived delete
     * loads every child entity and queues per-row {@code delete … where id=?}
     * statements whose row counts Hibernate verifies at the next flush — so a
     * row removed by anything else in the meantime (a concurrent request, a
     * duplicate in the caller's list) throws {@code StaleStateException} and
     * rolls the whole delete back. The bulk form issues one statement, checks
     * nothing, and returns how many rows actually went.
     */
    @Transactional
    @Modifying
    @Query("delete from SmaTimeframe t where t.tradeConfig.id = :tradeConfigId")
    int deleteByTradeConfigId(@Param("tradeConfigId") Integer tradeConfigId);

    /** Bulk variant for the auto-config bulk delete. Same rationale as above. */
    @Transactional
    @Modifying
    @Query("delete from SmaTimeframe t where t.tradeConfig.id in :tradeConfigIds")
    int deleteByTradeConfigIdIn(@Param("tradeConfigIds") Collection<Integer> tradeConfigIds);
}
