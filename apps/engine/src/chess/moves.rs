use super::board::*;

/// Move encoding: 16 bits
/// bits 0-5:  from square
/// bits 6-11: to square
/// bits 12-13: promotion piece (0=knight, 1=bishop, 2=rook, 3=queen)
/// bits 14-15: flags (0=normal, 1=promotion, 2=en passant, 3=castling)
pub type Move = u16;

pub const FLAG_NORMAL: u16 = 0;
pub const FLAG_PROMOTION: u16 = 1 << 14;
pub const FLAG_EP: u16 = 2 << 14;
pub const FLAG_CASTLE: u16 = 3 << 14;

pub fn new_move(from: u8, to: u8) -> Move {
    (from as u16) | ((to as u16) << 6)
}

pub fn new_promotion(from: u8, to: u8, promo: Piece) -> Move {
    let p = match promo {
        Piece::Knight => 0,
        Piece::Bishop => 1,
        Piece::Rook => 2,
        Piece::Queen => 3,
        _ => 0,
    };
    (from as u16) | ((to as u16) << 6) | ((p as u16) << 12) | FLAG_PROMOTION
}

pub fn new_ep(from: u8, to: u8) -> Move {
    (from as u16) | ((to as u16) << 6) | FLAG_EP
}

pub fn new_castle(from: u8, to: u8) -> Move {
    (from as u16) | ((to as u16) << 6) | FLAG_CASTLE
}

pub fn move_from(m: Move) -> u8 {
    (m & 0x3F) as u8
}

pub fn move_to(m: Move) -> u8 {
    ((m >> 6) & 0x3F) as u8
}

pub fn move_flags(m: Move) -> u16 {
    m & 0xC000
}

pub fn move_promo(m: Move) -> Piece {
    match (m >> 12) & 3 {
        0 => Piece::Knight,
        1 => Piece::Bishop,
        2 => Piece::Rook,
        3 => Piece::Queen,
        _ => unreachable!(),
    }
}

pub fn move_to_uci(m: Move) -> String {
    let from = move_from(m);
    let to = move_to(m);
    let mut s = String::with_capacity(5);
    s.push((b'a' + file_of(from)) as char);
    s.push((b'1' + rank_of(from)) as char);
    s.push((b'a' + file_of(to)) as char);
    s.push((b'1' + rank_of(to)) as char);
    if move_flags(m) == FLAG_PROMOTION {
        s.push(match move_promo(m) {
            Piece::Knight => 'n',
            Piece::Bishop => 'b',
            Piece::Rook => 'r',
            Piece::Queen => 'q',
            _ => 'q',
        });
    }
    s
}

pub fn uci_to_move(board: &Board, uci: &str) -> Option<Move> {
    let bytes = uci.as_bytes();
    if bytes.len() < 4 { return None; }
    let from = sq(bytes[0] - b'a', bytes[1] - b'1');
    let to = sq(bytes[2] - b'a', bytes[3] - b'1');
    let moves = generate_legal_moves(board);
    let promo_char = if bytes.len() > 4 { Some(bytes[4]) } else { None };

    moves.into_iter().find(|&m| {
        move_from(m) == from && move_to(m) == to && {
            if move_flags(m) == FLAG_PROMOTION {
                match promo_char {
                    Some(b'n') => move_promo(m) == Piece::Knight,
                    Some(b'b') => move_promo(m) == Piece::Bishop,
                    Some(b'r') => move_promo(m) == Piece::Rook,
                    Some(b'q') | None => move_promo(m) == Piece::Queen,
                    _ => false,
                }
            } else {
                true
            }
        }
    })
}

// Attack tables - computed at runtime once
use std::sync::LazyLock;

struct AttackTables {
    knight: [u64; 64],
    king: [u64; 64],
    pawn_attacks: [[u64; 64]; 2], // [color][square]
    // For sliding pieces we use classical ray approach
    ray_attacks: [[u64; 8]; 64], // [square][direction]
}

static TABLES: LazyLock<AttackTables> = LazyLock::new(|| {
    let mut t = AttackTables {
        knight: [0; 64],
        king: [0; 64],
        pawn_attacks: [[0; 64]; 2],
        ray_attacks: [[0; 8]; 64],
    };

    for sq in 0..64u8 {
        let f = file_of(sq) as i8;
        let r = rank_of(sq) as i8;

        // Knight attacks
        for &(df, dr) in &[(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)] {
            let nf = f + df;
            let nr = r + dr;
            if nf >= 0 && nf < 8 && nr >= 0 && nr < 8 {
                t.knight[sq as usize] |= bit(super::board::sq(nf as u8, nr as u8));
            }
        }

        // King attacks
        for &(df, dr) in &[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)] {
            let nf = f + df;
            let nr = r + dr;
            if nf >= 0 && nf < 8 && nr >= 0 && nr < 8 {
                t.king[sq as usize] |= bit(super::board::sq(nf as u8, nr as u8));
            }
        }

        // Pawn attacks
        // White pawn attacks (captures go up-left, up-right)
        if r < 7 {
            if f > 0 { t.pawn_attacks[0][sq as usize] |= bit(super::board::sq((f-1) as u8, (r+1) as u8)); }
            if f < 7 { t.pawn_attacks[0][sq as usize] |= bit(super::board::sq((f+1) as u8, (r+1) as u8)); }
        }
        // Black pawn attacks
        if r > 0 {
            if f > 0 { t.pawn_attacks[1][sq as usize] |= bit(super::board::sq((f-1) as u8, (r-1) as u8)); }
            if f < 7 { t.pawn_attacks[1][sq as usize] |= bit(super::board::sq((f+1) as u8, (r-1) as u8)); }
        }

        // Ray attacks: 8 directions (N, NE, E, SE, S, SW, W, NW)
        let dirs: [(i8,i8); 8] = [(0,1),(1,1),(1,0),(1,-1),(0,-1),(-1,-1),(-1,0),(-1,1)];
        for (di, &(df, dr)) in dirs.iter().enumerate() {
            let mut ray = 0u64;
            let mut cf = f + df;
            let mut cr = r + dr;
            while cf >= 0 && cf < 8 && cr >= 0 && cr < 8 {
                ray |= bit(super::board::sq(cf as u8, cr as u8));
                cf += df;
                cr += dr;
            }
            t.ray_attacks[sq as usize][di] = ray;
        }
    }

    t
});

// Direction indices for ray_attacks
const DIR_N: usize = 0;
const DIR_NE: usize = 1;
const DIR_E: usize = 2;
const DIR_SE: usize = 3;
const DIR_S: usize = 4;
const DIR_SW: usize = 5;
const DIR_W: usize = 6;
const DIR_NW: usize = 7;

fn ray_attack(sq: u8, dir: usize, occupied: u64) -> u64 {
    let ray = TABLES.ray_attacks[sq as usize][dir];
    let blockers = ray & occupied;
    if blockers == 0 {
        return ray;
    }
    // Find the first blocker in the direction
    let blocker_sq = match dir {
        DIR_N | DIR_NE | DIR_E | DIR_NW => blockers.trailing_zeros() as u8,  // positive direction: lowest bit
        _ => 63 - blockers.leading_zeros() as u8,  // negative direction: highest bit
    };
    ray ^ (TABLES.ray_attacks[blocker_sq as usize][dir])
}

fn bishop_attacks(sq: u8, occupied: u64) -> u64 {
    ray_attack(sq, DIR_NE, occupied) |
    ray_attack(sq, DIR_SE, occupied) |
    ray_attack(sq, DIR_SW, occupied) |
    ray_attack(sq, DIR_NW, occupied)
}

fn rook_attacks(sq: u8, occupied: u64) -> u64 {
    ray_attack(sq, DIR_N, occupied) |
    ray_attack(sq, DIR_E, occupied) |
    ray_attack(sq, DIR_S, occupied) |
    ray_attack(sq, DIR_W, occupied)
}

fn queen_attacks(sq: u8, occupied: u64) -> u64 {
    bishop_attacks(sq, occupied) | rook_attacks(sq, occupied)
}

pub fn is_square_attacked(board: &Board, square: u8, by_color: Color) -> bool {
    let them = by_color as usize;
    let occ = board.all_occupied;

    // Knight
    if TABLES.knight[square as usize] & board.pieces[them][Piece::Knight as usize] != 0 {
        return true;
    }
    // King
    if TABLES.king[square as usize] & board.pieces[them][Piece::King as usize] != 0 {
        return true;
    }
    // Pawn (check from opposite perspective)
    let us = by_color.flip() as usize;
    if TABLES.pawn_attacks[us][square as usize] & board.pieces[them][Piece::Pawn as usize] != 0 {
        return true;
    }
    // Bishop/Queen (diagonal)
    let diag = bishop_attacks(square, occ);
    if diag & (board.pieces[them][Piece::Bishop as usize] | board.pieces[them][Piece::Queen as usize]) != 0 {
        return true;
    }
    // Rook/Queen (straight)
    let straight = rook_attacks(square, occ);
    if straight & (board.pieces[them][Piece::Rook as usize] | board.pieces[them][Piece::Queen as usize]) != 0 {
        return true;
    }
    false
}

pub fn in_check(board: &Board) -> bool {
    let king_sq = board.king_square(board.side);
    is_square_attacked(board, king_sq, board.side.flip())
}

/// Make a move on the board, returning the new board state
pub fn make_move(board: &Board, m: Move) -> Board {
    let mut b = board.clone();
    let us = b.side;
    let them = us.flip();
    let from = move_from(m);
    let to = move_to(m);
    let flags = move_flags(m);

    let (_, piece) = b.piece_at(from).expect("No piece at from square");

    // Remove en passant from zobrist
    if let Some(ep) = b.ep_square {
        b.zobrist ^= ZOBRIST.ep[file_of(ep) as usize];
    }

    // Remove castling from zobrist
    b.zobrist ^= ZOBRIST.castling[b.castling.0 as usize];

    // Handle capture
    let mut captured = None;
    if flags == FLAG_EP {
        // En passant capture
        let cap_sq = if us == Color::White { to - 8 } else { to + 8 };
        b.remove_piece(them, Piece::Pawn, cap_sq);
        captured = Some(Piece::Pawn);
    } else if let Some((cap_color, cap_piece)) = b.piece_at(to) {
        if cap_color == them {
            b.remove_piece(them, cap_piece, to);
            captured = Some(cap_piece);
        }
    }

    // Move piece
    b.remove_piece(us, piece, from);

    if flags == FLAG_PROMOTION {
        b.set_piece(us, move_promo(m), to);
    } else {
        b.set_piece(us, piece, to);
    }

    // Handle castling move (move the rook)
    if flags == FLAG_CASTLE {
        match to {
            6 => { // White kingside (g1)
                b.remove_piece(Color::White, Piece::Rook, 7);  // h1
                b.set_piece(Color::White, Piece::Rook, 5);     // f1
            }
            2 => { // White queenside (c1)
                b.remove_piece(Color::White, Piece::Rook, 0);  // a1
                b.set_piece(Color::White, Piece::Rook, 3);     // d1
            }
            62 => { // Black kingside (g8)
                b.remove_piece(Color::Black, Piece::Rook, 63); // h8
                b.set_piece(Color::Black, Piece::Rook, 61);    // f8
            }
            58 => { // Black queenside (c8)
                b.remove_piece(Color::Black, Piece::Rook, 56); // a8
                b.set_piece(Color::Black, Piece::Rook, 59);    // d8
            }
            _ => {}
        }
    }

    // Update castling rights
    // King moves remove both castling rights
    if piece == Piece::King {
        match us {
            Color::White => { b.castling.remove(CastleRights::WK | CastleRights::WQ); }
            Color::Black => { b.castling.remove(CastleRights::BK | CastleRights::BQ); }
        }
    }
    // Rook moves/captures remove specific rights
    if from == 0 || to == 0 { b.castling.remove(CastleRights::WQ); }
    if from == 7 || to == 7 { b.castling.remove(CastleRights::WK); }
    if from == 56 || to == 56 { b.castling.remove(CastleRights::BQ); }
    if from == 63 || to == 63 { b.castling.remove(CastleRights::BK); }

    // Update en passant square
    b.ep_square = None;
    if piece == Piece::Pawn {
        let diff = (to as i8 - from as i8).unsigned_abs();
        if diff == 16 {
            b.ep_square = Some(if us == Color::White { from + 8 } else { from - 8 });
        }
    }

    // Update zobrist for castling and ep
    b.zobrist ^= ZOBRIST.castling[b.castling.0 as usize];
    if let Some(ep) = b.ep_square {
        b.zobrist ^= ZOBRIST.ep[file_of(ep) as usize];
    }

    // Switch side
    b.side = them;
    b.zobrist ^= ZOBRIST.side;

    // Update clocks
    if piece == Piece::Pawn || captured.is_some() {
        b.halfmove = 0;
    } else {
        b.halfmove += 1;
    }
    if us == Color::Black {
        b.fullmove += 1;
    }

    b
}

pub fn generate_pseudo_legal_moves(board: &Board) -> Vec<Move> {
    let mut moves = Vec::with_capacity(256);
    let us = board.side as usize;
    let them = board.side.flip() as usize;
    let our_occ = board.occupied[us];
    let their_occ = board.occupied[them];
    let all = board.all_occupied;
    let empty = !all;

    // Pawns
    let pawns = board.pieces[us][Piece::Pawn as usize];
    if board.side == Color::White {
        // Single push
        let push = (pawns << 8) & empty;
        let mut bb = push & 0x00FF_FFFF_FFFF_FFFF; // non-promotion
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to - 8, to));
            bb &= bb - 1;
        }
        // Promotion pushes
        let mut promo = push & 0xFF00_0000_0000_0000;
        while promo != 0 {
            let to = promo.trailing_zeros() as u8;
            moves.push(new_promotion(to - 8, to, Piece::Queen));
            moves.push(new_promotion(to - 8, to, Piece::Rook));
            moves.push(new_promotion(to - 8, to, Piece::Bishop));
            moves.push(new_promotion(to - 8, to, Piece::Knight));
            promo &= promo - 1;
        }
        // Double push
        let double = ((push & 0x0000_0000_00FF_0000) << 8) & empty;
        let mut bb = double;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to - 16, to));
            bb &= bb - 1;
        }
        // Captures left (a-file pawns can't capture left)
        let cap_left = ((pawns & !0x0101_0101_0101_0101) << 7) & their_occ;
        let mut bb = cap_left & 0x00FF_FFFF_FFFF_FFFF;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to - 7, to));
            bb &= bb - 1;
        }
        let mut promo = cap_left & 0xFF00_0000_0000_0000;
        while promo != 0 {
            let to = promo.trailing_zeros() as u8;
            moves.push(new_promotion(to - 7, to, Piece::Queen));
            moves.push(new_promotion(to - 7, to, Piece::Rook));
            moves.push(new_promotion(to - 7, to, Piece::Bishop));
            moves.push(new_promotion(to - 7, to, Piece::Knight));
            promo &= promo - 1;
        }
        // Captures right (h-file pawns can't capture right)
        let cap_right = ((pawns & !0x8080_8080_8080_8080) << 9) & their_occ;
        let mut bb = cap_right & 0x00FF_FFFF_FFFF_FFFF;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to - 9, to));
            bb &= bb - 1;
        }
        let mut promo = cap_right & 0xFF00_0000_0000_0000;
        while promo != 0 {
            let to = promo.trailing_zeros() as u8;
            moves.push(new_promotion(to - 9, to, Piece::Queen));
            moves.push(new_promotion(to - 9, to, Piece::Rook));
            moves.push(new_promotion(to - 9, to, Piece::Bishop));
            moves.push(new_promotion(to - 9, to, Piece::Knight));
            promo &= promo - 1;
        }
        // En passant
        if let Some(ep) = board.ep_square {
            if ep >= 8 {
                let ep_bit = bit(ep);
                if (pawns & !0x0101_0101_0101_0101) << 7 & ep_bit != 0 {
                    moves.push(new_ep(ep - 7, ep));
                }
                if (pawns & !0x8080_8080_8080_8080) << 9 & ep_bit != 0 {
                    moves.push(new_ep(ep - 9, ep));
                }
            }
        }
    } else {
        // Black pawns - same logic but reversed
        let push = (pawns >> 8) & empty;
        let mut bb = push & 0xFFFF_FFFF_FFFF_FF00;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to + 8, to));
            bb &= bb - 1;
        }
        let mut promo = push & 0x0000_0000_0000_00FF;
        while promo != 0 {
            let to = promo.trailing_zeros() as u8;
            moves.push(new_promotion(to + 8, to, Piece::Queen));
            moves.push(new_promotion(to + 8, to, Piece::Rook));
            moves.push(new_promotion(to + 8, to, Piece::Bishop));
            moves.push(new_promotion(to + 8, to, Piece::Knight));
            promo &= promo - 1;
        }
        let double = ((push & 0x0000_FF00_0000_0000) >> 8) & empty;
        let mut bb = double;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to + 16, to));
            bb &= bb - 1;
        }
        // Captures right (from black's perspective, >> 7 is right-down which means +file)
        let cap_right = ((pawns & !0x8080_8080_8080_8080) >> 7) & their_occ;
        let mut bb = cap_right & 0xFFFF_FFFF_FFFF_FF00;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to + 7, to));
            bb &= bb - 1;
        }
        let mut promo = cap_right & 0x0000_0000_0000_00FF;
        while promo != 0 {
            let to = promo.trailing_zeros() as u8;
            moves.push(new_promotion(to + 7, to, Piece::Queen));
            moves.push(new_promotion(to + 7, to, Piece::Rook));
            moves.push(new_promotion(to + 7, to, Piece::Bishop));
            moves.push(new_promotion(to + 7, to, Piece::Knight));
            promo &= promo - 1;
        }
        // Captures left
        let cap_left = ((pawns & !0x0101_0101_0101_0101) >> 9) & their_occ;
        let mut bb = cap_left & 0xFFFF_FFFF_FFFF_FF00;
        while bb != 0 {
            let to = bb.trailing_zeros() as u8;
            moves.push(new_move(to + 9, to));
            bb &= bb - 1;
        }
        let mut promo = cap_left & 0x0000_0000_0000_00FF;
        while promo != 0 {
            let to = promo.trailing_zeros() as u8;
            moves.push(new_promotion(to + 9, to, Piece::Queen));
            moves.push(new_promotion(to + 9, to, Piece::Rook));
            moves.push(new_promotion(to + 9, to, Piece::Bishop));
            moves.push(new_promotion(to + 9, to, Piece::Knight));
            promo &= promo - 1;
        }
        if let Some(ep) = board.ep_square {
            if ep < 56 {
                let ep_bit = bit(ep);
                if (pawns & !0x8080_8080_8080_8080) >> 7 & ep_bit != 0 {
                    moves.push(new_ep(ep + 7, ep));
                }
                if (pawns & !0x0101_0101_0101_0101) >> 9 & ep_bit != 0 {
                    moves.push(new_ep(ep + 9, ep));
                }
            }
        }
    }

    // Knights
    let mut knights = board.pieces[us][Piece::Knight as usize];
    while knights != 0 {
        let from = knights.trailing_zeros() as u8;
        let mut attacks = TABLES.knight[from as usize] & !our_occ;
        while attacks != 0 {
            let to = attacks.trailing_zeros() as u8;
            moves.push(new_move(from, to));
            attacks &= attacks - 1;
        }
        knights &= knights - 1;
    }

    // Bishops
    let mut bishops = board.pieces[us][Piece::Bishop as usize];
    while bishops != 0 {
        let from = bishops.trailing_zeros() as u8;
        let mut attacks = bishop_attacks(from, all) & !our_occ;
        while attacks != 0 {
            let to = attacks.trailing_zeros() as u8;
            moves.push(new_move(from, to));
            attacks &= attacks - 1;
        }
        bishops &= bishops - 1;
    }

    // Rooks
    let mut rooks = board.pieces[us][Piece::Rook as usize];
    while rooks != 0 {
        let from = rooks.trailing_zeros() as u8;
        let mut attacks = rook_attacks(from, all) & !our_occ;
        while attacks != 0 {
            let to = attacks.trailing_zeros() as u8;
            moves.push(new_move(from, to));
            attacks &= attacks - 1;
        }
        rooks &= rooks - 1;
    }

    // Queens
    let mut queens = board.pieces[us][Piece::Queen as usize];
    while queens != 0 {
        let from = queens.trailing_zeros() as u8;
        let mut attacks = queen_attacks(from, all) & !our_occ;
        while attacks != 0 {
            let to = attacks.trailing_zeros() as u8;
            moves.push(new_move(from, to));
            attacks &= attacks - 1;
        }
        queens &= queens - 1;
    }

    // King
    let king_sq = board.king_square(board.side);
    let mut attacks = TABLES.king[king_sq as usize] & !our_occ;
    while attacks != 0 {
        let to = attacks.trailing_zeros() as u8;
        moves.push(new_move(king_sq, to));
        attacks &= attacks - 1;
    }

    // Castling
    if board.side == Color::White {
        if board.castling.has(CastleRights::WK) {
            // e1-g1, f1 and g1 must be empty, e1/f1/g1 not attacked
            if all & (bit(5) | bit(6)) == 0
                && !is_square_attacked(board, 4, Color::Black)
                && !is_square_attacked(board, 5, Color::Black)
                && !is_square_attacked(board, 6, Color::Black)
            {
                moves.push(new_castle(4, 6));
            }
        }
        if board.castling.has(CastleRights::WQ) {
            // e1-c1, b1/c1/d1 must be empty, e1/d1/c1 not attacked
            if all & (bit(1) | bit(2) | bit(3)) == 0
                && !is_square_attacked(board, 4, Color::Black)
                && !is_square_attacked(board, 3, Color::Black)
                && !is_square_attacked(board, 2, Color::Black)
            {
                moves.push(new_castle(4, 2));
            }
        }
    } else {
        if board.castling.has(CastleRights::BK) {
            if all & (bit(61) | bit(62)) == 0
                && !is_square_attacked(board, 60, Color::White)
                && !is_square_attacked(board, 61, Color::White)
                && !is_square_attacked(board, 62, Color::White)
            {
                moves.push(new_castle(60, 62));
            }
        }
        if board.castling.has(CastleRights::BQ) {
            if all & (bit(57) | bit(58) | bit(59)) == 0
                && !is_square_attacked(board, 60, Color::White)
                && !is_square_attacked(board, 59, Color::White)
                && !is_square_attacked(board, 58, Color::White)
            {
                moves.push(new_castle(60, 58));
            }
        }
    }

    moves
}

pub fn generate_legal_moves(board: &Board) -> Vec<Move> {
    let pseudo = generate_pseudo_legal_moves(board);
    let mut legal = Vec::with_capacity(pseudo.len());

    for m in pseudo {
        let new_board = make_move(board, m);
        // After our move, check that our king is not in check
        let king_sq = new_board.king_square(board.side);
        if !is_square_attacked(&new_board, king_sq, board.side.flip()) {
            legal.push(m);
        }
    }

    legal
}

/// Generate only capture moves (for quiescence search)
pub fn generate_captures(board: &Board) -> Vec<Move> {
    let legal = generate_legal_moves(board);
    legal.into_iter().filter(|&m| {
        let to = move_to(m);
        let flags = move_flags(m);
        flags == FLAG_EP || flags == FLAG_PROMOTION || board.piece_at(to).is_some()
    }).collect()
}

/// Perft: count leaf nodes at given depth (for testing)
pub fn perft(board: &Board, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }
    let moves = generate_legal_moves(board);
    if depth == 1 {
        return moves.len() as u64;
    }
    let mut count = 0u64;
    for m in moves {
        let new_board = make_move(board, m);
        count += perft(&new_board, depth - 1);
    }
    count
}
