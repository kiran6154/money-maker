package com.moneymaker.util;

import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Unit tests for {@link ConverterUtility}. Every {@code Object[]} → DTO mapper
 * in the codebase routes through these three methods so a regression here is
 * a regression in every native query result mapping.
 */
class ConverterUtilityTest {

    @Nested
    class ToInteger {
        @Test
        void returns_null_for_null_input() {
            assertThat(ConverterUtility.toInteger(null)).isNull();
        }

        @Test
        void passes_through_Integer_unchanged() {
            assertThat(ConverterUtility.toInteger(Integer.valueOf(42))).isEqualTo(42);
        }

        @Test
        void narrows_Long_to_Integer() {
            assertThat(ConverterUtility.toInteger(Long.valueOf(123L))).isEqualTo(123);
        }

        @Test
        void parses_decimal_string_as_integer_only_when_no_fraction() {
            // Integer.parseInt rejects "12.5" — confirm the contract.
            assertThatThrownBy(() -> ConverterUtility.toInteger("12.5"))
                    .isInstanceOf(NumberFormatException.class);
            assertThat(ConverterUtility.toInteger("42")).isEqualTo(42);
        }

        @Test
        void rejects_unsupported_types() {
            assertThatThrownBy(() -> ConverterUtility.toInteger(new Object()))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("Cannot convert");
        }
    }

    @Nested
    class ToString {
        @Test
        void returns_null_for_null_input() {
            assertThat(ConverterUtility.toString(null)).isNull();
        }

        @Test
        void invokes_toString_on_object() {
            assertThat(ConverterUtility.toString(42)).isEqualTo("42");
            assertThat(ConverterUtility.toString("hello")).isEqualTo("hello");
        }
    }

    @Nested
    class ToBigDecimal {
        @Test
        void returns_null_for_null_input() {
            assertThat(ConverterUtility.toBigDecimal(null)).isNull();
        }

        @Test
        void passes_through_BigDecimal_unchanged() {
            BigDecimal in = new BigDecimal("12.3400");
            BigDecimal out = ConverterUtility.toBigDecimal(in);
            // Identity (same reference); confirms zero-copy fast path.
            assertThat(out).isSameAs(in);
            // Scale preserved.
            assertThat(out.scale()).isEqualTo(4);
        }

        @Test
        void converts_Integer_via_string_so_scale_is_zero() {
            BigDecimal out = ConverterUtility.toBigDecimal(42);
            assertThat(out).isEqualTo(new BigDecimal("42"));
        }

        @Test
        void converts_Double_via_string_preserving_textual_precision() {
            // Going via toString() avoids the binary-representation surprise
            // (new BigDecimal(0.1) gives 0.10000000…, but new BigDecimal("0.1") gives 0.1).
            BigDecimal out = ConverterUtility.toBigDecimal(Double.valueOf(0.1));
            assertThat(out).isEqualTo(new BigDecimal("0.1"));
        }

        @Test
        void parses_string_directly() {
            assertThat(ConverterUtility.toBigDecimal("12.50")).isEqualTo(new BigDecimal("12.50"));
        }

        @Test
        void rejects_unsupported_types() {
            assertThatThrownBy(() -> ConverterUtility.toBigDecimal(new Object()))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("Cannot convert");
        }
    }
}
