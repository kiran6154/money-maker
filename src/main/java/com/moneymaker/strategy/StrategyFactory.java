package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeConfig;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * Resolves the {@link Strategy} to run for a given
 * {@link TradeConfigCombinedDTO} based on
 * {@link TradeConfig#getStratergyId()}.
 */
@Slf4j
@Component
public class StrategyFactory {

    private final Map<Integer, Strategy> strategiesById;

    public StrategyFactory(List<Strategy> strategies) {
        this.strategiesById = strategies.stream()
                .collect(Collectors.toUnmodifiableMap(Strategy::getId, Function.identity()));
        log.info("Registered strategies: {}", strategiesById.keySet());
    }

    /**
     * Returns the registered strategy ids in ascending order — used by the
     * trade-config admin UI to populate the strategy dropdown without
     * hardcoding the list.
     */
    public List<Integer> availableStrategyIds() {
        return strategiesById.keySet().stream().sorted().toList();
    }

    public Strategy get(Integer strategyId) {
        if (strategyId == null) {
            throw new IllegalArgumentException("strategyId is null");
        }
        Strategy strategy = strategiesById.get(strategyId);
        if (strategy == null) {
            throw new IllegalArgumentException("No strategy registered for id=" + strategyId);
        }
        return strategy;
    }

    /**
     * Resolve the strategy from the combined DTO and execute it.
     *
     * <p>The id comes from {@link TradeConfigCombinedDTO#getStrategyId()} — the
     * strategy this DTO was fanned out for — not from
     * {@code TradeConfig.stratergyId} directly. A config tagged with several
     * strategies arrives here once per tag, and reading the config's primary id
     * would run the same strategy every time. The DTO getter falls back to
     * {@code stratergyId} when nothing was tagged, so an untagged config
     * dispatches exactly as it did before changeset 031.</p>
     */
    public void execute(TradeConfigCombinedDTO config, LocalDateTime asOf) {
        if (config == null || config.getTradeConfig() == null) {
            throw new IllegalArgumentException("TradeConfigCombinedDTO or its TradeConfig is null");
        }
        Integer id = config.getStrategyId();
        Strategy strategy = get(id);
        log.debug("Dispatching tradeConfigId={} to strategy id={} ({}) asOf={}",
                config.getTradeConfig().getId(), id, strategy.getClass().getSimpleName(), asOf);
        strategy.execute(config, asOf);
    }
}

