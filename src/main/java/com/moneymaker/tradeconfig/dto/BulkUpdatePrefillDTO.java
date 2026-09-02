package com.moneymaker.tradeconfig.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

/**
 * What the bulk-edit panel prefils from: the current state of the matched
 * config set, folded per field.
 *
 * <p>{@link #values} holds only fields <b>every</b> matched config agrees on
 * (numbers compared by value, not scale). A field the fleet disagrees on is
 * listed in {@link #mixedFields} and left out of {@code values}; a field that
 * is null on every row appears in neither — the input stays blank in both
 * cases, but the panel can label "mixed" differently from "unset".</p>
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class BulkUpdatePrefillDTO {

    /** Configs the selector matches — the set an apply with it would write. */
    private long matched;

    /** field name → shared value, rendered as a plain string. */
    private Map<String, String> values;

    /** Fields whose value differs across the matched set. */
    private List<String> mixedFields;
}
