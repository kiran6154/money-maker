package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * Per-day record of "I already fired this alert for this trading date".
 * Backs {@code DailyEventGuard} so once-per-day notifications survive a JVM
 * restart.
 *
 * <p>Unique constraint {@code (alert_key, alert_date)} means a re-insert
 * raises {@code DataIntegrityViolationException}, which the guard treats as
 * "already fired".
 */
@Entity
@Table(name = "alert_state")
@Getter
@Setter
public class AlertState {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "alert_key", nullable = false, length = 64)
    private String alertKey;

    @Column(name = "alert_date", nullable = false)
    private LocalDate alertDate;

    @Column(name = "fired_at", nullable = false)
    private LocalDateTime firedAt;
}
