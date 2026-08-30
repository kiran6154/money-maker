package com.moneymaker.market.provider;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

/**
 * Resolves the one {@link MarketDataProvider} the app fetches candles through.
 *
 * <p>Before this existed (GAPS #20 — the file was literally empty), selection was
 * an emergent property of {@code @ConditionalOnProperty} annotations spread across
 * the provider classes plus a {@code @Primary} on one of them, and the actual
 * decision was made by Spring's autowiring rules at the single-provider injection
 * point in {@code KiteHistoricalFetcher}. That is fragile in a specific way: any
 * second provider bean made the injection ambiguous and startup died with
 * {@code NoUniqueBeanDefinitionException}, so {@code @Primary} was load-bearing
 * without being an obvious statement of intent, and the answer to "which provider
 * is running?" was not written down anywhere.
 *
 * <h3>The rule, in order</h3>
 * <ol>
 *   <li><b>{@code market.data.provider} is set</b> — that provider is used, matched
 *       case-insensitively against {@link MarketDataProvider#getName()}. A name
 *       that matches no registered provider <b>fails startup</b> naming the
 *       candidates, rather than silently falling through to whatever else is on
 *       the classpath. This is what the key was always for; it just never had a
 *       reader.</li>
 *   <li><b>Exactly one provider registered</b> — that one, no ambiguity to
 *       resolve.</li>
 *   <li><b>Several registered, no property</b> — {@link #DEFAULT_PRECEDENCE},
 *       highest first. Today that means the historical source wins over the
 *       broker, which is exactly what the {@code @Primary} it replaces
 *       encoded.</li>
 *   <li><b>None registered</b> — fails startup. A market-data app with no market
 *       data has nothing useful to do next.</li>
 * </ol>
 *
 * <h3>Why HISTORICAL_ICICI outranks the broker</h3>
 * Not arbitrary, and worth stating now that it is a line of code rather than an
 * annotation: when {@code backtest.data-source=HISTORICAL_ICICI} is active, the
 * operator has asked to replay imported candles. Any path that still reaches the
 * fetcher should read those, not quietly call a live broker API — a replay that
 * silently mixes in today's real quotes produces a ledger that is not a function
 * of the replayed window, which is the class of bug GAPS #4 / S11 were about.
 * Deferring to the broker instead would be the dangerous default.
 */
@Slf4j
@Component
public class MarketDataProviderFactory {

    /**
     * Applied only when several providers are registered and
     * {@code market.data.provider} does not say which to use. Earlier wins.
     */
    static final List<String> DEFAULT_PRECEDENCE = List.of(
            HistoricalIciciMarketDataProvider.NAME,
            ZerodhaMarketDataProvider.NAME);

    private final Map<String, MarketDataProvider> byName = new LinkedHashMap<>();
    private final String configuredName;
    private MarketDataProvider active;

    public MarketDataProviderFactory(List<MarketDataProvider> providers,
                                     @Value("${market.data.provider:}") String configuredName) {
        this.configuredName = configuredName == null ? "" : configuredName.trim();
        for (MarketDataProvider provider : providers) {
            if (provider == null || provider.getName() == null) continue;
            MarketDataProvider clash = byName.put(key(provider.getName()), provider);
            if (clash != null) {
                throw new IllegalStateException("Two MarketDataProviders both call themselves '"
                        + provider.getName() + "': " + clash.getClass().getName()
                        + " and " + provider.getClass().getName()
                        + " — getName() is the selection key and must be unique");
            }
        }
    }

    /**
     * Resolved once at startup rather than per call, so a misconfiguration is a
     * boot failure with a clear message instead of an exception on the first
     * candle fetch of a trading day.
     */
    @PostConstruct
    void resolve() {
        if (byName.isEmpty()) {
            throw new IllegalStateException(
                    "No MarketDataProvider beans are registered. Check broker.active / "
                            + "backtest.data-source — every provider is gated on one of them.");
        }

        if (!configuredName.isEmpty()) {
            active = byName.get(key(configuredName));
            if (active == null) {
                throw new IllegalStateException("market.data.provider='" + configuredName
                        + "' does not match any registered provider. Registered: " + byName.values().stream()
                        .map(MarketDataProvider::getName).sorted().toList());
            }
            log.info("[market-data] provider={} (explicitly selected by market.data.provider)", active.getName());
            return;
        }

        if (byName.size() == 1) {
            active = byName.values().iterator().next();
            log.info("[market-data] provider={} (the only one registered)", active.getName());
            return;
        }

        for (String preferred : DEFAULT_PRECEDENCE) {
            MarketDataProvider candidate = byName.get(key(preferred));
            if (candidate != null) {
                active = candidate;
                log.info("[market-data] provider={} (default precedence; registered: {}). "
                                + "Set market.data.provider to override.",
                        active.getName(), registeredNames());
                return;
            }
        }

        throw new IllegalStateException("Several MarketDataProviders are registered " + registeredNames()
                + " and none is in the default precedence " + DEFAULT_PRECEDENCE
                + ". Set market.data.provider to say which one to use.");
    }

    /** The provider every candle fetch goes through. Never null after startup. */
    public MarketDataProvider active() {
        return Objects.requireNonNull(active, "MarketDataProviderFactory was not initialised");
    }

    /** Names of every registered provider, sorted — for logs and error messages. */
    public List<String> registeredNames() {
        return byName.values().stream().map(MarketDataProvider::getName).sorted().toList();
    }

    private static String key(String name) {
        return name.toUpperCase(Locale.ROOT);
    }
}
