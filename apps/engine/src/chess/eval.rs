use super::board::*;
use super::moves::{generate_legal_moves, is_square_attacked, in_check};

pub const MATE_SCORE: i32 = 30000;
pub const DRAW_SCORE: i32 = 0;

// Material values in centipawns
const PAWN_VALUE: i32 = 100;
const KNIGHT_VALUE: i32 = 320;
const BISHOP_VALUE: i32 = 330;
const ROOK_VALUE: i32 = 500;
const QUEEN_VALUE: i32 = 900;

pub fn piece_value(piece: Piece) -> i32 {
    match piece {
        Piece::Pawn => PAWN_VALUE,
        Piece::Knight => KNIGHT_VALUE,
        Piece::Bishop => BISHOP_VALUE,
        Piece::Rook => ROOK_VALUE,
        Piece::Queen => QUEEN_VALUE,
        Piece::King => 0,
    }
}

// Piece-square tables (from white's perspective, a1=index 0)
// Mirrored for black
#[rustfmt::skip]
const PAWN_PST: [i32; 64] = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
];

#[rustfmt::skip]
const KNIGHT_PST: [i32; 64] = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
];

#[rustfmt::skip]
const BISHOP_PST: [i32; 64] = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
];

#[rustfmt::skip]
const ROOK_PST: [i32; 64] = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
];

#[rustfmt::skip]
const QUEEN_PST: [i32; 64] = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
];

#[rustfmt::skip]
const KING_MG_PST: [i32; 64] = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
];

#[rustfmt::skip]
const KING_EG_PST: [i32; 64] = [
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
];

fn pst_index(sq: u8, color: Color) -> usize {
    if color == Color::White {
        sq as usize
    } else {
        (sq ^ 56) as usize // Mirror vertically for black
    }
}

fn count_bits(bb: u64) -> i32 {
    bb.count_ones() as i32
}

fn material_phase(board: &Board) -> i32 {
    // Phase value: 0 = endgame, 256 = opening
    let mut phase = 0i32;
    for color in 0..2 {
        phase += count_bits(board.pieces[color][Piece::Knight as usize]) * 1;
        phase += count_bits(board.pieces[color][Piece::Bishop as usize]) * 1;
        phase += count_bits(board.pieces[color][Piece::Rook as usize]) * 2;
        phase += count_bits(board.pieces[color][Piece::Queen as usize]) * 4;
    }
    phase.min(24) // max phase = 24
}

pub fn evaluate(board: &Board) -> i32 {
    let mut mg_score = 0i32; // middlegame
    let mut eg_score = 0i32; // endgame

    for &color in &[Color::White, Color::Black] {
        let sign = if color == Color::White { 1 } else { -1 };
        let c = color as usize;

        // Material + PST
        let mut bb = board.pieces[c][Piece::Pawn as usize];
        while bb != 0 {
            let sq = bb.trailing_zeros() as u8;
            mg_score += sign * (PAWN_VALUE + PAWN_PST[pst_index(sq, color)]);
            eg_score += sign * (PAWN_VALUE + PAWN_PST[pst_index(sq, color)]);
            bb &= bb - 1;
        }

        let mut bb = board.pieces[c][Piece::Knight as usize];
        while bb != 0 {
            let sq = bb.trailing_zeros() as u8;
            mg_score += sign * (KNIGHT_VALUE + KNIGHT_PST[pst_index(sq, color)]);
            eg_score += sign * (KNIGHT_VALUE + KNIGHT_PST[pst_index(sq, color)]);
            bb &= bb - 1;
        }

        let mut bb = board.pieces[c][Piece::Bishop as usize];
        while bb != 0 {
            let sq = bb.trailing_zeros() as u8;
            mg_score += sign * (BISHOP_VALUE + BISHOP_PST[pst_index(sq, color)]);
            eg_score += sign * (BISHOP_VALUE + BISHOP_PST[pst_index(sq, color)]);
            bb &= bb - 1;
        }

        let mut bb = board.pieces[c][Piece::Rook as usize];
        while bb != 0 {
            let sq = bb.trailing_zeros() as u8;
            mg_score += sign * (ROOK_VALUE + ROOK_PST[pst_index(sq, color)]);
            eg_score += sign * (ROOK_VALUE + ROOK_PST[pst_index(sq, color)]);
            bb &= bb - 1;
        }

        let mut bb = board.pieces[c][Piece::Queen as usize];
        while bb != 0 {
            let sq = bb.trailing_zeros() as u8;
            mg_score += sign * (QUEEN_VALUE + QUEEN_PST[pst_index(sq, color)]);
            eg_score += sign * (QUEEN_VALUE + QUEEN_PST[pst_index(sq, color)]);
            bb &= bb - 1;
        }

        // King PST
        let king_sq = board.king_square(color);
        mg_score += sign * KING_MG_PST[pst_index(king_sq, color)];
        eg_score += sign * KING_EG_PST[pst_index(king_sq, color)];

        // Bishop pair bonus
        if count_bits(board.pieces[c][Piece::Bishop as usize]) >= 2 {
            mg_score += sign * 30;
            eg_score += sign * 50;
        }

        // Doubled pawns penalty
        let pawns = board.pieces[c][Piece::Pawn as usize];
        for file in 0..8 {
            let file_mask = 0x0101_0101_0101_0101u64 << file;
            let pawns_on_file = count_bits(pawns & file_mask);
            if pawns_on_file > 1 {
                mg_score -= sign * 10 * (pawns_on_file - 1);
                eg_score -= sign * 20 * (pawns_on_file - 1);
            }
        }

        // Isolated pawns penalty
        for file in 0..8u8 {
            let file_mask = 0x0101_0101_0101_0101u64 << file;
            if pawns & file_mask != 0 {
                let mut adj = 0u64;
                if file > 0 { adj |= 0x0101_0101_0101_0101u64 << (file - 1); }
                if file < 7 { adj |= 0x0101_0101_0101_0101u64 << (file + 1); }
                if pawns & adj == 0 {
                    mg_score -= sign * 10;
                    eg_score -= sign * 20;
                }
            }
        }
    }

    // Tapered eval: interpolate between middlegame and endgame
    let phase = material_phase(board);
    let score = (mg_score * phase + eg_score * (24 - phase)) / 24;

    // Return from side-to-move's perspective
    if board.side == Color::White { score } else { -score }
}

/// Check if current position is checkmate or stalemate
pub fn is_terminal(board: &Board) -> Option<i32> {
    let moves = generate_legal_moves(board);
    if moves.is_empty() {
        if in_check(board) {
            return Some(-MATE_SCORE); // Checkmated (from side to move's perspective)
        } else {
            return Some(DRAW_SCORE); // Stalemate
        }
    }
    // Fifty-move rule
    if board.halfmove >= 100 {
        return Some(DRAW_SCORE);
    }
    // Insufficient material
    if is_insufficient_material(board) {
        return Some(DRAW_SCORE);
    }
    None
}

fn is_insufficient_material(board: &Board) -> bool {
    // No pawns, rooks, or queens
    for c in 0..2 {
        if board.pieces[c][Piece::Pawn as usize] != 0
            || board.pieces[c][Piece::Rook as usize] != 0
            || board.pieces[c][Piece::Queen as usize] != 0
        {
            return false;
        }
    }
    let w_knights = count_bits(board.pieces[0][Piece::Knight as usize]);
    let w_bishops = count_bits(board.pieces[0][Piece::Bishop as usize]);
    let b_knights = count_bits(board.pieces[1][Piece::Knight as usize]);
    let b_bishops = count_bits(board.pieces[1][Piece::Bishop as usize]);

    let w_minor = w_knights + w_bishops;
    let b_minor = b_knights + b_bishops;

    // K vs K, K+N vs K, K+B vs K
    if w_minor <= 1 && b_minor == 0 { return true; }
    if b_minor <= 1 && w_minor == 0 { return true; }

    false
}
