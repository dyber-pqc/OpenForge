// Formal verification properties for ML-KEM accelerator
// Checks FIPS 140-3 compliance and security properties

module mlkem_formal_checks (
    input wire clk,
    input wire rst_n,
    input wire zeroize,
    input wire [3:0] state,
    input wire self_test_done,
    input wire crypto_enable,
    input wire error,
    input wire health_test_fail
);

    // ── Key Zeroization ─────────────────────────────────────────
    // Key material must be cleared within 100 cycles of zeroize
    // (covered by openforge crypto_properties.sv library)

    // ── Self-Test Gating ────────────────────────────────────────
    // No crypto operations until self-test passes
    assert property (@(posedge clk)
        !self_test_done |-> !crypto_enable
    ) else $error("FIPS: Crypto enabled before self-test!");

    // ── Error State Sticky ──────────────────────────────────────
    // Error state (4'hF) can only exit via reset
    assert property (@(posedge clk) disable iff (!rst_n)
        (state == 4'hF) |=> (state == 4'hF)
    ) else $error("FIPS: Error state is not sticky!");

    // ── Valid State Check ───────────────────────────────────────
    // FSM must never enter undefined states
    assert property (@(posedge clk)
        state inside {4'd0, 4'd1, 4'd2, 4'd3, 4'd4,
                      4'd5, 4'd6, 4'd7, 4'd8, 4'd9, 4'd15}
    ) else $error("FSM: Invalid state detected!");

    // ── RNG Health Gating ───────────────────────────────────────
    // Crypto must be disabled when RNG health test fails
    assert property (@(posedge clk)
        health_test_fail |-> !crypto_enable
    ) else $error("FIPS: Crypto active during RNG health failure!");

    // ── No Crypto During Zeroization ────────────────────────────
    assert property (@(posedge clk)
        zeroize |-> (state == 4'd0 || state == 4'hF)
    ) else $error("Zeroization must return to idle or error state!");

endmodule
