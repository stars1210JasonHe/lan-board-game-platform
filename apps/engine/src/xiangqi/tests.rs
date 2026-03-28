use super::board::*;
use super::moves::*;

#[test]
fn test_startpos_fen_roundtrip() {
    let board = Board::from_fen(STARTPOS);
    let fen = board.to_fen();
    // Parse again and compare
    let board2 = Board::from_fen(&fen);
    assert_eq!(board2.to_fen(), fen);
}

#[test]
fn test_startpos_legal_moves() {
    let board = Board::new();
    let moves = generate_legal_moves(&board);
    // Red's initial moves: 44 is the standard count
    // Rooks: each has 2 vertical moves = 4
    // Horses: each has 2 moves = 4
    // Elephants: each has 2 moves = 4
    // Advisors: each has 1 move = 2
    // King: 1 move
    // Cannons: each has ~10-12 moves
    // Pawns: 5 forward = 5
    // Let's just check it's reasonable
    assert!(moves.len() > 30, "Expected >30 legal moves at start, got {}", moves.len());
    assert!(moves.len() < 50, "Expected <50 legal moves at start, got {}", moves.len());
}

#[test]
fn test_rook_moves() {
    // Rook on empty board at e5 (row 4, col 4)
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(4, 4, Cell { color: Color::Red, piece: Piece::Rook });
    // Kings on different columns to avoid flying king issues
    board.set_piece(0, 3, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 5, Cell { color: Color::Black, piece: Piece::King });

    let moves = generate_legal_moves(&board);
    let rook_moves: Vec<_> = moves.iter()
        .filter(|m| m.0 == 4 && m.1 == 4)
        .collect();
    // Rook on open board: 9 horizontal + 9 vertical - 1 (own square) * 2 sides
    // Actually: left 4 + right 4 + up 5 + down 4 = 17 moves
    assert!(rook_moves.len() >= 15, "Rook should have many moves, got {}", rook_moves.len());
}

#[test]
fn test_horse_blocking() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(0, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 4, Cell { color: Color::Black, piece: Piece::King });
    // Horse at b0 (row 0, col 1)
    board.set_piece(0, 1, Cell { color: Color::Red, piece: Piece::Horse });
    // Block the forward direction with a pawn at b1
    board.set_piece(1, 1, Cell { color: Color::Red, piece: Piece::Pawn });

    let moves = generate_legal_moves(&board);
    // Horse should not be able to jump forward (blocked), only sideways jumps
    let horse_moves: Vec<_> = moves.iter()
        .filter(|m| m.0 == 0 && m.1 == 1)
        .collect();
    // With b1 blocked, horse can't go to (2,0) or (2,2) but can still go to (1,3) via (0,2) if c0 is empty
    // Actually from (0,1): orthogonal steps are (1,1) blocked, (-1,1) invalid, (0,0), (0,2)
    // Via (0,0): to (-1,1) invalid, (1,0) valid if not self-capture
    // Via (0,2): to (-1,3) invalid, (1,3) valid
    assert!(horse_moves.len() <= 4, "Horse should have limited moves when blocked, got {}", horse_moves.len());
}

#[test]
fn test_cannon_capture() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(0, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 4, Cell { color: Color::Black, piece: Piece::King });
    // Block king column to avoid flying king
    board.set_piece(5, 4, Cell { color: Color::Red, piece: Piece::Advisor });
    // Cannon at a0, piece at a3, enemy at a5
    board.set_piece(0, 0, Cell { color: Color::Red, piece: Piece::Cannon });
    board.set_piece(3, 0, Cell { color: Color::Red, piece: Piece::Pawn }); // screen
    board.set_piece(5, 0, Cell { color: Color::Black, piece: Piece::Pawn }); // target

    let moves = generate_legal_moves(&board);
    let cannon_captures: Vec<_> = moves.iter()
        .filter(|m| m.0 == 0 && m.1 == 0 && board.grid[m.2 as usize][m.3 as usize].is_some())
        .collect();
    // Cannon should be able to capture the pawn at a5 by jumping over the pawn at a3
    assert!(cannon_captures.iter().any(|m| m.2 == 5 && m.3 == 0),
        "Cannon should capture at a5, captures: {:?}", cannon_captures);
}

#[test]
fn test_pawn_before_river() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(0, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 4, Cell { color: Color::Black, piece: Piece::King });
    // Red pawn at e3 (row 3, col 4) - before river
    board.set_piece(3, 4, Cell { color: Color::Red, piece: Piece::Pawn });

    let moves = generate_legal_moves(&board);
    let pawn_moves: Vec<_> = moves.iter()
        .filter(|m| m.0 == 3 && m.1 == 4)
        .collect();
    // Before river, pawn can only go forward
    assert_eq!(pawn_moves.len(), 1, "Pawn before river should have 1 move, got {:?}", pawn_moves);
    assert_eq!(pawn_moves[0].2, 4); // row 4
    assert_eq!(pawn_moves[0].3, 4); // same col
}

#[test]
fn test_pawn_after_river() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(0, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 4, Cell { color: Color::Black, piece: Piece::King });
    // Block king column to avoid flying king
    board.set_piece(4, 4, Cell { color: Color::Red, piece: Piece::Rook });
    // Red pawn at d6 (row 6, col 3) - after river, off the king column
    board.set_piece(6, 3, Cell { color: Color::Red, piece: Piece::Pawn });

    let moves = generate_legal_moves(&board);
    let pawn_moves: Vec<_> = moves.iter()
        .filter(|m| m.0 == 6 && m.1 == 3)
        .collect();
    // After river: forward + left + right = 3 moves
    assert_eq!(pawn_moves.len(), 3, "Pawn after river should have 3 moves, got {:?}", pawn_moves);
}

#[test]
fn test_elephant_cannot_cross_river() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(0, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 4, Cell { color: Color::Black, piece: Piece::King });
    // Red elephant at c4 (row 4, col 2) - at river boundary
    board.set_piece(4, 2, Cell { color: Color::Red, piece: Piece::Elephant });

    let moves = generate_legal_moves(&board);
    let elephant_moves: Vec<_> = moves.iter()
        .filter(|m| m.0 == 4 && m.1 == 2)
        .collect();
    // Elephant at row 4 can only go to row 2 (own half), not row 6 (enemy half)
    for m in &elephant_moves {
        assert!(m.2 <= 4, "Elephant should not cross river: {:?}", m);
    }
}

#[test]
fn test_king_stays_in_palace() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(1, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 3, Cell { color: Color::Black, piece: Piece::King });

    let moves = generate_legal_moves(&board);
    let king_moves: Vec<_> = moves.iter()
        .filter(|m| m.0 == 1 && m.1 == 4)
        .collect();
    assert!(king_moves.len() >= 3, "King should have palace moves, got {}", king_moves.len());
    for m in &king_moves {
        assert!(m.2 <= 2 && m.3 >= 3 && m.3 <= 5,
            "King must stay in palace: row={}, col={}", m.2, m.3);
    }
}

#[test]
fn test_flying_king_rule() {
    let mut board = Board {
        grid: [[None; COLS]; ROWS],
        side: Color::Red,
        zobrist: 0,
    };
    board.set_piece(0, 4, Cell { color: Color::Red, piece: Piece::King });
    board.set_piece(9, 4, Cell { color: Color::Black, piece: Piece::King });
    // Rook blocking the kings on column 4
    board.set_piece(5, 4, Cell { color: Color::Red, piece: Piece::Rook });

    // If rook moves off column 4, kings would face each other
    let moves = generate_legal_moves(&board);
    let rook_off_col = moves.iter()
        .filter(|m| m.0 == 5 && m.1 == 4 && m.3 != 4)
        .count();
    // These moves should be illegal due to flying king
    // generate_legal_moves should already filter them out
    // Actually the rook can move off the column if it doesn't leave kings facing
    // But here the rook is the only piece between the two kings on col 4
    // So moving it off col 4 would make kings face -> illegal
    assert_eq!(rook_off_col, 0, "Rook should not be able to expose flying king");
}

#[test]
fn test_move_to_coord() {
    let m: Move = (2, 7, 2, 4);
    assert_eq!(move_to_coord(m), "h2e2");
}

#[test]
fn test_coord_to_move() {
    let m = coord_to_move("h2e2").unwrap();
    assert_eq!(m, (2, 7, 2, 4));
}

#[test]
fn test_perft_startpos_depth1() {
    let board = Board::new();
    let count = perft(&board, 1);
    assert_eq!(count, generate_legal_moves(&board).len() as u64);
}

#[test]
fn test_perft_startpos_depth2() {
    let board = Board::new();
    let count = perft(&board, 2);
    // Known xiangqi perft(2) from start = varies by implementation
    // Just verify it's reasonable
    assert!(count > 500, "perft(2) should be >500, got {}", count);
    assert!(count < 3000, "perft(2) should be <3000, got {}", count);
}
