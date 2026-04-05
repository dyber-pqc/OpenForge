// ============================================
// OpenForge Cryptographic Property Library
// ============================================
//
// SystemVerilog Assertions for verifying security properties
// of cryptographic hardware implementations.
//
// Usage: Include in SymbiYosys formal verification flow.
// See templates/crypto_verify.sby for integration.
//
// Copyright 2026 Dyber Inc. Licensed under GPL-3.0.

// ===========================================
// CONSTANT-TIME PROPERTIES
// ===========================================

// Control flow must not depend on secret
property ct_no_secret_branch(clk, secret, branch_cond);
    @(posedge clk)
    $stable(secret) |-> $stable(branch_cond);
endproperty

// Memory address must not depend on secret
property ct_no_secret_addr(clk, secret, addr);
    @(posedge clk)
    $stable(secret) |-> $stable(addr);
endproperty

// Execution time must not depend on secret
property ct_fixed_latency(clk, start, done, secret, LATENCY);
    @(posedge clk)
    start |-> ##LATENCY done;
endproperty


// ===========================================
// KEY HANDLING PROPERTIES
// ===========================================

// Key must be zeroized within N cycles of zeroize signal
property key_zeroization(clk, zeroize, key_reg, MAX_CYCLES);
    @(posedge clk)
    zeroize |-> ##[1:MAX_CYCLES] (key_reg == '0);
endproperty

// Key must not appear on any external interface
property key_isolation(clk, key_reg, output_bus);
    @(posedge clk)
    !(output_bus == key_reg);
endproperty

// Key register must only be written via secure path
property key_write_control(clk, key_reg, key_write_en, secure_path);
    @(posedge clk)
    $changed(key_reg) |-> (key_write_en && secure_path);
endproperty


// ===========================================
// FSM INTEGRITY PROPERTIES
// ===========================================

// FSM must not enter invalid state
property fsm_valid_state(clk, state, VALID_STATES);
    @(posedge clk)
    state inside {VALID_STATES};
endproperty

// Error state must be sticky (no escape without reset)
property error_state_sticky(clk, rst, state, ERROR_STATE);
    @(posedge clk) disable iff (rst)
    (state == ERROR_STATE) |=> (state == ERROR_STATE);
endproperty


// ===========================================
// NTT / POLYNOMIAL PROPERTIES
// ===========================================

// Butterfly correctness (Cooley-Tukey)
property ntt_butterfly_ct(clk, valid, a_in, b_in, w, q, a_out, b_out);
    @(posedge clk)
    valid |-> (
        (a_out == ((a_in + (w * b_in)) % q)) &&
        (b_out == ((a_in - (w * b_in) + q) % q))
    );
endproperty

// Modular reduction bounds
property mod_reduction_bounds(clk, input_val, output_val, q);
    @(posedge clk)
    (output_val < q) && (output_val == (input_val % q));
endproperty


// ===========================================
// RNG HEALTH PROPERTIES
// ===========================================

// RNG output must eventually change
property rng_liveness(clk, rng_valid, rng_data, MAX_CYCLES);
    @(posedge clk)
    rng_valid |-> ##[1:MAX_CYCLES] $changed(rng_data);
endproperty

// RNG must not output constant
property rng_no_constant(clk, rng_valid, rng_data);
    @(posedge clk)
    rng_valid |=> !$stable(rng_data);
endproperty


// ===========================================
// SELF-TEST PROPERTIES
// ===========================================

// Self-test must run on power-up
property self_test_on_powerup(clk, rst, self_test_start);
    @(posedge clk)
    $rose(!rst) |=> ##[1:10] self_test_start;
endproperty

// Crypto operations blocked until self-test passes
property crypto_blocked_until_tested(clk, self_test_done, crypto_enable);
    @(posedge clk)
    !self_test_done |-> !crypto_enable;
endproperty
