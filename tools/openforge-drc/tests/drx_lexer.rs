//! Lexer tests for the DRX (Ruby-subset) DSL.

use openforge_drc::rules::drx::lexer::{tokenize, Tok};

fn kinds(src: &str) -> Vec<Tok> {
    tokenize(src).unwrap().into_iter().map(|t| t.tok).collect()
}

#[test]
fn idents_and_dots() {
    let t = kinds("met1.width(0.14)");
    // ident . ident ( num ) newline
    assert!(matches!(t[0], Tok::Ident(ref s) if s == "met1"));
    assert!(matches!(t[1], Tok::Dot));
    assert!(matches!(t[2], Tok::Ident(ref s) if s == "width"));
    assert!(matches!(t[3], Tok::LParen));
    assert!(matches!(t[4], Tok::Num(_)));
    assert!(matches!(t[5], Tok::RParen));
}

#[test]
fn um_and_nm_suffixes() {
    let t = kinds("100.um 500.nm 2.mm");
    let nums: Vec<f64> = t
        .iter()
        .filter_map(|x| match x {
            Tok::Num(n) => Some(*n),
            _ => None,
        })
        .collect();
    assert_eq!(nums.len(), 3);
    assert!((nums[0] - 100.0).abs() < 1e-9);
    assert!((nums[1] - 0.5).abs() < 1e-9); // 500 nm
    assert!((nums[2] - 2000.0).abs() < 1e-9); // 2 mm
}

#[test]
fn strings_and_symbols() {
    let t = kinds("output(\"li.1\", :euclidian)");
    assert!(t.iter().any(|x| matches!(x, Tok::Str(s) if s == "li.1")));
    assert!(t
        .iter()
        .any(|x| matches!(x, Tok::Sym(s) if s == "euclidian")));
}

#[test]
fn comments_are_stripped() {
    let t = kinds("# this is a comment\nli1 = input(67, 20)\n");
    // Should be: Ident(li1) Eq Ident(input) ( 67 , 20 ) Newline
    assert!(matches!(t[0], Tok::Ident(ref s) if s == "li1"));
}

#[test]
fn keyword_args() {
    let t = kinds("density(window: 100.um)");
    // ident ( ident : num ident ) newline
    assert!(matches!(t[2], Tok::Ident(ref s) if s == "window"));
    assert!(matches!(t[3], Tok::Colon));
    assert!(matches!(t[4], Tok::Num(_)));
}
