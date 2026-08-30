package com.moneymaker.broker.zerodha;

import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.repository.InstrumentDetailsRepository;
import com.moneymaker.state.AppState;
import com.moneymaker.telegram.NotificationService;
import com.zerodhatech.kiteconnect.KiteConnect;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Pins the NFO contract lookup that replaced the {@code return null} stub
 * (ORDERS_AND_POSITIONS.md pending item; GAPS #1 "Depends on").
 *
 * <p>The two success fixtures are copied verbatim out of the bundled Kite dump
 * ({@code com/moneymaker/data/download/instruments.csv}) and are deliberately the
 * <b>same underlying, same strike, same option type</b> — they differ only in
 * expiry:
 *
 * <pre>
 *   14598658 , NIFTY2660223400CE , 2026-06-02 , 23400 , CE   (weekly)
 *   20401922 , NIFTY26JUN23400CE , 2026-06-30 , 23400 , CE   (monthly)
 * </pre>
 *
 * <p>That pair is the whole argument for resolving by token instead of formatting
 * a symbol: a formatter fed (NIFTY, 23400, CE) has no way to produce both strings,
 * and picking either rule silently trades the wrong expiry half the time.
 */
class ZerodhaTradingSymbolResolutionTest {

    private InstrumentDetailsRepository instruments;
    private ZerodhaOrderPlacementService service;

    @BeforeEach
    void setUp() {
        instruments = mock(InstrumentDetailsRepository.class);
        service = new ZerodhaOrderPlacementService(
                mock(KiteConnect.class), mock(AppState.class), mock(NotificationService.class), instruments);
    }

    /* ---------------- fixtures ---------------- */

    private static InstrumentDetails dumpRow(int token, String symbol, String expiry,
                                             String strike, String type, String exchange) {
        InstrumentDetails row = new InstrumentDetails();
        row.setInstrumentToken(token);
        row.setExchangeToken(token / 256);
        row.setTradingSymbol(symbol);
        row.setName("NIFTY");
        row.setLastPrice(BigDecimal.ZERO);
        row.setExpiry(expiry);
        row.setStrike(new BigDecimal(strike));
        row.setTickSize(new BigDecimal("0.05"));
        row.setLotSize(new BigDecimal("65"));
        row.setInstrumentType(type);
        row.setSegment("NFO-OPT");
        row.setExchange(exchange);
        return row;
    }

    private static TradeOrder order(String optionToken, Integer strike, String optionType) {
        TradeOrder o = new TradeOrder();
        o.setId(9001L);
        o.setInstrumentName("NIFTY");
        o.setOptionToken(optionToken);
        o.setOptionStrike(strike);
        o.setOptionType(optionType);
        return o;
    }

    /* ---------------- the two shapes a formatter cannot both produce ---------------- */

    @Test
    @DisplayName("weekly expiry resolves to the compressed NIFTY2660223400CE form")
    void resolves_weekly_contract() {
        when(instruments.findById(14598658)).thenReturn(Optional.of(
                dumpRow(14598658, "NIFTY2660223400CE", "2026-06-02", "23400", "CE", "NFO")));

        ZerodhaOrderPlacementService.Contract contract =
                service.resolveContract(order("14598658", 23400, "CE"));

        assertThat(contract).isNotNull();
        assertThat(contract.tradingSymbol()).isEqualTo("NIFTY2660223400CE");
        assertThat(contract.exchange()).isEqualTo("NFO");
    }

    @Test
    @DisplayName("monthly expiry on the same strike/type resolves to the NIFTY26JUN23400CE form")
    void resolves_monthly_contract() {
        when(instruments.findById(20401922)).thenReturn(Optional.of(
                dumpRow(20401922, "NIFTY26JUN23400CE", "2026-06-30", "23400", "CE", "NFO")));

        ZerodhaOrderPlacementService.Contract contract =
                service.resolveContract(order("20401922", 23400, "CE"));

        assertThat(contract).isNotNull();
        assertThat(contract.tradingSymbol()).isEqualTo("NIFTY26JUN23400CE");
    }

    @Test
    @DisplayName("exchange comes from the dump row, so a BFO contract is not routed to NFO")
    void exchange_is_read_from_the_row() {
        when(instruments.findById(1234567)).thenReturn(Optional.of(
                dumpRow(1234567, "SENSEX2660282000CE", "2026-06-02", "82000", "CE", "BFO")));

        ZerodhaOrderPlacementService.Contract contract =
                service.resolveContract(order("1234567", 82000, "CE"));

        assertThat(contract).isNotNull();
        assertThat(contract.exchange()).isEqualTo("BFO");
    }

    @Test
    @DisplayName("a row with no exchange falls back to NFO rather than sending a null exchange")
    void missing_exchange_falls_back_to_nfo() {
        when(instruments.findById(14598658)).thenReturn(Optional.of(
                dumpRow(14598658, "NIFTY2660223400CE", "2026-06-02", "23400", "CE", null)));

        assertThat(service.resolveContract(order("14598658", 23400, "CE")).exchange()).isEqualTo("NFO");
    }

    /* ---------------- refusals: every one of these must NOT reach the broker ---------------- */

    @Test
    @DisplayName("no option_token on the ledger row -> refuse")
    void refuses_when_token_missing() {
        assertThat(service.resolveContract(order(null, 23400, "CE"))).isNull();
        assertThat(service.resolveContract(order("   ", 23400, "CE"))).isNull();
    }

    @Test
    @DisplayName("a HISTORICAL_ICICI natural key is not a broker token -> refuse")
    void refuses_historical_natural_key() {
        assertThat(service.resolveContract(order("NIFTY|NFO|2024-01-04|23400|CE", 23400, "CE"))).isNull();
    }

    @Test
    @DisplayName("token absent from instrument_details (stale dump) -> refuse")
    void refuses_when_dump_has_no_row() {
        when(instruments.findById(14598658)).thenReturn(Optional.empty());
        assertThat(service.resolveContract(order("14598658", 23400, "CE"))).isNull();
    }

    @Test
    @DisplayName("dump row carries no tradingsymbol -> refuse")
    void refuses_when_symbol_blank() {
        when(instruments.findById(14598658)).thenReturn(Optional.of(
                dumpRow(14598658, "  ", "2026-06-02", "23400", "CE", "NFO")));
        assertThat(service.resolveContract(order("14598658", 23400, "CE"))).isNull();
    }

    @Test
    @DisplayName("token now names a different strike (dump re-seeded) -> refuse, do not trade the wrong leg")
    void refuses_on_strike_mismatch() {
        when(instruments.findById(14598658)).thenReturn(Optional.of(
                dumpRow(14598658, "NIFTY2660223500CE", "2026-06-02", "23500", "CE", "NFO")));
        assertThat(service.resolveContract(order("14598658", 23400, "CE"))).isNull();
    }

    @Test
    @DisplayName("token now names the other option type -> refuse")
    void refuses_on_option_type_mismatch() {
        when(instruments.findById(14598914)).thenReturn(Optional.of(
                dumpRow(14598914, "NIFTY2660223400PE", "2026-06-02", "23400", "PE", "NFO")));
        assertThat(service.resolveContract(order("14598914", 23400, "CE"))).isNull();
    }

    @Test
    @DisplayName("a ledger row that never recorded strike/type still resolves — absence is not a mismatch")
    void null_ledger_fields_do_not_block() {
        when(instruments.findById(14598658)).thenReturn(Optional.of(
                dumpRow(14598658, "NIFTY2660223400CE", "2026-06-02", "23400", "CE", "NFO")));

        assertThat(service.resolveContract(order("14598658", null, null)))
                .isNotNull()
                .extracting(ZerodhaOrderPlacementService.Contract::tradingSymbol)
                .isEqualTo("NIFTY2660223400CE");
    }
}
