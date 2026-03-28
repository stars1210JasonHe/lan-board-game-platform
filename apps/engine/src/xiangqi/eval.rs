use super::board::*;
use super::moves::{generate_legal_moves, is_in_check};

pub const MATE_SCORE: i32 = 30000;
pub const DRAW_SCORE: i32 = 0;

// Material values
const KING_VALUE: i32 = 0;
const ADVISOR_VALUE: i32 = 20;
const ELEPHANT_VALUE: i32 = 20;
const HORSE_VALUE: i32 = 40;
const CANNON_VALUE: i32 = 45;
const ROOK_VALUE: i32 = 90;
const PAWN_VALUE: i32 = 10;
const PAWN_CROSSED_VALUE: i32 = 20;

pub fn piece_value(piece: Piece) -> i32 {
    match piece {
        Piece::King => KING_VALUE,
        Piece::Advisor => ADVISOR_VALUE,
        Piece::Elephant => ELEPHANT_VALUE,
        Piece::Horse => HORSE_VALUE,
        Piece::Cannon => CANNON_VALUE,
        Piece::Rook => ROOK_VALUE,
        Piece::Pawn => PAWN_VALUE,
    }
}

// Piece-square tables (from Red's perspective, row 0 = Red's back rank)
// Values in centipawns-ish units

#[rustfmt::skip]
const ROOK_PST: [[i32; COLS]; ROWS] = [
    [ 0,  0,  0, 10, 10, 10,  0,  0,  0],
    [ 0,  0,  0, 10, 10, 10,  0,  0,  0],
    [ 0,  0,  0, 10, 10, 10,  0,  0,  0],
    [ 0,  0,  0, 10, 10, 10,  0,  0,  0],
    [ 5,  5,  5, 15, 15, 15,  5,  5,  5],
    [ 5,  5,  5, 15, 15, 15,  5,  5,  5],
    [10, 10, 10, 15, 15, 15, 10, 10, 10],
    [10, 10, 10, 15, 15, 15, 10, 10, 10],
    [10, 10, 10, 15, 15, 15, 10, 10, 10],
    [ 5,  5,  5, 10, 10, 10,  5,  5,  5],
];

#[rustfmt::skip]
const HORSE_PST: [[i32; COLS]; ROWS] = [
    [-10, -5,  0,  0,  0,  0,  0, -5,-10],
    [ -5,  0,  5,  5,  5,  5,  5,  0, -5],
    [  0,  5, 10, 10, 10, 10, 10,  5,  0],
    [  0,  5, 10, 15, 15, 15, 10,  5,  0],
    [  0,  5, 10, 15, 15, 15, 10,  5,  0],
    [  0,  5, 10, 15, 15, 15, 10,  5,  0],
    [  0,  5, 10, 10, 10, 10, 10,  5,  0],
    [ -5,  0,  5,  5,  5,  5,  5,  0, -5],
    [-10, -5,  0,  0,  0,  0,  0, -5,-10],
    [-10, -5,  0,  0,  0,  0,  0, -5,-10],
];

#[rustfmt::skip]
const CANNON_PST: [[i32; COLS]; ROWS] = [
    [  0,  0,  5,  5,  5,  5,  5,  0,  0],
    [  0,  0,  5,  5,  5,  5,  5,  0,  0],
    [  0,  5, 10, 10, 10, 10, 10,  5,  0],
    [  0,  5, 10, 10, 10, 10, 10,  5,  0],
    [  5, 10, 10, 15, 15, 15, 10, 10,  5],
    [  5, 10, 10, 15, 15, 15, 10, 10,  5],
    [  0,  5, 10, 10, 10, 10, 10,  5,  0],
    [  0,  0,  5,  5,  5,  5,  5,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

#[rustfmt::skip]
const PAWN_PST: [[i32; COLS]; ROWS] = [
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  5,  5,  5,  5,  5,  0,  0],
    [  5,  5,  5,  5,  5,  5,  5,  5,  5],
    [ 10, 10, 15, 20, 20, 20, 15, 10, 10],
    [ 10, 15, 20, 25, 25, 25, 20, 15, 10],
    [ 15, 20, 25, 30, 30, 30, 25, 20, 15],
    [ 20, 25, 30, 35, 35, 35, 30, 25, 20],
    [ 20, 25, 30, 35, 35, 35, 30, 25, 20],
];

fn pst_row(row: usize, color: Color) -> usize {
    if color == Color::Red { row } else { ROWS - 1 - row }
}

pub fn evaluate(board: &Board) -> i32 {
    let mut score = 0i32;

    for r in 0..ROWS {
        for c in 0..COLS {
            if let Some(cell) = board.grid[r][c] {
                let sign = if cell.color == Color::Red { 1 } else { -1 };
                let pr = pst_row(r, cell.color);

                let val = match cell.piece {
                    Piece::King => KING_VALUE,
                    Piece::Advisor => ADVISOR_VALUE,
                    Piece::Elephant => ELEPHANT_VALUE,
                    Piece::Horse => HORSE_VALUE * 10 + HORSE_PST[pr][c],
                    Piece::Cannon => CANNON_VALUE * 10 + CANNON_PST[pr][c],
                    Piece::Rook => ROOK_VALUE * 10 + ROOK_PST[pr][c],
                    Piece::Pawn => {
                        let base = if (cell.color == Color::Red && r >= 5)
                            || (cell.color == Color::Black && r <= 4) {
                            PAWN_CROSSED_VALUE
                        } else {
                            PAWN_VALUE
                        };
                        base * 10 + PAWN_PST[pr][c]
                    }
                };

                score += sign * val;
            }
        }
    }

    // King safety: advisors and elephants near king
    for &color in &[Color::Red, Color::Black] {
        let sign = if color == Color::Red { 1 } else { -1 };
        let mut advisor_count = 0;
        let mut elephant_count = 0;
        for r in 0..ROWS {
            for c in 0..COLS {
                if let Some(cell) = board.grid[r][c] {
                    if cell.color == color {
                        if cell.piece == Piece::Advisor { advisor_count += 1; }
                        if cell.piece == Piece::Elephant { elephant_count += 1; }
                    }
                }
            }
        }
        score += sign * advisor_count * 15;
        score += sign * elephant_count * 10;
    }

    if board.side == Color::Red { score } else { -score }
}

pub fn is_terminal(board: &Board) -> Option<i32> {
    let moves = generate_legal_moves(board);
    if moves.is_empty() {
        if is_in_check(board, board.side) {
            return Some(-MATE_SCORE);
        } else {
            return Some(DRAW_SCORE);
        }
    }
    None
}
