//! Polygon type used by the DRC engine.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub struct Bbox {
    pub x_min: f64,
    pub y_min: f64,
    pub x_max: f64,
    pub y_max: f64,
}

impl Bbox {
    pub fn from_points(points: &[(f64, f64)]) -> Self {
        let mut x_min = f64::INFINITY;
        let mut y_min = f64::INFINITY;
        let mut x_max = f64::NEG_INFINITY;
        let mut y_max = f64::NEG_INFINITY;
        for &(x, y) in points {
            if x < x_min {
                x_min = x;
            }
            if y < y_min {
                y_min = y;
            }
            if x > x_max {
                x_max = x;
            }
            if y > y_max {
                y_max = y;
            }
        }
        Bbox {
            x_min,
            y_min,
            x_max,
            y_max,
        }
    }

    pub fn width(&self) -> f64 {
        self.x_max - self.x_min
    }
    pub fn height(&self) -> f64 {
        self.y_max - self.y_min
    }

    /// Minimum gap between two boxes; 0 if they overlap.
    pub fn gap(&self, other: &Bbox) -> f64 {
        let dx = if other.x_min > self.x_max {
            other.x_min - self.x_max
        } else if self.x_min > other.x_max {
            self.x_min - other.x_max
        } else {
            0.0
        };
        let dy = if other.y_min > self.y_max {
            other.y_min - self.y_max
        } else if self.y_min > other.y_max {
            self.y_min - other.y_max
        } else {
            0.0
        };
        (dx * dx + dy * dy).sqrt()
    }
}

#[derive(Debug, Clone)]
pub struct Polygon {
    pub layer: String,
    /// User-unit (micron) coordinates. The polygon is implicitly closed
    /// (last point connects to first); duplicate-closed is also tolerated.
    pub points: Vec<(f64, f64)>,
    pub bbox: Bbox,
    /// Source cell name.
    pub cell: String,
}

impl Polygon {
    pub fn new(layer: impl Into<String>, points: Vec<(f64, f64)>, cell: impl Into<String>) -> Self {
        let bbox = Bbox::from_points(&points);
        Polygon {
            layer: layer.into(),
            points,
            bbox,
            cell: cell.into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bbox_basic() {
        let pts = vec![(0.0, 0.0), (1.0, 0.0), (1.0, 2.0), (0.0, 2.0)];
        let b = Bbox::from_points(&pts);
        assert_eq!(b.width(), 1.0);
        assert_eq!(b.height(), 2.0);
    }

    #[test]
    fn bbox_gap() {
        let a = Bbox {
            x_min: 0.0,
            y_min: 0.0,
            x_max: 1.0,
            y_max: 1.0,
        };
        let b = Bbox {
            x_min: 2.0,
            y_min: 0.0,
            x_max: 3.0,
            y_max: 1.0,
        };
        assert!((a.gap(&b) - 1.0).abs() < 1e-9);
        assert_eq!(a.gap(&a), 0.0);
    }
}
