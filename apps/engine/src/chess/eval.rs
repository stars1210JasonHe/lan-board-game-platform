use super::board::*;
use super::moves::{generate_legal_moves, in_check,
                    knight_attacks_bb, bishop_attacks_bb, rook_attacks_bb};

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

fn pst_index(s: u8, color: Color) -> usize {
    if color == Color::White {
        s as usize
    } else {
        (s ^ 56) as usize // Mirror vertically for black
    }
}

// --- Bitboard helpers ---
const FILE_A_BB: u64 = 0x0101_0101_0101_0101;

fn file_bb(f: u8) -> u64 {
    FILE_A_BB << f
}

fn adj_files_bb(f: u8) -> u64 {
    let mut m = 0u64;
    if f > 0 { m |= FILE_A_BB << (f - 1); }
    if f < 7 { m |= FILE_A_BB << (f + 1); }
    m
}

// Passed pawn bonus indexed by relative rank (from pawn's side perspective)
// Index 0 = back rank (impossible), 1 = 2nd rank, ..., 6 = 7th rank, 7 = promotion (impossible)
const PASSED_BONUS_MG: [i32; 8] = [0, 5, 10, 20, 35, 60, 100, 0];
const PASSED_BONUS_EG: [i32; 8] = [0, 10, 15, 30, 50, 80, 120, 0];

fn material_phase(board: &Board) -> i32 {
    // Phase value: 0 = endgame, 24 = opening
    let mut phase = 0i32;
    for color in 0..2 {
        phase += board.pieces[color][Piece::Knight as usize].count_ones() as i32;
        phase += board.pieces[color][Piece::Bishop as usize].count_ones() as i32;
        phase += board.pieces[color][Piece::Rook as usize].count_ones() as i32 * 2;
        phase += board.pieces[color][Piece::Queen as usize].count_ones() as i32 * 4;
    }
    phase.min(24)
}

pub fn evaluate(board: &Board) -> i32 {
    let mut mg = 0i32;
    let mut eg = 0i32;
    let occ = board.all_occupied;

    for &color in &[Color::White, Color::Black] {
        let sign = if color == Color::White { 1 } else { -1 };
        let c = color as usize;
        let e = color.flip() as usize;
        let friendly = board.occupied[c];
        let our_pawns = board.pieces[c][Piece::Pawn as usize];
        let their_pawns = board.pieces[e][Piece::Pawn as usize];

        // === Pawns: material + PST ===
        let mut bb = our_pawns;
        while bb != 0 {
            let s = bb.trailing_zeros() as u8;
            let v = PAWN_VALUE + PAWN_PST[pst_index(s, color)];
            mg += sign * v;
            eg += sign * v;
            bb &= bb - 1;
        }

        // === Knights: material + PST + mobility ===
        let mut bb = board.pieces[c][Piece::Knight as usize];
        while bb != 0 {
            let s = bb.trailing_zeros() as u8;
            let v = KNIGHT_VALUE + KNIGHT_PST[pst_index(s, color)];
            mg += sign * v;
            eg += sign * v;
            let mob = (knight_attacks_bb(s) & !friendly).count_ones() as i32;
            mg += sign * (mob - 4) * 4;
            eg += sign * (mob - 4) * 4;
            bb &= bb - 1;
        }

        // === Bishops: material + PST + mobility + pair bonus ===
        let mut bb = board.pieces[c][Piece::Bishop as usize];
        let bishop_count = bb.count_ones();
        while bb != 0 {
            let s = bb.trailing_zeros() as u8;
            let v = BISHOP_VALUE + BISHOP_PST[pst_index(s, color)];
            mg += sign * v;
            eg += sign * v;
            let mob = (bishop_attacks_bb(s, occ) & !friendly).count_ones() as i32;
            mg += sign * (mob - 7) * 3;
            eg += sign * (mob - 7) * 3;
            bb &= bb - 1;
        }
        if bishop_count >= 2 {
            mg += sign * 30;
            eg += sign * 50;
        }

        // === Rooks: material + PST + mobility + file bonus + 7th rank ===
        let mut bb = board.pieces[c][Piece::Rook as usize];
        while bb != 0 {
            let s = bb.trailing_zeros() as u8;
            let f = file_of(s);
            let r = rank_of(s);
            let v = ROOK_VALUE + ROOK_PST[pst_index(s, color)];
            mg += sign * v;
            eg += sign * v;
            let mob = (rook_attacks_bb(s, occ) & !friendly).count_ones() as i32;
            mg += sign * (mob - 7) * 2;
            eg += sign * (mob - 7) * 2;
            // Open/semi-open file
            let fmask = file_bb(f);
            if our_pawns & fmask == 0 {
                if their_pawns & fmask == 0 {
                    mg += sign * 20;
                    eg += sign * 15;
                } else {
                    mg += sign * 10;
                    eg += sign * 8;
                }
            }
            // Rook on 7th rank
            let seventh = if color == Color::White { 6u8 } else { 1u8 };
            if r == seventh {
                mg += sign * 20;
                eg += sign * 30;
            }
            bb &= bb - 1;
        }

        // === Queens: material + PST + light mobility ===
        let mut bb = board.pieces[c][Piece::Queen as usize];
        while bb != 0 {
            let s = bb.trailing_zeros() as u8;
            let v = QUEEN_VALUE + QUEEN_PST[pst_index(s, color)];
            mg += sign * v;
            eg += sign * v;
            let attacks = (bishop_attacks_bb(s, occ) | rook_attacks_bb(s, occ)) & !friendly;
            let mob = attacks.count_ones() as i32;
            mg += sign * (mob - 14) * 1;
            eg += sign * (mob - 14) * 2;
            bb &= bb - 1;
        }

        // === King: PST ===
        let king_sq = board.king_square(color);
        mg += sign * KING_MG_PST[pst_index(king_sq, color)];
        eg += sign * KING_EG_PST[pst_index(king_sq, color)];

        // === Pawn Structure ===
        for f in 0..8u8 {
            let fmask = file_bb(f);
            let cnt = (our_pawns & fmask).count_ones() as i32;
            // Doubled pawns penalty
            if cnt > 1 {
                mg -= sign * 10 * (cnt - 1);
                eg -= sign * 20 * (cnt - 1);
            }
            // Isolated pawns penalty
            if cnt > 0 && our_pawns & adj_files_bb(f) == 0 {
                mg -= sign * 10;
                eg -= sign * 20;
            }
        }

        // Passed pawns
        let mut pp = our_pawns;
        while pp != 0 {
            let s = pp.trailing_zeros() as u8;
            let f = file_of(s);
            let r = rank_of(s);
            let sentinel = file_bb(f) | adj_files_bb(f);
            let front = if color == Color::White {
                if r >= 7 { 0u64 } else { sentinel & (u64::MAX << ((r as u32 + 1) * 8)) }
            } else {
                if r == 0 { 0u64 } else { sentinel & ((1u64 << (r as u32 * 8)) - 1) }
            };
            if their_pawns & front == 0 {
                let rel = if color == Color::White { r } else { 7 - r };
                mg += sign * PASSED_BONUS_MG[rel as usize];
                eg += sign * PASSED_BONUS_EG[rel as usize];
            }
            pp &= pp - 1;
        }

        // === King Safety (primarily middlegame) ===
        let kf = file_of(king_sq);
        let shield_rank = if color == Color::White { 1u8 } else { 6u8 };
        let storm_rank = if color == Color::White { 2u8 } else { 5u8 };
        for f in kf.saturating_sub(1)..=(kf + 1).min(7) {
            // Pawn shield bonus
            if our_pawns & bit(sq(f, shield_rank)) != 0 {
                mg += sign * 10;
            } else if our_pawns & bit(sq(f, storm_rank)) != 0 {
                mg += sign * 5;
            }
            // Open/semi-open file near king penalty
            let fmask = file_bb(f);
            if our_pawns & fmask == 0 {
                if their_pawns & fmask == 0 {
                    mg -= sign * 20;
                } else {
                    mg -= sign * 10;
                }
            }
        }
    }

    // Tapered eval: interpolate between middlegame and endgame
    let phase = material_phase(board);
    let score = (mg * phase + eg * (24 - phase)) / 24;

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
    let w_knights = board.pieces[0][Piece::Knight as usize].count_ones() as i32;
    let w_bishops = board.pieces[0][Piece::Bishop as usize].count_ones() as i32;
    let b_knights = board.pieces[1][Piece::Knight as usize].count_ones() as i32;
    let b_bishops = board.pieces[1][Piece::Bishop as usize].count_ones() as i32;

    let w_minor = w_knights + w_bishops;
    let b_minor = b_knights + b_bishops;

    // K vs K, K+N vs K, K+B vs K
    if w_minor <= 1 && b_minor == 0 { return true; }
    if b_minor <= 1 && w_minor == 0 { return true; }

    false
}
