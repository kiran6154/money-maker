package com.moneymaker.telegram;

import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.HeartbeatStatus;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/**
 * Notification facade. Other packages depend on this class (not Telegram
 * directly) so future channels can be plugged in without touching callers.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationService {

    private static final DateTimeFormatter TS =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneId.of("Asia/Kolkata"));

    private final TelegramNotifier telegram;

    public void alertLoginSuccess(Broker broker, String userId) {
        telegram.send(String.format("[OK] *%s* login successful (%s) at %s IST",
                broker, userId == null ? "-" : userId, TS.format(Instant.now())));
    }

    public void alertLoginFailed(Broker broker, String reason) {
        telegram.send(String.format("[FAIL] *%s* login FAILED at %s IST\nReason: `%s`",
                broker, TS.format(Instant.now()), safe(reason)));
    }

    public void alertSessionLost(Broker broker, HeartbeatStatus status, String reason) {
        telegram.send(String.format("[ALERT] *%s* session lost (%s) at %s IST\nDetails: `%s`",
                broker, status, TS.format(Instant.now()), safe(reason)));
    }

    public void alertNoData(Broker broker, String reason) {
        telegram.send(String.format("[NO-DATA] *%s* token valid but NO market data at %s IST\nDetails: `%s`",
                broker, TS.format(Instant.now()), safe(reason)));
    }

    public void alertRecovered(Broker broker) {
        telegram.send(String.format("[RECOVERED] *%s* heartbeat back to OK at %s IST",
                broker, TS.format(Instant.now())));
    }

    private static String safe(String s) {
        return s == null ? "-" : s.replace("`", "'");
    }
}

