package com.moneymaker.dto;

import com.moneymaker.shared.data.SharedData;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class AllTimeFramedto {
    private Integer timePeriod;
    private Integer sma;
    private static Map<Integer, List<Integer>> timeframeToSmaMap= new HashMap<>();
static {
    if (SharedData.allTimeFrameMap == null) {
        throw new IllegalStateException("SharedData.allTimeFrameList must be initialized before AllTimeFramedto static initialization");
    }
    timeframeToSmaMap.put(5, List.of(50, 100, 200, 500));
    timeframeToSmaMap.put(10, List.of(50, 100, 200, 500));
    timeframeToSmaMap.put(15, List.of(50, 100, 200));

    AllTimeFramedto dto= new AllTimeFramedto(timeframeToSmaMap);
    SharedData.allTimeFrameMap=timeframeToSmaMap;

}
    public static void initializeDefaults() {
        // Intentionally empty. Calling this method forces class initialization.
    }

    public AllTimeFramedto(Map<Integer, List<Integer>> timeframeToSmaMap) {
       this. timeframeToSmaMap=timeframeToSmaMap;
    }



    public Integer getTimePeriod() {
        return timePeriod;
    }

    public void setTimePeriod(Integer timePeriod) {
        this.timePeriod = timePeriod;
    }

    public Integer getSma() {
        return sma;
    }

    public void setSma(Integer sma) {
        this.sma = sma;
    }

}
