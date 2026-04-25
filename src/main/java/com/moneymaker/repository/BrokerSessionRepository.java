package com.moneymaker.repository;

import com.moneymaker.entity.BrokerSessionEntity;
import com.moneymaker.login.model.Broker;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface BrokerSessionRepository extends JpaRepository<BrokerSessionEntity, Integer> {

    Optional<BrokerSessionEntity> findByBroker(Broker broker);

    Optional<BrokerSessionEntity> findFirstByLoggedInTrue();

    @Modifying
    @Query("update BrokerSessionEntity b set b.loggedIn = false where b.broker <> :broker")
    int clearLoggedInExcept(Broker broker);

    @Modifying
    @Query("update BrokerSessionEntity b set b.loggedIn = false")
    int clearAllLoggedIn();
}

