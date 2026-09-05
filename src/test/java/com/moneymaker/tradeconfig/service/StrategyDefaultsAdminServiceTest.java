package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.StrategyDefaults;
import com.moneymaker.repository.StrategyDefaultsRepository;
import com.moneymaker.tradeconfig.dto.StrategyBracketModeFormDTO;
import com.moneymaker.tradeconfig.dto.StrategyDefaultsViewDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the Strategy bracket panel's write path (changeset 041).
 *
 * <p>What it edits matters less than what it refuses: this service is one of two
 * callers of {@code BracketMode.parse} and the only one that may reject, so a
 * regression that made it degrade like {@code OrderService} does would let a
 * typo reach the column and silently trade the wrong bracket.</p>
 */
class StrategyDefaultsAdminServiceTest {

    private StrategyDefaultsRepository repo;
    private StrategyDefaultsAdminService service;

    @BeforeEach
    void setUp() {
        repo = mock(StrategyDefaultsRepository.class);
        service = new StrategyDefaultsAdminService(repo);
        when(repo.save(any(StrategyDefaults.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    private StrategyDefaults row(String targetMode, String slMode) {
        StrategyDefaults d = new StrategyDefaults();
        d.setStrategyId(1);
        d.setTransactionType("SELL");
        d.setLotQuantity(75);
        d.setMaxLoss(new BigDecimal("200"));
        d.setNoOfTrades(5);
        d.setNoOfParallelTrades(1);
        d.setAutoConfigEnabled(true);
        d.setOppositeSide(false);
        d.setTargetMode(targetMode);
        d.setSlMode(slMode);
        when(repo.findById(1)).thenReturn(Optional.of(d));
        return d;
    }

    private StrategyBracketModeFormDTO form(String targetMode, String slMode) {
        StrategyBracketModeFormDTO f = new StrategyBracketModeFormDTO();
        f.setTargetMode(targetMode);
        f.setSlMode(slMode);
        return f;
    }

    @Test
    @DisplayName("flips both sides and returns the saved state")
    void flipsBothSides() {
        StrategyDefaults d = row("PERCENT", "PERCENT");

        StrategyDefaultsViewDTO view = service.updateBracketModes(1, form("POINTS", "POINTS"));

        assertThat(d.getTargetMode()).isEqualTo("POINTS");
        assertThat(d.getSlMode()).isEqualTo("POINTS");
        assertThat(view.getTargetMode()).isEqualTo("POINTS");
        assertThat(view.getSlMode()).isEqualTo("POINTS");
    }

    @Test
    @DisplayName("the two sides are independent — a points target with a percentage stop")
    void sidesAreIndependent() {
        // The mixed bracket 041 exists to make expressible.
        StrategyDefaults d = row("PERCENT", "PERCENT");

        service.updateBracketModes(1, form("POINTS", "PERCENT"));

        assertThat(d.getTargetMode()).isEqualTo("POINTS");
        assertThat(d.getSlMode()).isEqualTo("PERCENT");
    }

    @Test
    @DisplayName("a null side is left unchanged, not defaulted")
    void nullSideIsUnchanged() {
        StrategyDefaults d = row("POINTS", "PERCENT");

        service.updateBracketModes(1, form(null, "POINTS"));

        assertThat(d.getTargetMode()).isEqualTo("POINTS");
        assertThat(d.getSlMode()).isEqualTo("POINTS");
    }

    @Test
    @DisplayName("stores the canonical casing, not what was typed")
    void canonicalisesCasing() {
        StrategyDefaults d = row("PERCENT", "PERCENT");

        service.updateBracketModes(1, form("  points  ", "Percent"));

        assertThat(d.getTargetMode()).isEqualTo("POINTS");
        assertThat(d.getSlMode()).isEqualTo("PERCENT");
    }

    @ParameterizedTest
    @ValueSource(strings = {"POINT", "PCT", "%", ""})
    @DisplayName("an unusable mode is rejected and nothing is written")
    void rejectsUnusableMode(String raw) {
        // Deliberately stricter than OrderService, which degrades to PERCENT so a
        // typo cannot stop trading. Here a human is attached, so the mistake is
        // fixed now rather than found in a log after a session of wrong exits.
        row("PERCENT", "PERCENT");

        assertThatThrownBy(() -> service.updateBracketModes(1, form(raw, "PERCENT")))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("targetMode");

        verify(repo, never()).save(any());
    }

    @Test
    @DisplayName("a missing strategy row is an error, never an insert")
    void missingRowIsRejected() {
        // Creating the row would mean guessing transaction_type / max_loss / the
        // trade counts — the trading decisions CLAUDE.md #9 forbids defaulting.
        when(repo.findById(9)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.updateBracketModes(9, form("POINTS", "POINTS")))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("strategy 9");

        verify(repo, never()).save(any());
    }

    @Test
    @DisplayName("a legacy NULL column surfaces as the PERCENT the resolver applies")
    void nullColumnReadsAsPercent() {
        // An empty dropdown would misreport which bracket the strategy is on.
        // Built before the stub, not inside it: row() stubs findById, and a
        // when() inside another when()'s argument is unfinished stubbing.
        StrategyDefaults legacy = row(null, null);
        when(repo.findAll()).thenReturn(List.of(legacy));

        StrategyDefaultsViewDTO view = service.list().get(0);

        assertThat(view.getTargetMode()).isEqualTo("PERCENT");
        assertThat(view.getSlMode()).isEqualTo("PERCENT");
    }
}
