/// Bitboard-based chess board representation.
/// Squares: a1=0, b1=1, ..., h1=7, a2=8, ..., h8=63

pub const STARTPOS: &str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Color {
    White = 0,
    Black = 1,
}

impl Color {
    pub fn flip(self) -> Color {
        match self {
            Color::White => Color::Black,
            Color::Black => Color::White,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Piece {
    Pawn = 0,
    Knight = 1,
    Bishop = 2,
    Rook = 3,
    Queen = 4,
    King = 5,
}

pub const ALL_PIECES: [Piece; 6] = [
    Piece::Pawn, Piece::Knight, Piece::Bishop, Piece::Rook, Piece::Queen, Piece::King,
];

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct CastleRights(pub u8);

impl CastleRights {
    pub const WK: u8 = 1;
    pub const WQ: u8 = 2;
    pub const BK: u8 = 4;
    pub const BQ: u8 = 8;
    pub const ALL: u8 = 15;

    pub fn has(self, flag: u8) -> bool {
        self.0 & flag != 0
    }

    pub fn remove(&mut self, flag: u8) {
        self.0 &= !flag;
    }
}

#[derive(Clone)]
pub struct Board {
    pub pieces: [[u64; 6]; 2], // [color][piece] bitboards
    pub occupied: [u64; 2],     // [color] all pieces
    pub all_occupied: u64,
    pub side: Color,
    pub castling: CastleRights,
    pub ep_square: Option<u8>,  // en passant target square
    pub halfmove: u16,
    pub fullmove: u16,
    pub zobrist: u64,
}

// Zobrist keys - initialized at compile time using a simple PRNG
pub static ZOBRIST: ZobristKeys = ZobristKeys::new();

pub struct ZobristKeys {
    pub pieces: [[[u64; 64]; 6]; 2], // [color][piece][square]
    pub side: u64,
    pub castling: [u64; 16],
    pub ep: [u64; 8], // file-based ep key
}

impl ZobristKeys {
    const fn new() -> Self {
        let mut pieces = [[[0u64; 64]; 6]; 2];
        let mut side = 0u64;
        let mut castling = [0u64; 16];
        let mut ep = [0u64; 8];

        // Simple xorshift64 PRNG for compile-time generation
        let mut state: u64 = 0x12345678_9ABCDEF0;

        macro_rules! next {
            ($s:expr) => {{
                $s ^= $s << 13;
                $s ^= $s >> 7;
                $s ^= $s << 17;
                $s
            }};
        }

        let mut c = 0;
        while c < 2 {
            let mut p = 0;
            while p < 6 {
                let mut sq = 0;
                while sq < 64 {
                    state = next!(state);
                    pieces[c][p][sq] = state;
                    sq += 1;
                }
                p += 1;
            }
            c += 1;
        }

        state = next!(state);
        side = state;

        let mut i = 0;
        while i < 16 {
            state = next!(state);
            castling[i] = state;
            i += 1;
        }

        let mut i = 0;
        while i < 8 {
            state = next!(state);
            ep[i] = state;
            i += 1;
        }

        ZobristKeys { pieces, side, castling, ep }
    }
}

// Square helpers
pub const fn sq(file: u8, rank: u8) -> u8 {
    rank * 8 + file
}

pub const fn file_of(sq: u8) -> u8 {
    sq & 7
}

pub const fn rank_of(sq: u8) -> u8 {
    sq >> 3
}

pub const fn bit(sq: u8) -> u64 {
    1u64 << sq
}

impl Board {
    pub fn new() -> Self {
        Self::from_fen(STARTPOS)
    }

    pub fn piece_at(&self, square: u8) -> Option<(Color, Piece)> {
        let b = bit(square);
        let color = if self.occupied[0] & b != 0 {
            Color::White
        } else if self.occupied[1] & b != 0 {
            Color::Black
        } else {
            return None;
        };

        for &p in &ALL_PIECES {
            if self.pieces[color as usize][p as usize] & b != 0 {
                return Some((color, p));
            }
        }
        None
    }

    pub fn set_piece(&mut self, color: Color, piece: Piece, square: u8) {
        let b = bit(square);
        self.pieces[color as usize][piece as usize] |= b;
        self.occupied[color as usize] |= b;
        self.all_occupied |= b;
        self.zobrist ^= ZOBRIST.pieces[color as usize][piece as usize][square as usize];
    }

    pub fn remove_piece(&mut self, color: Color, piece: Piece, square: u8) {
        let b = bit(square);
        self.pieces[color as usize][piece as usize] &= !b;
        self.occupied[color as usize] &= !b;
        self.all_occupied &= !b;
        self.zobrist ^= ZOBRIST.pieces[color as usize][piece as usize][square as usize];
    }

    pub fn from_fen(fen: &str) -> Self {
        let mut board = Board {
            pieces: [[0; 6]; 2],
            occupied: [0; 2],
            all_occupied: 0,
            side: Color::White,
            castling: CastleRights(0),
            ep_square: None,
            halfmove: 0,
            fullmove: 1,
            zobrist: 0,
        };

        let parts: Vec<&str> = fen.split_whitespace().collect();
        let ranks: Vec<&str> = parts[0].split('/').collect();

        for (ri, rank_str) in ranks.iter().enumerate() {
            let rank = 7 - ri as u8; // FEN starts from rank 8
            let mut file: u8 = 0;
            for ch in rank_str.chars() {
                if let Some(skip) = ch.to_digit(10) {
                    file += skip as u8;
                } else {
                    let color = if ch.is_uppercase() { Color::White } else { Color::Black };
                    let piece = match ch.to_ascii_lowercase() {
                        'p' => Piece::Pawn,
                        'n' => Piece::Knight,
                        'b' => Piece::Bishop,
                        'r' => Piece::Rook,
                        'q' => Piece::Queen,
                        'k' => Piece::King,
                        _ => panic!("Invalid FEN piece: {}", ch),
                    };
                    board.set_piece(color, piece, sq(file, rank));
                    file += 1;
                }
            }
        }

        if parts.len() > 1 {
            board.side = if parts[1] == "b" { Color::Black } else { Color::White };
            if board.side == Color::Black {
                board.zobrist ^= ZOBRIST.side;
            }
        }

        if parts.len() > 2 {
            let castle = parts[2];
            if castle.contains('K') { board.castling.0 |= CastleRights::WK; }
            if castle.contains('Q') { board.castling.0 |= CastleRights::WQ; }
            if castle.contains('k') { board.castling.0 |= CastleRights::BK; }
            if castle.contains('q') { board.castling.0 |= CastleRights::BQ; }
            board.zobrist ^= ZOBRIST.castling[board.castling.0 as usize];
        }

        if parts.len() > 3 && parts[3] != "-" {
            let bytes = parts[3].as_bytes();
            let file = bytes[0] - b'a';
            let rank = bytes[1] - b'1';
            board.ep_square = Some(sq(file, rank));
            board.zobrist ^= ZOBRIST.ep[file as usize];
        }

        if parts.len() > 4 {
            board.halfmove = parts[4].parse().unwrap_or(0);
        }
        if parts.len() > 5 {
            board.fullmove = parts[5].parse().unwrap_or(1);
        }

        board
    }

    pub fn to_fen(&self) -> String {
        let mut s = String::new();
        for rank in (0..8).rev() {
            let mut empty = 0;
            for file in 0..8 {
                match self.piece_at(sq(file, rank)) {
                    Some((color, piece)) => {
                        if empty > 0 {
                            s.push(char::from_digit(empty, 10).unwrap());
                            empty = 0;
                        }
                        let ch = match piece {
                            Piece::Pawn => 'p',
                            Piece::Knight => 'n',
                            Piece::Bishop => 'b',
                            Piece::Rook => 'r',
                            Piece::Queen => 'q',
                            Piece::King => 'k',
                        };
                        s.push(if color == Color::White { ch.to_ascii_uppercase() } else { ch });
                    }
                    None => empty += 1,
                }
            }
            if empty > 0 {
                s.push(char::from_digit(empty, 10).unwrap());
            }
            if rank > 0 { s.push('/'); }
        }

        s.push(' ');
        s.push(if self.side == Color::White { 'w' } else { 'b' });

        s.push(' ');
        if self.castling.0 == 0 {
            s.push('-');
        } else {
            if self.castling.has(CastleRights::WK) { s.push('K'); }
            if self.castling.has(CastleRights::WQ) { s.push('Q'); }
            if self.castling.has(CastleRights::BK) { s.push('k'); }
            if self.castling.has(CastleRights::BQ) { s.push('q'); }
        }

        s.push(' ');
        match self.ep_square {
            Some(ep) => {
                s.push((b'a' + file_of(ep)) as char);
                s.push((b'1' + rank_of(ep)) as char);
            }
            None => s.push('-'),
        }

        s.push_str(&format!(" {} {}", self.halfmove, self.fullmove));
        s
    }

    pub fn king_square(&self, color: Color) -> u8 {
        self.pieces[color as usize][Piece::King as usize].trailing_zeros() as u8
    }
}
