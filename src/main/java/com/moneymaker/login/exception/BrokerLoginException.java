package com.moneymaker.login.exception;

/**
 * Wraps any error raised while talking to a broker login API so callers
 * can react uniformly regardless of broker.
 */
public class BrokerLoginException extends RuntimeException {

    private final String errorCode;

    public BrokerLoginException(String message) {
        this(message, "BROKER_LOGIN_ERROR", null);
    }

    public BrokerLoginException(String message, Throwable cause) {
        this(message, "BROKER_LOGIN_ERROR", cause);
    }

    public BrokerLoginException(String message, String errorCode, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode;
    }

    public String getErrorCode() {
        return errorCode;
    }
}

