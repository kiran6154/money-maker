package com.moneymaker.entity;


import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Entity
@Table(name = "instrument")
@Getter
@Setter
public class Instrument {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "ins_name")
    private String insName;

    @Column(name = "ins_id", unique = true)
    private String insId;

    @Column(name = "lot_qty")
    private Integer lotQty;

    @Column(name = "strike_points")
    private BigDecimal strikePoints;

    // Getters and setters
    // (Omitted for brevity)
}