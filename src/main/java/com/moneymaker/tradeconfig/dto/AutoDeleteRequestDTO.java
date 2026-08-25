package com.moneymaker.tradeconfig.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

/**
 * Bulk-delete selector for auto-generated trade configs.
 *
 * <p>Exactly one axis is honoured, chosen by {@link #mode}:</p>
 * <ul>
 *   <li>{@code TRADING_DATE} — drop configs whose {@code trading_date} is in
 *       {@link #dates}. "Remove what trades on the 12th."</li>
 *   <li>{@code UPDATED_RANGE} — drop configs written between
 *       {@link #updatedFrom} and {@link #updatedTo}. "Undo that generation run,"
 *       which spans several trading dates and so cannot be expressed above.</li>
 * </ul>
 *
 * <p>{@code source='AUTO_DOWNTREND'} is applied by the service and is not part of
 * this request — a client cannot widen the delete to MANUAL rows.</p>
 */
@Data
public class AutoDeleteRequestDTO {

    public enum Mode { TRADING_DATE, UPDATED_RANGE }

    /** Values of {@code trade_config.source}. Nothing else is reachable here. */
    public enum Source { AUTO_DOWNTREND, MANUAL }

    private Mode mode = Mode.TRADING_DATE;

    /**
     * Which configs the selector may reach. Defaults to {@code AUTO_DOWNTREND},
     * the disposable detector output — so an incomplete request can never touch
     * hand-written configs. {@code MANUAL} is an explicit opt-in.
     *
     * <p>Ignored when {@code mode=UPDATED_RANGE}: a "generation run" is a
     * detector concept, so that mode stays pinned to {@code AUTO_DOWNTREND}.</p>
     */
    private Source source = Source.AUTO_DOWNTREND;

    /** Used when {@code mode=TRADING_DATE}. */
    private List<LocalDate> dates;

    /** Inclusive lower bound, used when {@code mode=UPDATED_RANGE}. */
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd'T'HH:mm:ss")
    private LocalDateTime updatedFrom;

    /** Inclusive upper bound, used when {@code mode=UPDATED_RANGE}. */
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd'T'HH:mm:ss")
    private LocalDateTime updatedTo;

    /**
     * Defaults to {@code true} so an incomplete or malformed call reports what it
     * <i>would</i> remove instead of removing it. The UI always previews first and
     * shows the server's own count in the confirm dialog, so the number you approve
     * is the number the server matched — not one the browser guessed.
     */
    private boolean dryRun = true;

    /**
     * When {@code true}, configs that {@code trade_order} rows reference are
     * deleted too — <b>and so are those trade rows</b>. Defaults to {@code false},
     * which keeps the audit protection: such configs are skipped and reported as
     * {@code skippedWithTrades}.
     *
     * <p>Only ever set from an explicit opt-in in the confirm dialog. The trade
     * history it removes is not recoverable, so it must never be defaulted on.</p>
     */
    private boolean force = false;
}
