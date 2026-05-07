//! Parser for the DRX subset.
//!
//! Produces an `Expr` tree per statement. The interpreter then walks the
//! tree, recognising specific shapes (`input(...)`, `<layer>.width(...)`,
//! `<chain>.output(...)`) and lowering them to layer bindings or `Rule`
//! variants.

use super::lexer::{Tok, Token};
use crate::{DrcError, Result};

#[derive(Debug, Clone)]
pub enum Expr {
    /// Identifier reference: `met1`.
    Ident(String),
    /// Numeric literal (already in microns).
    Num(f64),
    /// String literal.
    Str(String),
    /// Ruby symbol `:foo`.
    Sym(String),
    /// `func(args)` — bare function call.
    Call {
        name: String,
        args: Vec<Expr>,
        kwargs: Vec<(String, Expr)>,
    },
    /// `<recv>.method(args)`.
    MethodCall {
        recv: Box<Expr>,
        method: String,
        args: Vec<Expr>,
        kwargs: Vec<(String, Expr)>,
    },
}

#[derive(Debug, Clone)]
pub enum Stmt {
    /// `name = expr`.
    Assign {
        name: String,
        expr: Expr,
        line: usize,
    },
    /// Bare expression statement.
    Expr { expr: Expr, line: usize },
}

struct Parser<'a> {
    toks: &'a [Token],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&Tok> {
        self.toks.get(self.pos).map(|t| &t.tok)
    }
    fn line(&self) -> usize {
        self.toks
            .get(self.pos)
            .or_else(|| self.toks.last())
            .map(|t| t.line)
            .unwrap_or(0)
    }
    fn bump(&mut self) -> Option<Token> {
        let t = self.toks.get(self.pos).cloned();
        if t.is_some() {
            self.pos += 1;
        }
        t
    }
    fn eat(&mut self, t: &Tok) -> bool {
        if self.peek() == Some(t) {
            self.pos += 1;
            true
        } else {
            false
        }
    }
    fn expect(&mut self, t: &Tok, what: &str) -> Result<()> {
        if !self.eat(t) {
            return Err(DrcError::RuleParse(format!(
                "line {}: expected {what}, got {:?}",
                self.line(),
                self.peek()
            )));
        }
        Ok(())
    }
    fn skip_newlines(&mut self) {
        while matches!(self.peek(), Some(Tok::Newline)) {
            self.pos += 1;
        }
    }

    fn parse_program(&mut self) -> Result<Vec<Stmt>> {
        let mut out = Vec::new();
        self.skip_newlines();
        while self.peek().is_some() {
            let stmt = self.parse_stmt()?;
            out.push(stmt);
            self.skip_newlines();
        }
        Ok(out)
    }

    fn parse_stmt(&mut self) -> Result<Stmt> {
        let line = self.line();
        // Lookahead for `IDENT =` (but NOT `==` which we already collapsed).
        if let (Some(Tok::Ident(_)), Some(Tok::Eq)) = (
            self.toks.get(self.pos).map(|t| &t.tok),
            self.toks.get(self.pos + 1).map(|t| &t.tok),
        ) {
            let name = if let Some(Token {
                tok: Tok::Ident(n), ..
            }) = self.bump()
            {
                n
            } else {
                unreachable!()
            };
            self.bump(); // `=`
            let expr = self.parse_expr()?;
            return Ok(Stmt::Assign { name, expr, line });
        }
        let expr = self.parse_expr()?;
        Ok(Stmt::Expr { expr, line })
    }

    /// An expression is a primary followed by zero or more `.method(args)` calls.
    fn parse_expr(&mut self) -> Result<Expr> {
        let mut e = self.parse_primary()?;
        loop {
            if self.eat(&Tok::Dot) {
                let name = match self.bump() {
                    Some(Token {
                        tok: Tok::Ident(n), ..
                    }) => n,
                    other => {
                        return Err(DrcError::RuleParse(format!(
                            "line {}: expected method name after '.', got {other:?}",
                            self.line()
                        )))
                    }
                };
                let (args, kwargs) = if matches!(self.peek(), Some(Tok::LParen)) {
                    self.parse_call_args()?
                } else {
                    (Vec::new(), Vec::new())
                };
                e = Expr::MethodCall {
                    recv: Box::new(e),
                    method: name,
                    args,
                    kwargs,
                };
            } else {
                break;
            }
        }
        Ok(e)
    }

    fn parse_primary(&mut self) -> Result<Expr> {
        match self.peek().cloned() {
            Some(Tok::Num(n)) => {
                self.pos += 1;
                Ok(Expr::Num(n))
            }
            Some(Tok::Str(s)) => {
                self.pos += 1;
                Ok(Expr::Str(s))
            }
            Some(Tok::Sym(s)) => {
                self.pos += 1;
                Ok(Expr::Sym(s))
            }
            Some(Tok::Ident(name)) => {
                self.pos += 1;
                if matches!(self.peek(), Some(Tok::LParen)) {
                    let (args, kwargs) = self.parse_call_args()?;
                    Ok(Expr::Call { name, args, kwargs })
                } else {
                    Ok(Expr::Ident(name))
                }
            }
            Some(Tok::LParen) => {
                self.pos += 1;
                let e = self.parse_expr()?;
                self.expect(&Tok::RParen, "')'")?;
                Ok(e)
            }
            Some(Tok::LBracket) => {
                // Ruby array literal — we don't really use them; consume.
                self.pos += 1;
                let mut depth = 1;
                while depth > 0 {
                    match self.bump() {
                        Some(Token {
                            tok: Tok::LBracket, ..
                        }) => depth += 1,
                        Some(Token {
                            tok: Tok::RBracket, ..
                        }) => depth -= 1,
                        Some(_) => {}
                        None => {
                            return Err(DrcError::RuleParse(
                                "unterminated array literal".to_string(),
                            ))
                        }
                    }
                }
                Ok(Expr::Sym("__array__".into()))
            }
            other => Err(DrcError::RuleParse(format!(
                "line {}: unexpected token in expression: {:?}",
                self.line(),
                other
            ))),
        }
    }

    /// Parse `(arg, arg, key: val, key: val)`. Returns (positional, kwargs).
    #[allow(clippy::type_complexity)]
    fn parse_call_args(&mut self) -> Result<(Vec<Expr>, Vec<(String, Expr)>)> {
        self.expect(&Tok::LParen, "'('")?;
        let mut args = Vec::new();
        let mut kwargs = Vec::new();
        // Allow newlines inside arg lists.
        while matches!(self.peek(), Some(Tok::Newline)) {
            self.pos += 1;
        }
        if self.eat(&Tok::RParen) {
            return Ok((args, kwargs));
        }
        loop {
            // Detect `IDENT :` keyword arg or `IDENT =>` (collapsed to Eq) -
            // not the recv.method form.
            let is_kwarg = matches!(
                (
                    self.toks.get(self.pos).map(|t| &t.tok),
                    self.toks.get(self.pos + 1).map(|t| &t.tok),
                ),
                (Some(Tok::Ident(_)), Some(Tok::Colon))
            );
            if is_kwarg {
                let key = if let Some(Token {
                    tok: Tok::Ident(n), ..
                }) = self.bump()
                {
                    n
                } else {
                    unreachable!()
                };
                self.bump(); // colon
                let val = self.parse_expr()?;
                kwargs.push((key, val));
            } else {
                let e = self.parse_expr()?;
                args.push(e);
            }
            while matches!(self.peek(), Some(Tok::Newline)) {
                self.pos += 1;
            }
            if self.eat(&Tok::Comma) {
                while matches!(self.peek(), Some(Tok::Newline)) {
                    self.pos += 1;
                }
                continue;
            }
            break;
        }
        self.expect(&Tok::RParen, "')'")?;
        Ok((args, kwargs))
    }
}

pub fn parse(toks: &[Token]) -> Result<Vec<Stmt>> {
    let mut p = Parser { toks, pos: 0 };
    p.parse_program()
}

#[cfg(test)]
#[allow(clippy::collapsible_match)]
mod tests {
    use super::*;
    use crate::rules::drx::lexer::tokenize;

    fn parse_src(src: &str) -> Vec<Stmt> {
        let t = tokenize(src).unwrap();
        parse(&t).unwrap()
    }

    #[test]
    fn parses_assignment_with_input() {
        let s = parse_src("met1 = input(68, 20)\n");
        assert_eq!(s.len(), 1);
        match &s[0] {
            Stmt::Assign { name, expr, .. } => {
                assert_eq!(name, "met1");
                match expr {
                    Expr::Call { name, args, .. } => {
                        assert_eq!(name, "input");
                        assert_eq!(args.len(), 2);
                    }
                    _ => panic!("expected Call"),
                }
            }
            _ => panic!("expected Assign"),
        }
    }

    #[test]
    fn parses_method_chain_with_output() {
        let s = parse_src("li1.width(0.17).output(\"li.1\", \"min width\")\n");
        assert_eq!(s.len(), 1);
        match &s[0] {
            Stmt::Expr { expr, .. } => match expr {
                Expr::MethodCall {
                    method, recv, args, ..
                } => {
                    assert_eq!(method, "output");
                    assert_eq!(args.len(), 2);
                    match recv.as_ref() {
                        Expr::MethodCall { method: m, .. } => assert_eq!(m, "width"),
                        _ => panic!(),
                    }
                }
                _ => panic!(),
            },
            _ => panic!(),
        }
    }

    #[test]
    fn parses_kwargs() {
        let s = parse_src("met1.density(window: 100.um).range(0.2, 0.8)\n");
        match &s[0] {
            Stmt::Expr { expr, .. } => match expr {
                Expr::MethodCall { method, recv, .. } => {
                    assert_eq!(method, "range");
                    if let Expr::MethodCall {
                        method: m, kwargs, ..
                    } = recv.as_ref()
                    {
                        assert_eq!(m, "density");
                        assert_eq!(kwargs.len(), 1);
                        assert_eq!(kwargs[0].0, "window");
                    } else {
                        panic!();
                    }
                }
                _ => panic!(),
            },
            _ => panic!(),
        }
    }
}
