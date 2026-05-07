//! Minimal DEF AST — only the fields xRC needs.

#[derive(Debug, Clone)]
pub struct Def {
    pub design: String,
    pub units_per_micron: f64,
    pub die_area: ((i64, i64), (i64, i64)),
    pub components: Vec<Component>,
    pub nets: Vec<Net>,
}

#[derive(Debug, Clone)]
pub struct Component {
    pub name: String,
    pub macro_name: String,
    pub placement: Option<(i64, i64)>,
    pub orient: String,
}

#[derive(Debug, Clone)]
pub struct Net {
    pub name: String,
    /// (instance, pin) connections — for PIN connections, instance == "PIN".
    pub connections: Vec<(String, String)>,
    pub routes: Vec<RouteSeg>,
}

/// One ROUTED entry: a layer plus a path of points, possibly punctuated by vias.
#[derive(Debug, Clone)]
pub struct RouteSeg {
    pub layer: String,
    pub points: Vec<RoutePoint>,
}

#[derive(Debug, Clone)]
pub struct RoutePoint {
    pub x: i64,
    pub y: i64,
    /// Optional via name placed at this point.
    pub via: Option<String>,
}
