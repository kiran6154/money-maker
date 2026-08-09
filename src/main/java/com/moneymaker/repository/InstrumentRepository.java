package com.moneymaker.repository;

import com.moneymaker.entity.Instrument;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface InstrumentRepository extends JpaRepository<Instrument, Integer> {

    /**
     * Exact-match path when the DB stores the canonical index label as-is
     * (e.g. "NIFTY", "BANKNIFTY").
     */
    Optional<Instrument> findFirstByInsNameIgnoreCaseOrderByIdAsc(String insName);

    /**
     * Candidate lookup for environments where the index is stored with a
     * variant label (e.g. "NIFTY50"). Callers should prefer the exact-match
     * method above first, then fall back to this ordered candidate list.
     */
    @Query("""
        SELECT i
        FROM Instrument i
        WHERE LOWER(i.insName) LIKE LOWER(CONCAT(:namePrefix, '%'))
        ORDER BY i.id ASC
    """)
    List<Instrument> findByInsNameStartingWithIgnoreCaseOrderByIdAsc(
            @Param("namePrefix") String namePrefix);
}
