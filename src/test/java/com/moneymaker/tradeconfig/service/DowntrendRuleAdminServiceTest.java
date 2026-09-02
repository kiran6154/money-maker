package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.SmaDowntrendRule;
import com.moneymaker.repository.SmaDowntrendRuleRepository;
import com.moneymaker.repository.SmaDowntrendRuleStrategyRepository;
import com.moneymaker.tradeconfig.dto.DowntrendRuleGridFormDTO;
import com.moneymaker.tradeconfig.generation.SmaDowntrendScanner;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * The Detection rules panel's save path. The contract: save-time validation is
 * stricter than the scanner's run-time leniency (reject, don't WARN-drop),
 * stored values are canonical, blank resets to the default grid, and null
 * fields patch nothing.
 */
class DowntrendRuleAdminServiceTest {

    private SmaDowntrendRuleRepository ruleRepository;
    private DowntrendRuleAdminService service;
    private SmaDowntrendRule rule;

    @BeforeEach
    void setUp() {
        ruleRepository = mock(SmaDowntrendRuleRepository.class);
        SmaDowntrendRuleStrategyRepository tagRepository = mock(SmaDowntrendRuleStrategyRepository.class);
        when(tagRepository.findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(anyInt())).thenReturn(List.of());

        service = new DowntrendRuleAdminService(ruleRepository, tagRepository,
                List.of(new SmaDowntrendScanner(null, null)));

        rule = new SmaDowntrendRule();
        rule.setId(1);
        rule.setStrategyId(1);
        rule.setEnabled(true);
        rule.setSmaPeriods("50,100,200,500");
        rule.setTimeframesMinutes("5,15");
        rule.setIndicatorType("SMA_DOWNTREND");
        when(ruleRepository.findById(1)).thenReturn(Optional.of(rule));
        when(ruleRepository.save(any(SmaDowntrendRule.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    private static DowntrendRuleGridFormDTO form() {
        return new DowntrendRuleGridFormDTO();
    }

    @Test
    @DisplayName("hand-typed spacing is stored canonically")
    void canonicalises() {
        DowntrendRuleGridFormDTO f = form();
        f.setSmaPeriods(" 200 , 50 ");
        f.setTimeframesMinutes(" 15 , 5 ,");

        service.updateGrid(1, f);

        assertThat(rule.getSmaPeriods()).isEqualTo("50,200");
        assertThat(rule.getTimeframesMinutes()).isEqualTo("5,15");
    }

    @Test
    @DisplayName("blank resets to the default grid rather than storing an ambiguous empty string")
    void blankResetsToDefaults() {
        DowntrendRuleGridFormDTO f = form();
        f.setSmaPeriods("");
        f.setTimeframesMinutes("");

        service.updateGrid(1, f);

        assertThat(rule.getSmaPeriods()).isEqualTo("50,100,200,500");
        assertThat(rule.getTimeframesMinutes()).isEqualTo("5,15");
    }

    @Test
    @DisplayName("an unsupported period is rejected at save time, not WARN-dropped later")
    void unsupportedPeriodRejected() {
        DowntrendRuleGridFormDTO f = form();
        f.setSmaPeriods("50,60");

        assertThatThrownBy(() -> service.updateGrid(1, f))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("[60]");
        verify(ruleRepository, never()).save(any());
    }

    @Test
    @DisplayName("input that parses to nothing is rejected — it is not 'blank'")
    void garbageRejected() {
        DowntrendRuleGridFormDTO f = form();
        f.setSmaPeriods("abc");

        assertThatThrownBy(() -> service.updateGrid(1, f))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("no usable period");
    }

    @Test
    @DisplayName("an unknown indicator type is rejected, naming the registered scanners")
    void unknownIndicatorRejected() {
        DowntrendRuleGridFormDTO f = form();
        f.setIndicatorType("RSI_OVERBOUGHT");

        assertThatThrownBy(() -> service.updateGrid(1, f))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("SMA_DOWNTREND");
        verify(ruleRepository, never()).save(any());
    }

    @Test
    @DisplayName("null fields patch nothing; enabled toggles alone")
    void nullFieldsKeepValues() {
        DowntrendRuleGridFormDTO f = form();
        f.setEnabled(false);

        service.updateGrid(1, f);

        assertThat(rule.getEnabled()).isFalse();
        assertThat(rule.getSmaPeriods()).isEqualTo("50,100,200,500");
        assertThat(rule.getTimeframesMinutes()).isEqualTo("5,15");
        assertThat(rule.getIndicatorType()).isEqualTo("SMA_DOWNTREND");
    }
}
