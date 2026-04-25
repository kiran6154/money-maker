package com.moneymaker.login.util;

import com.moneymaker.login.exception.BrokerLoginException;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.time.Instant;

/**
 * Self-contained RFC-6238 TOTP generator (HMAC-SHA1, 6 digits, 30s step).
 * Shared by all broker adapters that mint a daily access token from a
 * Base32 TOTP secret (Groww, Angel One SmartAPI, etc.).
 */
public final class TotpGenerator {

    private TotpGenerator() {}

    public static String generate(String base32Secret) {
        return generate(base32Secret, Instant.now());
    }

    public static String generate(String base32Secret, Instant at) {
        if (base32Secret == null || base32Secret.isBlank()) {
            throw new BrokerLoginException("TOTP secret is not configured", "MISSING_TOTP_SECRET", null);
        }
        try {
            byte[] key = base32Decode(base32Secret.replace(" ", "").toUpperCase());
            long counter = at.getEpochSecond() / 30L;
            byte[] data = ByteBuffer.allocate(8).putLong(counter).array();

            Mac mac = Mac.getInstance("HmacSHA1");
            mac.init(new SecretKeySpec(key, "HmacSHA1"));
            byte[] hash = mac.doFinal(data);

            int offset = hash[hash.length - 1] & 0x0F;
            int binary =
                    ((hash[offset]     & 0x7F) << 24) |
                    ((hash[offset + 1] & 0xFF) << 16) |
                    ((hash[offset + 2] & 0xFF) <<  8) |
                    ( hash[offset + 3] & 0xFF);
            int otp = binary % 1_000_000;
            return String.format("%06d", otp);
        } catch (Exception e) {
            throw new BrokerLoginException("Failed to generate TOTP", "TOTP_ERROR", e);
        }
    }

    private static final String B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

    private static byte[] base32Decode(String s) {
        s = s.replace("=", "");
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int buffer = 0, bitsLeft = 0;
        for (char c : s.toCharArray()) {
            int idx = B32.indexOf(c);
            if (idx < 0) throw new BrokerLoginException("Invalid Base32 character in TOTP secret: " + c);
            buffer = (buffer << 5) | idx;
            bitsLeft += 5;
            if (bitsLeft >= 8) {
                bitsLeft -= 8;
                out.write((buffer >> bitsLeft) & 0xFF);
            }
        }
        return out.toByteArray();
    }
}

