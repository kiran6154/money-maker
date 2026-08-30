package com.moneymaker.market.provider;

import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Properties;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * GAPS #20 — provider selection moves out of Spring's autowiring rules and into
 * one readable place.
 *
 * <p>The load-bearing test here is
 * {@link #resolution_is_unchanged_under_the_shipped_properties()}. Everything else
 * describes the new rule; that one proves the rule <b>did not change which
 * provider actually runs</b>, which is the condition attached to dropping the
 * {@code @Primary} the factory replaces. It reads the real
 * {@code application.properties} rather than restating what it says, because a
 * test that hardcodes the property values it is meant to be checking proves
 * nothing the day someone edits them.
 */
class MarketDataProviderFactoryTest {

    /** Minimal stand-in — the factory only ever asks a provider for its name. */
    private record NamedProvider(String name) implements MarketDataProvider {
        @Override public String getName() { return name; }
        @Override public List<MarketData> fetchHistoricalData(
                String symbol, LocalDateTime from, LocalDateTime to, String interval) {
            return List.of();
        }
    }

    private static MarketDataProvider provider(String name) {
        return new NamedProvider(name);
    }

    private static MarketDataProviderFactory factory(String configured, MarketDataProvider... providers) {
        MarketDataProviderFactory f = new MarketDataProviderFactory(List.of(providers), configured);
        ReflectionTestUtils.invokeMethod(f, "resolve");
        return f;
    }

    /* ---------------- the claim that licenses dropping @Primary ---------------- */

    @Test
    @DisplayName("under the shipped application.properties the factory resolves the same provider @Primary did")
    void resolution_is_unchanged_under_the_shipped_properties() throws IOException {
        Properties shipped = new Properties();
        Path file = Paths.get("src", "main", "resources", "application.properties");
        try (var in = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            shipped.load(in);
        }

        String brokerActive = shipped.getProperty("broker.active");
        String backtestSource = shipped.getProperty("backtest.data-source");
        String configuredProvider = shipped.getProperty("market.data.provider", "");

        // Which provider beans register is decided by @ConditionalOnProperty on each
        // class; reproduce that here from the same property values Spring would read.
        assertThat(brokerActive)
                .as("ZerodhaMarketDataProvider is gated on broker.active=ZERODHA (matchIfMissing=true)")
                .isEqualTo("ZERODHA");
        assertThat(backtestSource)
                .as("HistoricalIciciMarketDataProvider is gated on backtest.data-source=HISTORICAL_ICICI")
                .isEqualTo("HISTORICAL_ICICI");

        MarketDataProviderFactory f = factory(configuredProvider,
                provider(ZerodhaMarketDataProvider.NAME),
                provider(HistoricalIciciMarketDataProvider.NAME));

        // Before: two candidates for KiteHistoricalFetcher's single MarketDataProvider
        // parameter, arbitrated by @Primary on HistoricalIcici. After: the factory's
        // default precedence. Same answer -- that equality is the whole point.
        assertThat(f.active().getName()).isEqualTo(HistoricalIciciMarketDataProvider.NAME);
    }

    @Test
    @DisplayName("HISTORICAL_ICICI outranks the broker, so a replay can never fall through to a live API")
    void historical_outranks_the_broker_regardless_of_bean_order() {
        assertThat(factory("", provider(ZerodhaMarketDataProvider.NAME),
                               provider(HistoricalIciciMarketDataProvider.NAME))
                .active().getName()).isEqualTo(HistoricalIciciMarketDataProvider.NAME);

        // List injection order is not a contract, so the answer must not depend on it.
        assertThat(factory("", provider(HistoricalIciciMarketDataProvider.NAME),
                               provider(ZerodhaMarketDataProvider.NAME))
                .active().getName()).isEqualTo(HistoricalIciciMarketDataProvider.NAME);
    }

    /* ---------------- the rule ---------------- */

    @Test
    @DisplayName("one registered provider is used whatever it is")
    void single_provider_wins() {
        assertThat(factory("", provider(ZerodhaMarketDataProvider.NAME)).active().getName())
                .isEqualTo(ZerodhaMarketDataProvider.NAME);
        assertThat(factory("", provider("ANYTHING")).active().getName()).isEqualTo("ANYTHING");
    }

    @Test
    @DisplayName("market.data.provider overrides the precedence — the key finally has a reader")
    void explicit_property_overrides() {
        MarketDataProviderFactory f = factory("ZERODHA",
                provider(ZerodhaMarketDataProvider.NAME),
                provider(HistoricalIciciMarketDataProvider.NAME));

        assertThat(f.active().getName()).isEqualTo(ZerodhaMarketDataProvider.NAME);
    }

    @Test
    @DisplayName("the override is case- and whitespace-insensitive")
    void override_is_lenient_about_formatting() {
        assertThat(factory("  zerodha  ",
                provider(ZerodhaMarketDataProvider.NAME),
                provider(HistoricalIciciMarketDataProvider.NAME))
                .active().getName()).isEqualTo(ZerodhaMarketDataProvider.NAME);
    }

    /* ---------------- the loud failures ---------------- */

    @Test
    @DisplayName("a typo'd market.data.provider fails startup instead of silently picking something else")
    void unknown_name_fails_startup() {
        assertThatThrownBy(() -> factory("ZERODAH",
                provider(ZerodhaMarketDataProvider.NAME),
                provider(HistoricalIciciMarketDataProvider.NAME)))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("does not match any registered provider")
                .hasMessageContaining("ZERODAH");
    }

    @Test
    @DisplayName("no providers at all fails startup")
    void no_providers_fails_startup() {
        assertThatThrownBy(() -> factory(""))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("No MarketDataProvider beans are registered");
    }

    @Test
    @DisplayName("several providers, none in the precedence list, refuses to guess")
    void ambiguous_set_refuses_to_guess() {
        assertThatThrownBy(() -> factory("", provider("ALPHA"), provider("BETA")))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Set market.data.provider");
    }

    @Test
    @DisplayName("two providers sharing a name is a wiring bug, not a coin toss")
    void duplicate_names_rejected() {
        assertThatThrownBy(() -> factory("", provider("ZERODHA"), provider("zerodha")))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("must be unique");
    }

    @Test
    @DisplayName("registeredNames reports every provider, for the startup log and error messages")
    void reports_what_is_registered() {
        assertThat(factory("", provider(ZerodhaMarketDataProvider.NAME),
                               provider(HistoricalIciciMarketDataProvider.NAME))
                .registeredNames())
                .containsExactly(HistoricalIciciMarketDataProvider.NAME, ZerodhaMarketDataProvider.NAME);
    }
}
