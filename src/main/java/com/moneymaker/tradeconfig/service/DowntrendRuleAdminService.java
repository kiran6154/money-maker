package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.SmaDowntrendRule;
import com.moneymaker.entity.SmaDowntrendRuleStrategy;
import com.moneymaker.repository.SmaDowntrendRuleRepository;
import com.moneymaker.repository.SmaDowntrendRuleStrategyRepository;
import com.moneymaker.tradeconfig.dto.DowntrendRuleGridFormDTO;
import com.moneymaker.tradeconfig.dto.DowntrendRuleViewDTO;
import com.moneymaker.tradeconfig.generation.EodTrendScanner;
import com.moneymaker.tradeconfig.generation.SmaDowntrendScanner;
import com.moneymaker.util.IntCsv;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

/**
 * Read + grid-edit surface behind the Detection rules panel on
 * {@code /trade-configs} — the front end for changeset 039's per-rule grid
 * ("skip a few SMAs / pick the indicator" without SQL).
 *
 * <p>Edits are limited to the grid ({@code sma_periods},
 * {@code timeframes_minutes}, {@code indicator_type}) and {@code enabled}. The
 * rule's thresholds and bracket stay SQL-only on purpose — they are NOT NULL
 * trading numbers with their own changeset history, and this panel exists to
 * make the grid selectable, not to become a second config editor.</p>
 *
 * <p>Save-time validation is deliberately stricter than the scanner's
 * run-time behaviour: {@link SmaDowntrendScanner} WARN-drops an unsupported
 * period so a hand-edited row cannot silence a whole rule, but an interactive
 * save has a human attached, so it <b>rejects</b> instead — the mistake is
 * fixed now rather than discovered in a log later. Stored values are
 * canonicalised through {@link IntCsv} so the column never carries the
 * spacing someone typed.</p>
 *
 * <p>No cache to invalidate: unlike trade-config writes, the detector reads
 * {@code sma_downtrend_rule} fresh on every {@code runForDay}.</p>
 */
@Slf4j
@Service
public class DowntrendRuleAdminService {

    private final SmaDowntrendRuleRepository ruleRepository;
    private final SmaDowntrendRuleStrategyRepository ruleStrategyRepository;
    private final List<String> indicatorTypes;

    public DowntrendRuleAdminService(SmaDowntrendRuleRepository ruleRepository,
                                     SmaDowntrendRuleStrategyRepository ruleStrategyRepository,
                                     List<EodTrendScanner> scanners) {
        this.ruleRepository = ruleRepository;
        this.ruleStrategyRepository = ruleStrategyRepository;
        this.indicatorTypes = scanners == null
                ? List.of()
                : scanners.stream().map(EodTrendScanner::indicatorType).sorted().toList();
    }

    /** Registered scanner types — the panel's indicator dropdown source. */
    public List<String> indicatorTypes() {
        return indicatorTypes;
    }

    public List<DowntrendRuleViewDTO> list() {
        return ruleRepository.findAll().stream()
                .sorted(Comparator.comparing(SmaDowntrendRule::getId,
                        Comparator.nullsLast(Integer::compareTo)))
                .map(this::toView)
                .toList();
    }

    @Transactional
    public DowntrendRuleViewDTO updateGrid(Integer id, DowntrendRuleGridFormDTO form) {
        if (form == null) throw new IllegalArgumentException("form payload missing");
        SmaDowntrendRule rule = ruleRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("No downtrend rule with id=" + id));

        if (form.getSmaPeriods() != null) {
            rule.setSmaPeriods(canonicalPeriods(form.getSmaPeriods()));
        }
        if (form.getTimeframesMinutes() != null) {
            rule.setTimeframesMinutes(canonicalTimeframes(form.getTimeframesMinutes()));
        }
        if (form.getIndicatorType() != null) {
            String type = form.getIndicatorType().trim();
            if (!indicatorTypes.contains(type)) {
                throw new IllegalArgumentException("Unknown indicator_type '" + type
                        + "' — registered scanners: " + indicatorTypes);
            }
            rule.setIndicatorType(type);
        }
        if (form.getEnabled() != null) {
            rule.setEnabled(form.getEnabled());
        }

        ruleRepository.save(rule);
        log.info("[downtrend-rule] updated id={} smaPeriods='{}' timeframes='{}' indicator='{}' enabled={}",
                id, rule.getSmaPeriods(), rule.getTimeframesMinutes(),
                rule.getIndicatorType(), rule.getEnabled());
        return toView(rule);
    }

    /**
     * Blank resets to the default grid (the scanner reads blank the same way, so
     * storing the default explicitly just makes the row say what it does). A
     * non-blank value must parse to at least one period, all of them supported.
     */
    private static String canonicalPeriods(String input) {
        if (input.isBlank()) {
            return IntCsv.format(SmaDowntrendScanner.DEFAULT_SMA_PERIODS);
        }
        List<Integer> periods = IntCsv.parse(input);
        if (periods.isEmpty()) {
            throw new IllegalArgumentException("smaPeriods '" + input
                    + "' contains no usable period. Use a comma list from "
                    + SmaDowntrendScanner.SUPPORTED_PERIODS.stream().sorted().toList()
                    + ", or leave blank for the default grid.");
        }
        List<Integer> unsupported = periods.stream()
                .filter(p -> !SmaDowntrendScanner.SUPPORTED_PERIODS.contains(p))
                .toList();
        if (!unsupported.isEmpty()) {
            throw new IllegalArgumentException("Unsupported SMA period(s) " + unsupported
                    + " — MarketData has trend flags only for "
                    + SmaDowntrendScanner.SUPPORTED_PERIODS.stream().sorted().toList()
                    + ". Adding a new period is a code change (flags + SmaTrendCalculator).");
        }
        return IntCsv.format(periods);
    }

    private static String canonicalTimeframes(String input) {
        if (input.isBlank()) {
            return IntCsv.format(SmaDowntrendScanner.DEFAULT_TIMEFRAMES_MINUTES);
        }
        List<Integer> timeframes = IntCsv.parse(input);
        if (timeframes.isEmpty()) {
            throw new IllegalArgumentException("timeframesMinutes '" + input
                    + "' contains no usable value — use positive minutes like 5,15, "
                    + "or leave blank for the default.");
        }
        return IntCsv.format(timeframes);
    }

    private DowntrendRuleViewDTO toView(SmaDowntrendRule rule) {
        DowntrendRuleViewDTO v = new DowntrendRuleViewDTO();
        v.setId(rule.getId());
        if (rule.getInstrument() != null) {
            v.setInstrumentId(rule.getInstrument().getId());
            v.setInstrumentName(rule.getInstrument().getInsName());
        }
        v.setStrategyId(rule.getStrategyId());

        // Same resolution the detector uses: enabled tags, or the primary.
        List<Integer> tagged = rule.getId() == null
                ? List.of()
                : ruleStrategyRepository.findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(rule.getId())
                        .stream()
                        .map(SmaDowntrendRuleStrategy::getStrategyId)
                        .filter(Objects::nonNull)
                        .toList();
        if (tagged.isEmpty() && rule.getStrategyId() != null) {
            tagged = List.of(rule.getStrategyId());
        }
        v.setStrategyIds(new ArrayList<>(tagged));

        v.setEnabled(rule.getEnabled());
        v.setSmaPeriods(rule.getSmaPeriods());
        v.setTimeframesMinutes(rule.getTimeframesMinutes());
        v.setIndicatorType(rule.getIndicatorType());
        v.setMaxDeviation(rule.getMaxDeviation());
        v.setStartTime(rule.getStartTime());
        v.setTargetPct(rule.getTargetPct());
        v.setSlPct(rule.getSlPct());
        v.setMaxSlPoints(rule.getMaxSlPoints());
        v.setTrailLadder(rule.getTrailLadder());
        v.setMinOptionPrice(rule.getMinOptionPrice());
        v.setMaxOptionPrice(rule.getMaxOptionPrice());
        return v;
    }
}
