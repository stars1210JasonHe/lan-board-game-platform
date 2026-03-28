/// Xiangqi (Chinese Chess) board representation.
/// 10 rows × 9 columns. Array-based.
/// Red = uppercase, Black = lowercase (same as server convention).
/// Rows: 0=Red's back rank (bottom), 9=Black's back rank (top).
/// Columns: 0=a (left) to 8=i (right).

pub const STARTPOS: &str = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w";

pub const ROWS: usize = 10;
pub const COLS: usize = 9;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Color {
    Red = 0,   // Equivalent to White (moves first)
    Black = 1,
}

impl Color {
    pub fn flip(self) -> Color {
        match self {
            Color::Red => Color::Black,
            Color::Black => Color::Red,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Piece {
    King = 0,     // K/k - General/帅/将
    Advisor = 1,  // A/a - 仕/士
    Elephant = 2, // B/b (or E/e) - 相/象
    Horse = 3,    // N/n (or H/h) - 马
    Rook = 4,     // R/r - 车
    Cannon = 5,   // C/c - 炮
    Pawn = 6,     // P/p - 兵/卒
}

pub const ALL_PIECES: [Piece; 7] = [
    Piece::King, Piece::Advisor, Piece::Elephant, Piece::Horse,
    Piece::Rook, Piece::Cannon, Piece::Pawn,
];

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Cell {
    pub color: Color,
    pub piece: Piece,
}

#[derive(Clone)]
pub struct Board {
    pub grid: [[Option<Cell>; COLS]; ROWS],
    pub side: Color,
    pub zobrist: u64,
}

// Zobrist keys
pub struct ZobristKeys {
    pub pieces: [[[u64; COLS]; ROWS]; 14], // 7 piece types × 2 colors
    pub side: u64,
}

fn piece_index(color: Color, piece: Piece) -> usize {
    color as usize * 7 + piece as usize
}

pub static ZOBRIST: std::sync::LazyLock<ZobristKeys> = std::sync::LazyLock::new(|| {
    let mut keys = ZobristKeys {
        pieces: [[[0u64; COLS]; ROWS]; 14],
        side: 0,
    };
    let mut state: u64 = 0xABCDEF01_23456789;
    let mut next = || -> u64 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };

    for pi in 0..14 {
        for r in 0..ROWS {
            for c in 0..COLS {
                keys.pieces[pi][r][c] = next();
            }
        }
    }
    keys.side = next();
    keys
});

impl Board {
    pub fn new() -> Self {
        Self::from_fen(STARTPOS)
    }

    pub fn from_fen(fen: &str) -> Self {
        let mut board = Board {
            grid: [[None; COLS]; ROWS],
            side: Color::Red,
            zobrist: 0,
        };

        let parts: Vec<&str> = fen.split_whitespace().collect();
        let ranks: Vec<&str> = parts[0].split('/').collect();

        // FEN rank order: rank 9 (black's back) first, rank 0 (red's back) last
        for (ri, rank_str) in ranks.iter().enumerate() {
            let row = ROWS - 1 - ri;
            let mut col = 0usize;
            for ch in rank_str.chars() {
                if let Some(skip) = ch.to_digit(10) {
                    col += skip as usize;
                } else {
                    let color = if ch.is_uppercase() { Color::Red } else { Color::Black };
                    let piece = match ch.to_ascii_lowercase() {
                        'k' => Piece::King,
                        'a' => Piece::Advisor,
                        'b' | 'e' => Piece::Elephant,
                        'n' | 'h' => Piece::Horse,
                        'r' => Piece::Rook,
                        'c' => Piece::Cannon,
                        'p' => Piece::Pawn,
                        _ => panic!("Invalid FEN piece: {}", ch),
                    };
                    let cell = Cell { color, piece };
                    board.grid[row][col] = Some(cell);
                    let pi = piece_index(color, piece);
                    board.zobrist ^= ZOBRIST.pieces[pi][row][col];
                    col += 1;
                }
            }
        }

        if parts.len() > 1 {
            board.side = match parts[1] {
                "b" => Color::Black,
                _ => Color::Red,
            };
            if board.side == Color::Black {
                board.zobrist ^= ZOBRIST.side;
            }
        }

        board
    }

    pub fn to_fen(&self) -> String {
        let mut s = String::new();
        for row in (0..ROWS).rev() {
            let mut empty = 0;
            for col in 0..COLS {
                match self.grid[row][col] {
                    Some(cell) => {
                        if empty > 0 {
                            s.push(char::from_digit(empty, 10).unwrap());
                            empty = 0;
                        }
                        let ch = match cell.piece {
                            Piece::King => 'k',
                            Piece::Advisor => 'a',
                            Piece::Elephant => 'b',
                            Piece::Horse => 'n',
                            Piece::Rook => 'r',
                            Piece::Cannon => 'c',
                            Piece::Pawn => 'p',
                        };
                        s.push(if cell.color == Color::Red { ch.to_ascii_uppercase() } else { ch });
                    }
                    None => empty += 1,
                }
            }
            if empty > 0 {
                s.push(char::from_digit(empty, 10).unwrap());
            }
            if row > 0 { s.push('/'); }
        }
        s.push(' ');
        s.push(if self.side == Color::Red { 'w' } else { 'b' });
        s
    }

    pub fn set_piece(&mut self, row: usize, col: usize, cell: Cell) {
        self.grid[row][col] = Some(cell);
        let pi = piece_index(cell.color, cell.piece);
        self.zobrist ^= ZOBRIST.pieces[pi][row][col];
    }

    pub fn remove_piece(&mut self, row: usize, col: usize) -> Option<Cell> {
        if let Some(cell) = self.grid[row][col] {
            let pi = piece_index(cell.color, cell.piece);
            self.zobrist ^= ZOBRIST.pieces[pi][row][col];
            self.grid[row][col] = None;
            Some(cell)
        } else {
            None
        }
    }

    pub fn find_king(&self, color: Color) -> Option<(usize, usize)> {
        for r in 0..ROWS {
            for c in 0..COLS {
                if let Some(cell) = self.grid[r][c] {
                    if cell.color == color && cell.piece == Piece::King {
                        return Some((r, c));
                    }
                }
            }
        }
        None
    }

    /// Check if two kings face each other on the same column with no pieces between
    pub fn kings_facing(&self) -> bool {
        let (rr, rc) = match self.find_king(Color::Red) { Some(k) => k, None => return false };
        let (br, bc) = match self.find_king(Color::Black) { Some(k) => k, None => return false };
        if rc != bc { return false; }
        for r in (rr + 1)..br {
            if self.grid[r][rc].is_some() {
                return false;
            }
        }
        true
    }
}
