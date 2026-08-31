package com.moneymaker.repository;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Boots the real JPA metamodel (H2) and exercises the hand-written
 * {@code @Query} deletes, so a JPQL path that does not exist on the entity —
 * e.g. {@code SmaTimeframe.tradeConfigId}, which is actually the relation
 * {@code tradeConfig.id} — fails HERE instead of at first click in the running
 * app. Mocked-repository unit tests can never catch that class of bug: the
 * query string is only parsed by a live {@code EntityManager}.
 *
 * <p>Runs against empty tables — the point is query <i>translation</i>, not
 * data. Liquibase is off; Hibernate creates the schema from the entities.</p>
 */
@DataJpaTest(properties = {
        "spring.liquibase.enabled=false",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
class RepositoryQueryBootstrapTest {

    @Autowired SmaTimeframeRepository smaTimeframeRepository;
    @Autowired TradeOrderRepository tradeOrderRepository;

    @Test
    @DisplayName("every declared @Query and derived method translates against the real entity metamodel")
    void repositoriesBootstrap() {
        // The assertion is the context refresh itself: Spring Data parses and
        // validates every @Query and derived method name when it builds the
        // repository beans, so a bad JPQL path fails this test before these
        // lines run. No schema needed — translation, not execution.
        assertThat(smaTimeframeRepository).isNotNull();
        assertThat(tradeOrderRepository).isNotNull();
    }
}
