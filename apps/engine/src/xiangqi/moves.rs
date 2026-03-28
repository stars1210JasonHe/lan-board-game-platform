use super::board::*;

/// Move: (from_row, from_col, to_row, to_col)
pub type Move = (u8, u8, u8, u8);

pub fn move_to_coord(m: Move) -> String {
    // Output format: column-letter + row-number for from and to
    // e.g. h2e2 means (row=2, col=7) -> (row=2, col=4)
    // Columns: a=0, b=1, ..., i=8
    // Rows: 0-9
    format!("{}{}{}{}",
        (b'a' + m.1) as char, m.0,
        (b'a' + m.3) as char, m.2)
}

pub fn coord_to_move(s: &str) -> Option<Move> {
    let bytes = s.as_bytes();
    if bytes.len() < 4 { return None; }
    let fc = bytes[0].wrapping_sub(b'a');
    let fr = bytes[1].wrapping_sub(b'0');
    let tc = bytes[2].wrapping_sub(b'a');
    let tr = bytes[3].wrapping_sub(b'0');
    if fc < 9 && fr < 10 && tc < 9 && tr < 10 {
        Some((fr, fc, tr, tc))
    } else {
        None
    }
}

fn in_palace(row: usize, col: usize, color: Color) -> bool {
    let (min_row, max_row) = match color {
        Color::Red => (0, 2),
        Color::Black => (7, 9),
    };
    row >= min_row && row <= max_row && col >= 3 && col <= 5
}

fn in_own_half(row: usize, color: Color) -> bool {
    match color {
        Color::Red => row <= 4,
        Color::Black => row >= 5,
    }
}

fn crossed_river(row: usize, color: Color) -> bool {
    !in_own_half(row, color)
}

fn in_bounds(r: i32, c: i32) -> bool {
    r >= 0 && r < ROWS as i32 && c >= 0 && c < COLS as i32
}

/// Generate all pseudo-legal moves (doesn't check for self-check or flying kings)
pub fn generate_pseudo_legal_moves(board: &Board) -> Vec<Move> {
    let mut moves = Vec::with_capacity(128);
    let us = board.side;

    for r in 0..ROWS {
        for c in 0..COLS {
            let cell = match board.grid[r][c] {
                Some(cell) if cell.color == us => cell,
                _ => continue,
            };

            match cell.piece {
                Piece::King => {
                    // One step orthogonally within palace
                    for &(dr, dc) in &[(0i32, 1i32), (0, -1), (1, 0), (-1, 0)] {
                        let nr = r as i32 + dr;
                        let nc = c as i32 + dc;
                        if in_bounds(nr, nc) && in_palace(nr as usize, nc as usize, us) {
                            if let Some(target) = board.grid[nr as usize][nc as usize] {
                                if target.color != us {
                                    moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                }
                            } else {
                                moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            }
                        }
                    }
                }

                Piece::Advisor => {
                    // One step diagonally within palace
                    for &(dr, dc) in &[(1i32, 1i32), (1, -1), (-1, 1), (-1, -1)] {
                        let nr = r as i32 + dr;
                        let nc = c as i32 + dc;
                        if in_bounds(nr, nc) && in_palace(nr as usize, nc as usize, us) {
                            if let Some(target) = board.grid[nr as usize][nc as usize] {
                                if target.color != us {
                                    moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                }
                            } else {
                                moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            }
                        }
                    }
                }

                Piece::Elephant => {
                    // Two steps diagonally, must stay in own half, blocking point must be empty
                    for &(dr, dc) in &[(2i32, 2i32), (2, -2), (-2, 2), (-2, -2)] {
                        let nr = r as i32 + dr;
                        let nc = c as i32 + dc;
                        let br = r as i32 + dr / 2; // blocking square
                        let bc = c as i32 + dc / 2;
                        if in_bounds(nr, nc) && in_own_half(nr as usize, us)
                            && board.grid[br as usize][bc as usize].is_none()
                        {
                            if let Some(target) = board.grid[nr as usize][nc as usize] {
                                if target.color != us {
                                    moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                }
                            } else {
                                moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            }
                        }
                    }
                }

                Piece::Horse => {
                    // L-shape: one step orthogonal, then one diagonal; blocking on the orthogonal step
                    for &(dr1, dc1, dr2, dc2) in &[
                        (1i32, 0i32, 2i32, 1i32), (1, 0, 2, -1),
                        (-1, 0, -2, 1), (-1, 0, -2, -1),
                        (0, 1, 1, 2), (0, 1, -1, 2),
                        (0, -1, 1, -2), (0, -1, -1, -2),
                    ] {
                        let br = r as i32 + dr1;
                        let bc = c as i32 + dc1;
                        let nr = r as i32 + dr2;
                        let nc = c as i32 + dc2;
                        if in_bounds(nr, nc) && in_bounds(br, bc)
                            && board.grid[br as usize][bc as usize].is_none()
                        {
                            if let Some(target) = board.grid[nr as usize][nc as usize] {
                                if target.color != us {
                                    moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                }
                            } else {
                                moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            }
                        }
                    }
                }

                Piece::Rook => {
                    // Straight lines until blocked
                    for &(dr, dc) in &[(0i32, 1i32), (0, -1), (1, 0), (-1, 0)] {
                        let mut nr = r as i32 + dr;
                        let mut nc = c as i32 + dc;
                        while in_bounds(nr, nc) {
                            if let Some(target) = board.grid[nr as usize][nc as usize] {
                                if target.color != us {
                                    moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                }
                                break;
                            }
                            moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            nr += dr;
                            nc += dc;
                        }
                    }
                }

                Piece::Cannon => {
                    // Straight lines: move like rook but capture by jumping exactly one piece
                    for &(dr, dc) in &[(0i32, 1i32), (0, -1), (1, 0), (-1, 0)] {
                        let mut nr = r as i32 + dr;
                        let mut nc = c as i32 + dc;
                        // Non-capture moves (slide until blocked)
                        while in_bounds(nr, nc) {
                            if board.grid[nr as usize][nc as usize].is_some() {
                                break;
                            }
                            moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            nr += dr;
                            nc += dc;
                        }
                        // Jump over the blocker and look for capture
                        if in_bounds(nr, nc) {
                            nr += dr;
                            nc += dc;
                            while in_bounds(nr, nc) {
                                if let Some(target) = board.grid[nr as usize][nc as usize] {
                                    if target.color != us {
                                        moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                    }
                                    break;
                                }
                                nr += dr;
                                nc += dc;
                            }
                        }
                    }
                }

                Piece::Pawn => {
                    // Before crossing river: forward only
                    // After crossing river: forward + sideways
                    let forward = match us {
                        Color::Red => (1i32, 0i32),
                        Color::Black => (-1, 0),
                    };

                    let mut dirs = vec![forward];
                    if crossed_river(r, us) {
                        dirs.push((0, 1));
                        dirs.push((0, -1));
                    }

                    for (dr, dc) in dirs {
                        let nr = r as i32 + dr;
                        let nc = c as i32 + dc;
                        if in_bounds(nr, nc) {
                            if let Some(target) = board.grid[nr as usize][nc as usize] {
                                if target.color != us {
                                    moves.push((r as u8, c as u8, nr as u8, nc as u8));
                                }
                            } else {
                                moves.push((r as u8, c as u8, nr as u8, nc as u8));
                            }
                        }
                    }
                }
            }
        }
    }

    moves
}

/// Check if a color's king is attacked
pub fn is_in_check(board: &Board, color: Color) -> bool {
    let (kr, kc) = match board.find_king(color) { Some(k) => k, None => return false };
    let enemy = color.flip();

    // Check each enemy piece
    for r in 0..ROWS {
        for c in 0..COLS {
            if let Some(cell) = board.grid[r][c] {
                if cell.color != enemy { continue; }
                if can_attack(board, r, c, kr, kc, cell.piece, enemy) {
                    return true;
                }
            }
        }
    }
    false
}

/// Check if a piece at (fr,fc) can attack square (tr,tc)
fn can_attack(board: &Board, fr: usize, fc: usize, tr: usize, tc: usize, piece: Piece, _color: Color) -> bool {
    let dr = tr as i32 - fr as i32;
    let dc = tc as i32 - fc as i32;

    match piece {
        Piece::Rook => {
            if fr != tr && fc != tc { return false; }
            // Check path is clear
            if fr == tr {
                let (min_c, max_c) = if fc < tc { (fc + 1, tc) } else { (tc + 1, fc) };
                for c in min_c..max_c {
                    if board.grid[fr][c].is_some() { return false; }
                }
            } else {
                let (min_r, max_r) = if fr < tr { (fr + 1, tr) } else { (tr + 1, fr) };
                for r in min_r..max_r {
                    if board.grid[r][fc].is_some() { return false; }
                }
            }
            true
        }
        Piece::Cannon => {
            if fr != tr && fc != tc { return false; }
            // Must jump exactly one piece
            let mut count = 0;
            if fr == tr {
                let (min_c, max_c) = if fc < tc { (fc + 1, tc) } else { (tc + 1, fc) };
                for c in min_c..max_c {
                    if board.grid[fr][c].is_some() { count += 1; }
                }
            } else {
                let (min_r, max_r) = if fr < tr { (fr + 1, tr) } else { (tr + 1, fr) };
                for r in min_r..max_r {
                    if board.grid[r][fc].is_some() { count += 1; }
                }
            }
            count == 1
        }
        Piece::Horse => {
            // L-shape with blocking check
            let adr = dr.unsigned_abs() as usize;
            let adc = dc.unsigned_abs() as usize;
            if !((adr == 2 && adc == 1) || (adr == 1 && adc == 2)) { return false; }
            // Check blocking square
            if adr == 2 {
                let br = fr as i32 + dr.signum();
                if board.grid[br as usize][fc].is_some() { return false; }
            } else {
                let bc = fc as i32 + dc.signum();
                if board.grid[fr][bc as usize].is_some() { return false; }
            }
            true
        }
        Piece::Pawn => {
            let forward = match _color {
                Color::Red => 1i32,
                Color::Black => -1,
            };
            if dr == forward && dc == 0 { return true; }
            if crossed_river(fr, _color) && dr == 0 && dc.unsigned_abs() == 1 { return true; }
            false
        }
        Piece::King => {
            // Kings can "attack" across the board column (flying king rule)
            if fc == tc && fr != tr {
                // Check if there are no pieces between
                let (min_r, max_r) = if fr < tr { (fr + 1, tr) } else { (tr + 1, fr) };
                for r in min_r..max_r {
                    if board.grid[r][fc].is_some() { return false; }
                }
                return true;
            }
            // Normal one-step
            (dr.unsigned_abs() + dc.unsigned_abs()) == 1
        }
        Piece::Advisor => {
            dr.unsigned_abs() == 1 && dc.unsigned_abs() == 1
        }
        Piece::Elephant => {
            // Elephants don't really "attack" across the river but for completeness
            if dr.unsigned_abs() != 2 || dc.unsigned_abs() != 2 { return false; }
            let br = (fr as i32 + dr / 2) as usize;
            let bc = (fc as i32 + dc / 2) as usize;
            board.grid[br][bc].is_none()
        }
    }
}

pub fn make_move(board: &Board, m: Move) -> Board {
    let mut b = board.clone();
    let (fr, fc, tr, tc) = (m.0 as usize, m.1 as usize, m.2 as usize, m.3 as usize);

    b.remove_piece(tr, tc); // capture if any
    let cell = b.remove_piece(fr, fc).expect("No piece at from square");
    b.set_piece(tr, tc, cell);

    b.zobrist ^= ZOBRIST.side;
    b.side = b.side.flip();
    b
}

pub fn generate_legal_moves(board: &Board) -> Vec<Move> {
    let pseudo = generate_pseudo_legal_moves(board);
    let us = board.side;

    pseudo.into_iter().filter(|&m| {
        // Cannot capture the enemy king
        if let Some(target) = board.grid[m.2 as usize][m.3 as usize] {
            if target.piece == Piece::King { return false; }
        }
        let new_board = make_move(board, m);
        // After our move, our king must not be in check
        // and kings must not be facing
        !is_in_check(&new_board, us) && !new_board.kings_facing()
    }).collect()
}

/// Generate captures only (for quiescence)
pub fn generate_captures(board: &Board) -> Vec<Move> {
    generate_legal_moves(board).into_iter().filter(|&m| {
        board.grid[m.2 as usize][m.3 as usize].is_some()
    }).collect()
}

/// Perft for xiangqi
pub fn perft(board: &Board, depth: u32) -> u64 {
    if depth == 0 { return 1; }
    let moves = generate_legal_moves(board);
    if depth == 1 { return moves.len() as u64; }
    let mut count = 0u64;
    for m in moves {
        let new_board = make_move(board, m);
        count += perft(&new_board, depth - 1);
    }
    count
}
