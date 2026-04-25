package com.moneymaker.state;

/**
 * Application run-mode. Selected via {@code app.mode} in
 * {@code application.properties}. Mutually exclusive — at most one of the
 * mode-specific bean groups is active at a time.
 *
 * <ul>
 *   <li>{@link #LIVE} – {@code com.moneymaker.scheduler.LoginScheduler} is
 *       active (08:00 cron + 1-min heartbeat). The backtest controller is
 *       <b>not</b> registered, so {@code POST /api/backtest/login} 404s.</li>
 *   <li>{@link #BACKTEST} – the scheduler is disabled. The backtest
 *       controller is active and exposes {@code POST /api/backtest/login}
 *       which calls the same {@code LoginOrchestrator} the live scheduler
 *       would have used.</li>
 * </ul>
 *
 * Both modes share the same {@code LoginOrchestrator} – there is intentionally
 * no second auth code path.
 */
public enum AppMode {
    LIVE,
    BACKTEST
}

