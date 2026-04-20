package com.moneymaker.scheduler;

import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.DayOfWeek;

@Slf4j
@Component
public class TradeConfigScheduler {

    @Scheduled(cron = "0 12 9 * * MON-FRI")
    public void dailyTaskAt912AM() {
        LocalDateTime now = LocalDateTime.now();

        if (now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY) {
            log.info("Scheduler has run at 9:12 AM on {}", now);
        }
    }

    @Scheduled(cron = "0 16 9 * * MON-FRI")
    public void checkTradeConfigAt916AM() {
        LocalDateTime now = LocalDateTime.now();

        if (now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY) {
            log.info("Is any trade-config available for today? Checking at 9:16 AM on {}", now);
        }
    }
}

