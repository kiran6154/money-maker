package com.moneymaker.scheduler;

import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.DayOfWeek;

@Slf4j
@Component
public class IndicatorScheduler {

    @Scheduled(cron = "0 20/5 9 * * MON-FRI")
    public void indicatorSchedulerEvery5Mins() {
        LocalDateTime now = LocalDateTime.now();

        if (now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY) {
            log.info("Indicator scheduler has run at {} on {}", now.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss")), now.toLocalDate());
        }
    }
}

