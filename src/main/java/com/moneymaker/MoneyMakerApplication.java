package com.moneymaker;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class MoneyMakerApplication {

    public static void main(String[] args) {
        SpringApplication.run(MoneyMakerApplication.class, args);
    }
}

