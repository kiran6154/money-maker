package com.moneymaker.login.util;

import com.moneymaker.login.exception.BrokerLoginException;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * RFC 6238 reference vectors anchored to known timestamps prove the
 * generator's math without leaning on a live broker.
 *
 * <p>The reference HMAC-SHA1 key used in the RFC is {@code "12345678901234567890"}.
 * In Base32 that's {@code GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ}. The expected
 * OTPs at the published timestamps are 6-digit codes lifted from the RFC.
 */
class TotpGeneratorTest {

    /** RFC 6238 reference secret, base32-encoded. */
    private static final String REF_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";

    @Test
    void rfc6238_vector_at_unix_timestamp_59() {
        // From RFC 6238 Appendix B, T = 59 (sha1 column) → "94287082"
        // Truncated to 6 digits → "287082".
        String otp = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(59L));
        assertThat(otp).isEqualTo("287082");
    }

    @Test
    void rfc6238_vector_at_unix_timestamp_1111111109() {
        // T = 1111111109 → "07081804" → "081804".
        String otp = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(1111111109L));
        assertThat(otp).isEqualTo("081804");
    }

    @Test
    void rfc6238_vector_at_unix_timestamp_1234567890() {
        // T = 1234567890 → "89005924" → "005924".
        String otp = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(1234567890L));
        assertThat(otp).isEqualTo("005924");
    }

    @Test
    void otp_is_always_six_digits_zero_padded() {
        // Pick a timestamp where the binary code mod 1M starts with a leading zero.
        String otp = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(1111111109L));
        assertThat(otp).hasSize(6);
        assertThat(otp).matches("\\d{6}");
    }

    @Test
    void otp_changes_when_the_30_second_step_advances() {
        // Two timestamps within the same 30s window → same OTP.
        String at0   = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(60L));
        String at29  = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(89L));
        String at30  = TotpGenerator.generate(REF_SECRET, Instant.ofEpochSecond(90L));
        assertThat(at0).isEqualTo(at29);
        assertThat(at0).isNotEqualTo(at30);
    }

    @Test
    void blank_secret_is_rejected_with_typed_exception() {
        assertThatThrownBy(() -> TotpGenerator.generate(null, Instant.now()))
                .isInstanceOf(BrokerLoginException.class)
                .hasMessageContaining("TOTP secret is not configured");
        assertThatThrownBy(() -> TotpGenerator.generate("", Instant.now()))
                .isInstanceOf(BrokerLoginException.class);
        assertThatThrownBy(() -> TotpGenerator.generate("   ", Instant.now()))
                .isInstanceOf(BrokerLoginException.class);
    }

    @Test
    void invalid_base32_character_is_rejected() {
        // '1' is not in the RFC 4648 Base32 alphabet (which is A-Z + 2-7).
        // The inner base32Decode throws BrokerLoginException("Invalid Base32 character: ..."),
        // and the outer try/catch wraps it as "Failed to generate TOTP". Assert the wrapping
        // contract — both messages are part of the user-visible failure trail.
        assertThatThrownBy(() -> TotpGenerator.generate("ABCDE1FG", Instant.now()))
                .isInstanceOf(BrokerLoginException.class)
                .hasMessageContaining("Failed to generate TOTP")
                .hasRootCauseInstanceOf(BrokerLoginException.class)
                .hasRootCauseMessage("Invalid Base32 character in TOTP secret: 1");
    }

    @Test
    void spaces_in_secret_are_tolerated() {
        // Users sometimes paste secrets in 4-char groups separated by spaces.
        // The generator strips them.
        String withSpaces    = "GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ";
        String withoutSpaces = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
        Instant t = Instant.ofEpochSecond(59L);
        assertThat(TotpGenerator.generate(withSpaces, t))
                .isEqualTo(TotpGenerator.generate(withoutSpaces, t));
    }

    @Test
    void lowercase_secret_is_normalised_to_uppercase() {
        Instant t = Instant.ofEpochSecond(59L);
        assertThat(TotpGenerator.generate(REF_SECRET.toLowerCase(), t))
                .isEqualTo(TotpGenerator.generate(REF_SECRET, t));
    }

    @Test
    void no_args_overload_uses_current_time() {
        // Smoke test only — we can't assert a specific value, but we can prove
        // the overload is wired and returns a 6-digit code.
        String otp = TotpGenerator.generate(REF_SECRET);
        assertThat(otp).matches("\\d{6}");
    }
}
