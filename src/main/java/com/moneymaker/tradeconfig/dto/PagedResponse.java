package com.moneymaker.tradeconfig.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class PagedResponse<T> {
    private List<T> items;
    private int page;
    private int pageSize;
    private long totalItems;
    private int totalPages;
}
