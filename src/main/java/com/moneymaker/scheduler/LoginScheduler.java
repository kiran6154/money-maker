package com.moneymaker.scheduler;

import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.DayOfWeek;

@Slf4j
@Component
public class LoginScheduler {

    @Scheduled(cron = "0 0 9 * * MON-FRI")
    public void loginSchedulerAt900AM() {
        LocalDateTime now = LocalDateTime.now();

        if (now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY) {
            log.info("Login scheduler has run at 9:00 AM on {}", now);
        }
    }
}

