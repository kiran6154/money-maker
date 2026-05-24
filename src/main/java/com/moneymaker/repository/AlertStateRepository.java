package com.moneymaker.repository;

import com.moneymaker.entity.AlertState;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;

@Repository
public interface AlertStateRepository extends JpaRepository<AlertState, Long> {

    /**
     * True when an alert with {@code alertKey} has already been recorded for
     * {@code alertDate}. The matching DB unique constraint on
     * {@code (alert_key, alert_date)} keeps the answer authoritative under
     * concurrent inserts.
     */
    boolean existsByAlertKeyAndAlertDate(String alertKey, LocalDate alertDate);
}
