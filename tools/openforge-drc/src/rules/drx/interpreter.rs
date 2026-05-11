//! Interpreter that lowers a parsed DRX `Stmt` list into a `RuleDeck`.
//!
//! Conceptually this evaluates each statement in declaration order in a tiny
//! environment. Layer expressions evaluate to either a primitive layer name
//! (already in `RuleDeck::layers`) or a freshly-named derived layer that
//! gets pushed onto `RuleDeck::derived`. Rule-emitting calls (`.output(...)`
//! at the end of a chain, or `.range(...)` for density) push entries onto
//! `RuleDeck::rules`.
//!
//! Anything we don't understand becomes a warning printed to stderr; the
//! deck still parses so users see a partial-coverage report rather than a
//! hard failure on a real-world deck.

use super::parser::{Expr, Stmt};
use crate::rules::ast::{BoolOp, DensityDirection, DerivedLayer, LayerSpec, Rule, RuleDeck};
use crate::{DrcError, Result};
use std::collections::HashMap;

/// A "layer" handle the interpreter passes around: either a name in
/// `RuleDeck::layers` (primitive) or a synthetic derived-layer name in
/// `RuleDeck::derived`. Either way it's a `String` the rule emits.
#[derive(Debug, Clone)]
struct LayerHandle {
    /// The layer name to use when emitting a Rule.
    name: String,
}

/// A pending rule-builder that accumulates filters/outputs through method
/// chaining. Most checks just produce a `Rule` directly when `.output` is
/// called; density first builds a (window, min, max) tuple from `.density`
/// and `.range`.
#[derive(Debug, Clone)]
enum Pending {
    /// `<layer>.width(0.17[, ...])` - awaits `.output("name","msg")`.
    Width { layer: String, min_um: f64 },
    /// `<layer>.space(0.17[, ...])`.
    Space { layer: String, min_um: f64 },
    /// `<inner>.enclosing(<outer>, 0.08)`. Note: in DRX, `inner.enclosing(outer)`
    /// means *inner* must enclose *outer*; for sky130-style "li1.enclosing(licon, 0.08)"
    /// we treat li1 as the outer, licon as the inner. Matches Rule::Enclosure semantics.
    Enclosing {
        outer: String,
        inner: String,
        min_um: f64,
    },
    /// Density: window in um. After `.range(min, max)` is called we emit two rules.
    Density { layer: String, window_um: f64 },
    /// Density with min/max already applied.
    DensityRanged {
        layer: String,
        window_um: f64,
        min: f64,
        max: f64,
    },
    /// `<layerA>.separation(layerB, min)` - inter-layer min spacing.
    Separation {
        layer_a: String,
        layer_b: String,
        min_um: f64,
    },
    /// `<layer>.area(min_um2)` - minimum polygon area.
    Area { layer: String, min_um2: f64 },
    /// `<outer>.overhang(<inner>, min)` - outer must overhang inner.
    Overhang {
        outer: String,
        inner: String,
        min_um: f64,
    },
    /// `<layer>.notch(min)` - minimum notch width within a single polygon.
    Notch { layer: String, min_um: f64 },
    /// A bare layer (no rule yet). Used as the value of a layer expression.
    Layer(LayerHandle),
}

struct Interp {
    deck: RuleDeck,
    /// Map from variable name to layer handle (primitive or derived).
    env: HashMap<String, LayerHandle>,
    /// Counter for synthetic derived-layer names.
    derived_counter: usize,
    /// Warnings collected during interpretation.
    warnings: Vec<String>,
}

impl Interp {
    fn new() -> Self {
        Interp {
            deck: RuleDeck::default(),
            env: HashMap::new(),
            derived_counter: 0,
            warnings: Vec::new(),
        }
    }

    fn fresh_derived(&mut self) -> String {
        let n = format!("__derived_{}", self.derived_counter);
        self.derived_counter += 1;
        n
    }

    fn warn(&mut self, msg: impl Into<String>) {
        let m = msg.into();
        eprintln!("warning: {m}");
        self.warnings.push(m);
    }

    fn run(&mut self, stmts: Vec<Stmt>) -> Result<()> {
        for stmt in stmts {
            match stmt {
                Stmt::Assign { name, expr, line } => match self.eval(&expr) {
                    Ok(Pending::Layer(h)) => {
                        self.env.insert(name, h);
                    }
                    Ok(other) => {
                        self.warn(format!(
                            "line {line}: assignment of non-layer value ({other:?}); ignored"
                        ));
                    }
                    Err(e) => {
                        self.warn(format!("line {line}: {e}"));
                    }
                },
                Stmt::Expr { expr, line } => match self.eval(&expr) {
                    Ok(Pending::Layer(_)) => {
                        // Bare layer expression with no output - silently ignore.
                    }
                    Ok(
                        Pending::Width { .. }
                        | Pending::Space { .. }
                        | Pending::Enclosing { .. }
                        | Pending::Separation { .. }
                        | Pending::Area { .. }
                        | Pending::Overhang { .. }
                        | Pending::Notch { .. },
                    ) => {
                        // A measurement chain that was never `.output()`-ed.
                        // Real decks always terminate with `.output(...)` -
                        // this is a no-op and a warning helps users notice.
                        self.warn(format!(
                            "line {line}: rule chain without .output(...); ignored"
                        ));
                    }
                    Ok(Pending::Density { .. } | Pending::DensityRanged { .. }) => {
                        self.warn(format!(
                            "line {line}: density chain without .output(...); ignored"
                        ));
                    }
                    Err(e) => {
                        self.warn(format!("line {line}: {e}"));
                    }
                },
            }
        }
        Ok(())
    }

    /// Evaluate an expression into a Pending value.
    fn eval(&mut self, e: &Expr) -> std::result::Result<Pending, String> {
        match e {
            Expr::Ident(n) => self
                .env
                .get(n)
                .cloned()
                .map(Pending::Layer)
                .ok_or_else(|| format!("unknown identifier '{n}'")),
            Expr::Num(_) | Expr::Str(_) | Expr::Sym(_) => {
                Err("bare literal at expression position".into())
            }
            Expr::Call {
                name,
                args,
                kwargs: _,
            } => self.eval_call(name, args),
            Expr::MethodCall {
                recv,
                method,
                args,
                kwargs,
            } => {
                let recv_val = self.eval(recv)?;
                self.eval_method(recv_val, method, args, kwargs)
            }
        }
    }

    fn eval_call(&mut self, name: &str, args: &[Expr]) -> std::result::Result<Pending, String> {
        match name {
            "input" => {
                // input(layer) or input(layer, datatype)
                if args.is_empty() || args.len() > 2 {
                    return Err(format!("input() takes 1 or 2 args, got {}", args.len()));
                }
                let layer = lit_int(&args[0])?;
                let dtype = if args.len() == 2 {
                    lit_int(&args[1])?
                } else {
                    0
                };
                let synth_name = format!("L{layer}D{dtype}");
                self.deck.layers.insert(
                    synth_name.clone(),
                    LayerSpec {
                        layer: layer as u16,
                        datatype: dtype as u16,
                    },
                );
                Ok(Pending::Layer(LayerHandle { name: synth_name }))
            }
            "report" => {
                // `report("name")` is a header; capture as deck name.
                if let Some(Expr::Str(s)) = args.first() {
                    self.deck.name = s.clone();
                }
                // Returns "nothing" — represent as a no-op layer so chained
                // calls fail loudly. For now treat as dummy.
                Err("report() does not yield a layer".into())
            }
            other => Err(format!("unknown top-level function '{other}'")),
        }
    }

    fn eval_method(
        &mut self,
        recv: Pending,
        method: &str,
        args: &[Expr],
        _kwargs: &[(String, Expr)],
    ) -> std::result::Result<Pending, String> {
        match (recv, method) {
            // ---- Layer-on-layer measurement methods ----
            (Pending::Layer(l), "width") => {
                let min = first_num(args)?;
                Ok(Pending::Width {
                    layer: l.name,
                    min_um: min,
                })
            }
            (Pending::Layer(l), "space") => {
                let min = first_num(args)?;
                Ok(Pending::Space {
                    layer: l.name,
                    min_um: min,
                })
            }
            (Pending::Layer(l), "enclosing") | (Pending::Layer(l), "enclose") => {
                // `outer.enclosing(inner, min)` - real KLayout semantics:
                // outer must enclose inner by at least `min`.
                let inner = self.layer_arg(args, 0)?;
                let min = num_arg(args, 1)?;
                Ok(Pending::Enclosing {
                    outer: l.name,
                    inner,
                    min_um: min,
                })
            }
            // `surround` is the Magic-flavoured alias of `enclosing`:
            // `outer.surround(inner, min)` -> outer must surround inner.
            // Same geometric semantics as `.enclosing`.
            (Pending::Layer(l), "surround") => {
                let inner = self.layer_arg(args, 0)?;
                let min = num_arg(args, 1)?;
                Ok(Pending::Enclosing {
                    outer: l.name,
                    inner,
                    min_um: min,
                })
            }
            // Inter-layer spacing: `a.separation(b, min)`.
            (Pending::Layer(l), "separation") => {
                let other = self.layer_arg(args, 0)?;
                let min = num_arg(args, 1)?;
                Ok(Pending::Separation {
                    layer_a: l.name,
                    layer_b: other,
                    min_um: min,
                })
            }
            // Minimum polygon area: `layer.area(min_um2)`.
            (Pending::Layer(l), "area") => {
                let min = first_num(args)?;
                Ok(Pending::Area {
                    layer: l.name,
                    min_um2: min,
                })
            }
            // Overhang: `outer.overhang(inner, min)`. Geometric inverse of
            // `.enclosing` from the inner's perspective; we keep it as a
            // distinct rule so reports name the outer (offending) layer.
            (Pending::Layer(l), "overhang") => {
                let inner = self.layer_arg(args, 0)?;
                let min = num_arg(args, 1)?;
                Ok(Pending::Overhang {
                    outer: l.name,
                    inner,
                    min_um: min,
                })
            }
            // Same-layer notch (intra-polygon internal-edge spacing).
            (Pending::Layer(l), "notch") => {
                let min = first_num(args)?;
                Ok(Pending::Notch {
                    layer: l.name,
                    min_um: min,
                })
            }
            // ---- Boolean ops yielding a derived layer ----
            (Pending::Layer(l), op @ ("inside" | "outside" | "not" | "and" | "or")) => {
                let other_name = self.layer_arg(args, 0)?;
                let bop = match op {
                    "inside" => BoolOp::Inside,
                    "outside" => BoolOp::Outside,
                    "not" => BoolOp::Not,
                    "and" => BoolOp::And,
                    "or" => BoolOp::Or,
                    _ => unreachable!(),
                };
                let derived_name = self.fresh_derived();
                self.deck.derived.push(DerivedLayer {
                    name: derived_name.clone(),
                    op: bop,
                    a: l.name,
                    b: other_name,
                });
                Ok(Pending::Layer(LayerHandle { name: derived_name }))
            }
            // ---- Density ----
            (Pending::Layer(l), "density") => {
                // `density(window: 100.um)` or `density(100)`.
                let window = num_arg(args, 0)
                    .map_err(|_| "density() requires a window argument".to_string())?;
                Ok(Pending::Density {
                    layer: l.name,
                    window_um: window,
                })
            }
            (Pending::Density { layer, window_um }, "range") => {
                let min = num_arg(args, 0)?;
                let max = num_arg(args, 1)?;
                Ok(Pending::DensityRanged {
                    layer,
                    window_um,
                    min,
                    max,
                })
            }
            // ---- No-op filters (parsed, not enforced in v0.3) ----
            (
                p,
                "with_length" | "without_length" | "angles" | "rectangles" | "edges" | "merged",
            ) => {
                self.warn(format!(".{method}(...) is parsed but not enforced (v0.3)"));
                Ok(p)
            }
            // Metric symbols inside width/space args end up here only if the
            // user does e.g. `metric.euclidian` - unlikely, defensive:
            (p, "euclidian" | "square" | "projection") => Ok(p),

            // ---- Terminal: emit rules ----
            (Pending::Width { layer, min_um }, "output") => {
                let (name, msg) = output_args(args, &layer, "minimum width");
                self.deck.rules.push(Rule::Width {
                    layer,
                    min_um,
                    name,
                    message: msg,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (Pending::Space { layer, min_um }, "output") => {
                let (name, msg) = output_args(args, &layer, "minimum spacing");
                self.deck.rules.push(Rule::Space {
                    layer,
                    min_um,
                    name,
                    message: msg,
                    intra_layer: true,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (
                Pending::Enclosing {
                    outer,
                    inner,
                    min_um,
                },
                "output",
            ) => {
                let (name, msg) = output_args(args, &inner, "enclosure");
                self.deck.rules.push(Rule::Enclosure {
                    inner,
                    outer,
                    min_um,
                    name,
                    message: msg,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (
                Pending::Separation {
                    layer_a,
                    layer_b,
                    min_um,
                },
                "output",
            ) => {
                let dual = format!("{layer_a}-{layer_b}");
                let (name, msg) = output_args(args, &dual, "separation");
                self.deck.rules.push(Rule::Separation {
                    layer_a,
                    layer_b,
                    min_um,
                    name,
                    message: msg,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (Pending::Area { layer, min_um2 }, "output") => {
                let (name, msg) = output_args(args, &layer, "area");
                self.deck.rules.push(Rule::Area {
                    layer,
                    min_um2,
                    name,
                    message: msg,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (
                Pending::Overhang {
                    outer,
                    inner,
                    min_um,
                },
                "output",
            ) => {
                let (name, msg) = output_args(args, &outer, "overhang");
                self.deck.rules.push(Rule::Overhang {
                    outer,
                    inner,
                    min_um,
                    name,
                    message: msg,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (Pending::Notch { layer, min_um }, "output") => {
                let (name, msg) = output_args(args, &layer, "notch");
                self.deck.rules.push(Rule::Notch {
                    layer,
                    min_um,
                    name,
                    message: msg,
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (
                Pending::DensityRanged {
                    layer,
                    window_um,
                    min,
                    max,
                },
                "output",
            ) => {
                let (name_base, msg) = output_args(args, &layer, "density");
                self.deck.rules.push(Rule::Density {
                    layer: layer.clone(),
                    window_um,
                    pct: min,
                    direction: DensityDirection::Below,
                    name: format!("{name_base}.min"),
                    message: format!("{msg} (min)"),
                });
                self.deck.rules.push(Rule::Density {
                    layer,
                    window_um,
                    pct: max,
                    direction: DensityDirection::Above,
                    name: format!("{name_base}.max"),
                    message: format!("{msg} (max)"),
                });
                Ok(Pending::Layer(LayerHandle {
                    name: "__sink__".into(),
                }))
            }
            (recv, m) => Err(format!("unsupported method '.{m}' on {recv:?}")),
        }
    }

    /// Resolve an arg-list slot to a layer-name (primitive or derived).
    /// Errors if the slot isn't an Ident bound to a layer.
    fn layer_arg(&mut self, args: &[Expr], idx: usize) -> std::result::Result<String, String> {
        let a = args
            .get(idx)
            .ok_or_else(|| format!("missing layer arg #{idx}"))?;
        match self.eval(a)? {
            Pending::Layer(h) => Ok(h.name),
            other => Err(format!("expected layer arg, got {other:?}")),
        }
    }
}

fn lit_int(e: &Expr) -> std::result::Result<i64, String> {
    match e {
        Expr::Num(n) => Ok(*n as i64),
        _ => Err(format!("expected integer literal, got {e:?}")),
    }
}

fn first_num(args: &[Expr]) -> std::result::Result<f64, String> {
    num_arg(args, 0)
}

fn num_arg(args: &[Expr], idx: usize) -> std::result::Result<f64, String> {
    match args.get(idx) {
        Some(Expr::Num(n)) => Ok(*n),
        Some(other) => Err(format!("expected number at arg #{idx}, got {other:?}")),
        None => Err(format!("missing numeric arg #{idx}")),
    }
}

/// `.output("rule.name", "description")` — both args optional in some decks.
fn output_args(args: &[Expr], layer: &str, kind: &str) -> (String, String) {
    let name = match args.first() {
        Some(Expr::Str(s)) => s.clone(),
        _ => format!("{layer}.{kind}"),
    };
    let msg = match args.get(1) {
        Some(Expr::Str(s)) => s.clone(),
        _ => format!("{layer} {kind}"),
    };
    (name, msg)
}

pub fn interpret(stmts: Vec<Stmt>) -> Result<RuleDeck> {
    let mut interp = Interp::new();
    interp.run(stmts).map_err(|e| match e {
        DrcError::RuleParse(_) => e,
        other => other,
    })?;
    if interp.deck.name.is_empty() {
        interp.deck.name = "drx_deck".into();
    }
    Ok(interp.deck)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rules::drx::lexer::tokenize;
    use crate::rules::drx::parser;

    fn run(src: &str) -> RuleDeck {
        let toks = tokenize(src).unwrap();
        let stmts = parser::parse(&toks).unwrap();
        interpret(stmts).unwrap()
    }

    #[test]
    fn input_then_width() {
        let deck = run(r#"
            li1 = input(67, 20)
            li1.width(0.17).output("li.1", "Min width 0.17")
        "#);
        assert_eq!(deck.layers.len(), 1);
        assert_eq!(deck.rules.len(), 1);
        match &deck.rules[0] {
            Rule::Width { min_um, name, .. } => {
                assert_eq!(name, "li.1");
                assert!((*min_um - 0.17).abs() < 1e-9);
            }
            _ => panic!(),
        }
    }

    #[test]
    fn boolean_outside_creates_derived() {
        let deck = run(r#"
            diff = input(65, 20)
            nwell = input(64, 20)
            diff_outside = diff.outside(nwell)
            diff_outside.width(0.15).output("diff.1", "Diff width")
        "#);
        assert_eq!(deck.derived.len(), 1);
        assert_eq!(deck.derived[0].op, BoolOp::Outside);
        assert_eq!(deck.rules.len(), 1);
        match &deck.rules[0] {
            Rule::Width { layer, .. } => {
                assert!(layer.starts_with("__derived_"));
            }
            _ => panic!(),
        }
    }

    #[test]
    fn density_range_emits_two_rules() {
        let deck = run(r#"
            met1 = input(68, 20)
            met1.density(100).range(0.20, 0.80).output("met1.D", "Density")
        "#);
        assert_eq!(deck.rules.len(), 2);
    }

    #[test]
    fn enclosing_rule() {
        let deck = run(r#"
            li1 = input(67, 20)
            licon = input(66, 44)
            li1.enclosing(licon, 0.08).output("li.4", "Enclosure")
        "#);
        assert_eq!(deck.rules.len(), 1);
        match &deck.rules[0] {
            Rule::Enclosure {
                inner,
                outer,
                min_um,
                ..
            } => {
                // Both layer names are synthetic L67D20 / L66D44.
                assert_eq!(outer, "L67D20");
                assert_eq!(inner, "L66D44");
                assert!((*min_um - 0.08).abs() < 1e-9);
            }
            _ => panic!(),
        }
    }

    #[test]
    fn report_sets_deck_name() {
        let deck = run(r#"
            report("sky130A DRC")
            li1 = input(67, 20)
            li1.width(0.17).output("li.1", "msg")
        "#);
        assert_eq!(deck.name, "sky130A DRC");
    }
}
