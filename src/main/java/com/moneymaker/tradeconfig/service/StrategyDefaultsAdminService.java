package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.StrategyDefaults;
import com.moneymaker.repository.StrategyDefaultsRepository;
import com.moneymaker.tradeconfig.dto.StrategyBracketModeFormDTO;
import com.moneymaker.tradeconfig.dto.StrategyDefaultsViewDTO;
import com.moneymaker.util.BracketMode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Comparator;
import java.util.List;

/**
 * Read + bracket-mode edit surface behind the Strategy bracket panel on
 * {@code /trade-configs} — the front end for changeset 041's per-strategy
 * POINTS/PERCENT switch, so flipping it is a click rather than an
 * {@code UPDATE strategy_defaults}.
 *
 * <p>Edits are limited to {@code target_mode} / {@code sl_mode}. The rest of the
 * block — {@code transaction_type}, {@code max_loss}, the trade counts,
 * {@code opposite_side} — stays SQL-only for the reason
 * {@link DowntrendRuleAdminService} leaves its thresholds alone: they are NOT
 * NULL trading numbers with their own changeset history, and this panel exists
 * to make the bracket selectable, not to become a second config editor.</p>
 *
 * <p>Validation is deliberately stricter than the runtime's: {@code OrderService}
 * degrades an unreadable mode to {@code PERCENT} so a typo cannot stop trading,
 * but an interactive save has a human attached, so it <b>rejects</b> — the
 * mistake is fixed now rather than discovered as a log line after a session of
 * trades exited on the wrong bracket. Stored values are canonicalised through
 * {@link BracketMode}, so the column never carries the casing someone typed.</p>
 *
 * <p><b>No cache to invalidate</b>, unlike trade-config writes: {@code OrderService}
 * reads {@code strategy_defaults} fresh on every order open, so a save takes
 * effect on the next trade rather than at the next config-cache refresh. Trades
 * already open keep the bracket they were snapshotted with at entry
 * (changeset 011), which is the point of snapshotting it.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StrategyDefaultsAdminService {

    private final StrategyDefaultsRepository strategyDefaultsRepository;

    /** Every strategy block, ascending — the panel's row source. */
    public List<StrategyDefaultsViewDTO> list() {
        return strategyDefaultsRepository.findAll().stream()
                .sorted(Comparator.comparing(StrategyDefaults::getStrategyId,
                        Comparator.nullsLast(Integer::compareTo)))
                .map(this::toView)
                .toList();
    }

    /** The two values the panel's dropdowns offer. */
    public List<String> bracketModes() {
        return List.of(BracketMode.POINTS.name(), BracketMode.PERCENT.name());
    }

    /**
     * Flips one strategy's bracket modes.
     *
     * <p>A missing strategy is an error rather than an insert: creating a
     * {@code strategy_defaults} row means choosing a {@code transaction_type},
     * a {@code max_loss} and the trade counts, which are exactly the trading
     * decisions CLAUDE.md #9 forbids this service from guessing. The row is
     * created by the INSERT documented in EOD_DOWNTREND.md; this panel edits it
     * afterwards.</p>
     */
    @Transactional
    public StrategyDefaultsViewDTO updateBracketModes(Integer strategyId, StrategyBracketModeFormDTO form) {
        if (form == null) throw new IllegalArgumentException("form payload missing");
        StrategyDefaults defaults = strategyDefaultsRepository.findById(strategyId)
                .orElseThrow(() -> new IllegalArgumentException(
                        "No strategy_defaults row for strategy " + strategyId
                                + " — insert one first (see docs/EOD_DOWNTREND.md)"));

        String previousTarget = defaults.getTargetMode();
        String previousSl = defaults.getSlMode();

        if (form.getTargetMode() != null) {
            defaults.setTargetMode(require(form.getTargetMode(), "targetMode").name());
        }
        if (form.getSlMode() != null) {
            defaults.setSlMode(require(form.getSlMode(), "slMode").name());
        }

        StrategyDefaults saved = strategyDefaultsRepository.save(defaults);

        // Logged because it changes which price closes a trade, and the ledger
        // records only the resolved number — without this line there is nothing
        // that says when the bracket a run used was switched.
        log.info("[strategy-defaults] strategyId={} bracket target {} -> {}, sl {} -> {}",
                strategyId, previousTarget, saved.getTargetMode(), previousSl, saved.getSlMode());

        return toView(saved);
    }

    /**
     * Parses one submitted mode, naming the field when it is unusable.
     *
     * <p>Blank is rejected rather than treated as "unchanged": the form already
     * says unchanged with {@code null}, and a blank arriving here is a cleared
     * dropdown, which for a NOT NULL column is a mistake worth surfacing.</p>
     */
    private BracketMode require(String raw, String field) {
        if (raw.isBlank()) {
            throw new IllegalArgumentException(field + " must be POINTS or PERCENT, not blank");
        }
        try {
            return BracketMode.parse(raw);
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException(field + ": " + ex.getMessage(), ex);
        }
    }

    private StrategyDefaultsViewDTO toView(StrategyDefaults d) {
        StrategyDefaultsViewDTO v = new StrategyDefaultsViewDTO();
        v.setStrategyId(d.getStrategyId());
        // Through the typed accessors, so a legacy NULL surfaces as the PERCENT
        // the resolver actually applies rather than as an empty dropdown.
        v.setTargetMode(d.targetMode().name());
        v.setSlMode(d.slMode().name());
        v.setTransactionType(d.getTransactionType());
        v.setLotQuantity(d.getLotQuantity());
        v.setMaxLoss(d.getMaxLoss());
        v.setNoOfTrades(d.getNoOfTrades());
        v.setNoOfParallelTrades(d.getNoOfParallelTrades());
        v.setOppositeSide(d.tradesOppositeSide());
        v.setAutoConfigEnabled(d.getAutoConfigEnabled());
        return v;
    }
}
