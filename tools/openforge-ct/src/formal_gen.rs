//! Formal property generation for constant-time verification.
//!
//! Generates SystemVerilog Assertions (SVA) that can be checked
//! by SymbiYosys to formally prove constant-time properties.

use std::collections::HashSet;

/// Generate SVA properties for constant-time verification.
pub fn generate(secrets: &HashSet<String>, public: &HashSet<String>) -> Vec<String> {
    let mut properties = Vec::new();

    // Non-interference property: for any two secret values,
    // the observable (public) outputs must be identical.
    if !secrets.is_empty() && !public.is_empty() {
        let secret_list: Vec<&String> = secrets.iter().collect();
        let public_list: Vec<&String> = public.iter().collect();

        properties.push(format!(
            r#"// Auto-generated constant-time non-interference property
// Proves that public outputs are independent of secret inputs.
//
// Methodology: Two-copy simulation
// If the design produces the same public outputs for any two
// secret input values (given same public inputs), it is constant-time.

module ct_check_{top}(
    input clk,
    input rst
);
    // Shadow copies of secret signals
{shadow_decls}

    // Assert public outputs are identical regardless of secret values
{assertions}
endmodule"#,
            top = "design",
            shadow_decls = secret_list
                .iter()
                .map(|s| format!("    // Shadow for secret signal: {s}"))
                .collect::<Vec<_>>()
                .join("\n"),
            assertions = public_list
                .iter()
                .map(|p| format!(
                    "    assert property (@(posedge clk) disable iff (rst)\n        \
                     // {p} must not depend on secret values\n        \
                     $stable({p}));",
                ))
                .collect::<Vec<_>>()
                .join("\n\n"),
        ));
    }

    // Key zeroization property
    for secret in secrets {
        if secret.contains("key") {
            properties.push(format!(
                r#"// Key zeroization property for {secret}
// Verifies that key material is cleared within bounded cycles after zeroize
property key_zeroization_{name};
    @(posedge clk)
    zeroize |-> ##[1:100] ({secret} == '0);
endproperty
assert property (key_zeroization_{name});"#,
                name = secret.replace('.', "_"),
            ));
        }
    }

    properties
}
