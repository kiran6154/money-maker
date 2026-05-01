package com.moneymaker.login.config;

import com.zerodhatech.kiteconnect.KiteConnect;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class HttpClientConfig {

    @Bean
    public RestTemplate brokerRestTemplate(RestTemplateBuilder builder) {
        return builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(20))
                .build();
    }

    @Bean(name = "sharedKiteConnect")
    @ConditionalOnProperty(name = "broker.zerodha.enabled", havingValue = "true", matchIfMissing = true)
    public KiteConnect kiteConnect(BrokerProperties properties) {
        return new KiteConnect(properties.getZerodha().getApiKey());
    }
}

