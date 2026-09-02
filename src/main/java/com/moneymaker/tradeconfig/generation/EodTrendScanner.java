package com.moneymaker.tradeconfig.generation;

import com.moneymaker.entity.SmaDowntrendRule;

import java.time.LocalDate;
import java.util.List;

/**
 * One indicator's end-of-day scan — the seam that lets a new indicator rule be
 * added to the auto-config pipeline without touching the detector
 * (changeset 039, user request 2026-08-31).
 *
 * <p>{@link EodDowntrendDetectionService} owns everything indicator-agnostic:
 * which rules run, ATM strike selection, the bracket basis, idempotency, and
 * writing the {@code trade_config} + {@code sma_timeframe} rows. A scanner owns
 * exactly one question — <i>does this option leg qualify at today's close, and
 * on which (sma, timeframe) combos?</i> The detector picks the scanner whose
 * {@link #indicatorType()} matches {@code sma_downtrend_rule.indicator_type};
 * all scanners are discovered by Spring {@code List} injection, the same
 * pattern the order-placement and position-monitor factories use.</p>
 *
 * <p><b>To add an indicator rule</b> (say an RSI threshold): implement this
 * interface as a {@code @Component} returning a new type name, then point rule
 * rows at it with {@code UPDATE sma_downtrend_rule SET indicator_type='...'}.
 * No detector change, no new endpoint. Thresholds the new scan needs are new
 * columns on {@code sma_downtrend_rule} (CLAUDE.md #9 — detection knobs live in
 * the rules table, not in code), added by their own changeset.</p>
 *
 * <p><b>The combo contract.</b> Whatever the indicator measures, the returned
 * pairs become the generated config's {@code sma_timeframe} children — and those
 * children are what the <i>strategies</i> scan the next day (each pair's SMA is
 * a primary period for the SMA-cross engine). A non-SMA scanner therefore still
 * decides which (sma, timeframe) combos its detection vouches for; returning a
 * pair whose SMA period has no strategy rule case (e.g. 20 today) generates a
 * config that will not trade. Empty list = this side does not qualify.</p>
 */
public interface EodTrendScanner {

    /** The {@code sma_downtrend_rule.indicator_type} value this scanner serves. */
    String indicatorType();

    /**
     * Scans one option leg at {@code tradingDay}'s close under {@code rule}.
     *
     * @return the qualifying {@code [smaPeriod, timeframeMinutes]} pairs, empty
     *         when the leg does not qualify. May throw
     *         {@code HistoricalDataMissingException} when the data source has no
     *         series for the leg — the detector treats that as "skip this side".
     */
    List<int[]> scan(String optionToken, LocalDate tradingDay, SmaDowntrendRule rule);
}
