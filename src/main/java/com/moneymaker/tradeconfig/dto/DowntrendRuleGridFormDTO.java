package com.moneymaker.tradeconfig.dto;

import lombok.Data;

/**
 * The Detection rules panel's per-row save: the changeset-039 grid fields plus
 * the enabled toggle. {@code null} = leave unchanged (the panel sends every
 * field, but a scripted caller may patch one).
 *
 * <p>Deliberately <b>not</b> the whole rule. The bracket / band / deviation
 * columns are NOT NULL trading thresholds with their own history (changesets
 * 026/027/036); exposing them here would make the panel a second editor of
 * numbers the bulk-config panel and SQL already own.</p>
 */
@Data
public class DowntrendRuleGridFormDTO {

    /** CSV of SMA periods, e.g. {@code "50,100"}. Blank = reset to the default grid. */
    private String smaPeriods;

    /** CSV of timeframe minutes, e.g. {@code "5"}. Blank = reset to the default. */
    private String timeframesMinutes;

    /** Must be a registered {@code EodTrendScanner} type. */
    private String indicatorType;

    private Boolean enabled;
}
