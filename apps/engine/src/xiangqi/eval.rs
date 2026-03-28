use super::board::*;
use super::moves::{generate_legal_moves, is_in_check};

pub const MATE_SCORE: i32 = 30000;
pub const DRAW_SCORE: i32 = 0;

// Material values in centipawns (normalized scale)
const KING_VALUE: i32 = 0;
const ADVISOR_VALUE: i32 = 200;
const ELEPHANT_VALUE: i32 = 200;
const HORSE_VALUE: i32 = 400;
const CANNON_VALUE: i32 = 450;
const ROOK_VALUE: i32 = 900;
const PAWN_VALUE: i32 = 100;
const PAWN_CROSSED_VALUE: i32 = 200;

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

// Advisor PST: bonus for being in ideal defensive positions
#[rustfmt::skip]
const ADVISOR_PST: [[i32; COLS]; ROWS] = [
    [  0,  0,  0,  0, 10,  0,  0,  0,  0],
    [  0,  0,  0, 10,  0, 10,  0,  0,  0],
    [  0,  0,  0,  0, 10,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0, 10,  0,  0,  0,  0],
    [  0,  0,  0, 10,  0, 10,  0,  0,  0],
    [  0,  0,  0,  0, 10,  0,  0,  0,  0],
];

// Elephant PST: bonus for standard defensive positions
#[rustfmt::skip]
const ELEPHANT_PST: [[i32; COLS]; ROWS] = [
    [  0,  0, 10,  0,  0,  0, 10,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 10,  0,  0,  0, 15,  0,  0,  0, 10],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0, 10,  0,  0,  0, 10,  0,  0],
    [  0,  0, 10,  0,  0,  0, 10,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 10,  0,  0,  0, 15,  0,  0,  0, 10],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0, 10,  0,  0,  0, 10,  0,  0],
];

fn pst_row(row: usize, color: Color) -> usize {
    if color == Color::Red { row } else { ROWS - 1 - row }
}

fn in_bounds(r: i32, c: i32) -> bool {
    r >= 0 && r < ROWS as i32 && c >= 0 && c < COLS as i32
}

fn crossed_river(row: usize, color: Color) -> bool {
    match color {
        Color::Red => row >= 5,
        Color::Black => row <= 4,
    }
}

/// Count how many of the 8 horse destinations are reachable (leg not blocked)
fn horse_mobility(board: &Board, r: usize, c: usize, color: Color) -> i32 {
    static HORSE_MOVES: [(i32, i32, i32, i32); 8] = [
        (1, 0, 2, 1), (1, 0, 2, -1),
        (-1, 0, -2, 1), (-1, 0, -2, -1),
        (0, 1, 1, 2), (0, 1, -1, 2),
        (0, -1, 1, -2), (0, -1, -1, -2),
    ];
    let mut count = 0;
    for &(dr1, dc1, dr2, dc2) in &HORSE_MOVES {
        let br = r as i32 + dr1;
        let bc = c as i32 + dc1;
        let nr = r as i32 + dr2;
        let nc = c as i32 + dc2;
        if in_bounds(nr, nc) && in_bounds(br, bc)
            && board.grid[br as usize][bc as usize].is_none()
        {
            // Don't count squares occupied by own pieces
            if let Some(cell) = board.grid[nr as usize][nc as usize] {
                if cell.color == color { continue; }
            }
            count += 1;
        }
    }
    count
}

/// Check if a file (column) has no pawns of a given color
fn file_has_no_pawns(board: &Board, col: usize, color: Color) -> bool {
    for r in 0..ROWS {
        if let Some(cell) = board.grid[r][col] {
            if cell.color == color && cell.piece == Piece::Pawn {
                return false;
            }
        }
    }
    true
}

/// Count screen pieces (pieces that cannon can jump over) on the file
fn cannon_screens_on_file(board: &Board, r: usize, col: usize) -> i32 {
    let mut screens = 0;
    // Count pieces above
    let mut above = 0;
    for row in (r + 1)..ROWS {
        if board.grid[row][col].is_some() {
            above += 1;
        }
    }
    // Count pieces below
    let mut below = 0;
    for row in (0..r).rev() {
        if board.grid[row][col].is_some() {
            below += 1;
        }
    }
    // A screen piece is useful if there's at least 1 piece to jump over
    if above >= 1 { screens += 1; }
    if below >= 1 { screens += 1; }
    screens
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
                    Piece::Advisor => ADVISOR_VALUE + ADVISOR_PST[pr][c],
                    Piece::Elephant => ELEPHANT_VALUE + ELEPHANT_PST[pr][c],
                    Piece::Horse => {

                        let base = HORSE_VALUE + HORSE_PST[pr][c];
                        // Horse mobility bonus/penalty
                        let mob = horse_mobility(board, r, c, cell.color);
                        // Average unblocked moves ~5-6, penalize blocked horses
                        base + (mob - 4) * 8
                    }
                    Piece::Cannon => {

                        let base = CANNON_VALUE + CANNON_PST[pr][c];
                        // Cannon on open/semi-open file bonus
                        let mut file_bonus = 0;
                        if file_has_no_pawns(board, c, cell.color) {
                            file_bonus += 10;
                        }
                        // Bonus for having screen pieces available
                        let screens = cannon_screens_on_file(board, r, c);
                        base + file_bonus + screens * 5
                    }
                    Piece::Rook => {

                        let base = ROOK_VALUE + ROOK_PST[pr][c];
                        let mut bonus = 0;
                        // Open file bonus
                        let our_pawn_free = file_has_no_pawns(board, c, cell.color);
                        let their_pawn_free = file_has_no_pawns(board, c, cell.color.flip());
                        if our_pawn_free {
                            if their_pawn_free {
                                bonus += 25; // fully open file
                            } else {
                                bonus += 12; // semi-open file
                            }
                        }
                        // River crossing bonus
                        if crossed_river(r, cell.color) {
                            bonus += 15;
                        }
                        base + bonus
                    }
                    Piece::Pawn => {
                        let crossed = crossed_river(r, cell.color);
                        let base = if crossed { PAWN_CROSSED_VALUE } else { PAWN_VALUE };
                        base + PAWN_PST[pr][c]
                    }
                };

                score += sign * val;
            }
        }
    }

    // === King Safety ===
    for &color in &[Color::Red, Color::Black] {
        let sign = if color == Color::Red { 1 } else { -1 };
        let mut advisor_count = 0;
        let mut elephant_count = 0;

        // Count advisors and elephants
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

        // Advisor pair bonus (two advisors defending king is much better than one)
        let advisor_bonus = match advisor_count {
            2 => 40,
            1 => 15,
            _ => 0,
        };
        // Elephant pair bonus
        let elephant_bonus = match elephant_count {
            2 => 30,
            1 => 10,
            _ => 0,
        };
        score += sign * (advisor_bonus + elephant_bonus);

        // King exposure: penalty if king is on non-center file in palace
        if let Some((_kr, kc)) = board.find_king(color) {
            // Penalty for king not on center file (column 4)
            if kc != 4 {
                score -= sign * 10;
            }
            // Penalty if enemy rook is on same file as king
            let enemy = color.flip();
            for r in 0..ROWS {
                if let Some(cell) = board.grid[r][kc] {
                    if cell.color == enemy && cell.piece == Piece::Rook {
                        score -= sign * 20;
                    }
                }
            }
        }
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
