use super::board::*;
use super::moves::*;

#[test]
fn test_startpos_fen_roundtrip() {
    let board = Board::from_fen(STARTPOS);
    assert_eq!(board.to_fen(), STARTPOS);
}

#[test]
fn test_startpos_legal_moves() {
    let board = Board::new();
    let moves = generate_legal_moves(&board);
    assert_eq!(moves.len(), 20); // 16 pawn moves + 4 knight moves
}

#[test]
fn test_perft_startpos_depth1() {
    let board = Board::new();
    assert_eq!(perft(&board, 1), 20);
}

#[test]
fn test_perft_startpos_depth2() {
    let board = Board::new();
    assert_eq!(perft(&board, 2), 400);
}

#[test]
fn test_perft_startpos_depth3() {
    let board = Board::new();
    assert_eq!(perft(&board, 3), 8902);
}

#[test]
fn test_perft_startpos_depth4() {
    let board = Board::new();
    assert_eq!(perft(&board, 4), 197281);
}

// Kiwipete position - great for testing complex moves
#[test]
fn test_perft_kiwipete_depth1() {
    let board = Board::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
    assert_eq!(perft(&board, 1), 48);
}

#[test]
fn test_perft_kiwipete_depth2() {
    let board = Board::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
    assert_eq!(perft(&board, 2), 2039);
}

#[test]
fn test_perft_kiwipete_depth3() {
    let board = Board::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
    assert_eq!(perft(&board, 3), 97862);
}

// Position 3: en passant + promotion heavy
#[test]
fn test_perft_position3_depth1() {
    let board = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    assert_eq!(perft(&board, 1), 14);
}

#[test]
fn test_perft_position3_depth2() {
    let board = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    assert_eq!(perft(&board, 2), 191);
}

#[test]
fn test_perft_position3_depth3() {
    let board = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    assert_eq!(perft(&board, 3), 2812);
}

// Position 4: castling rights
#[test]
fn test_perft_position4_depth1() {
    let board = Board::from_fen("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1");
    assert_eq!(perft(&board, 1), 6);
}

#[test]
fn test_perft_position4_depth2() {
    let board = Board::from_fen("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1");
    assert_eq!(perft(&board, 2), 264);
}

#[test]
fn test_perft_position4_depth3() {
    let board = Board::from_fen("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1");
    assert_eq!(perft(&board, 3), 9467);
}

// Position 5
#[test]
fn test_perft_position5_depth1() {
    let board = Board::from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8");
    assert_eq!(perft(&board, 1), 44);
}

#[test]
fn test_perft_position5_depth2() {
    let board = Board::from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8");
    assert_eq!(perft(&board, 2), 1486);
}

#[test]
fn test_perft_position5_depth3() {
    let board = Board::from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8");
    assert_eq!(perft(&board, 3), 62379);
}

#[test]
fn test_en_passant() {
    // White pawn on e5, black just played d7-d5
    let board = Board::from_fen("rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3");
    let moves = generate_legal_moves(&board);
    let ep_moves: Vec<_> = moves.iter().filter(|&&m| move_flags(m) == FLAG_EP).collect();
    assert_eq!(ep_moves.len(), 1);
    let ep = ep_moves[0];
    assert_eq!(move_to_uci(*ep), "e5d6");
}

#[test]
fn test_castling() {
    let board = Board::from_fen("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1");
    let moves = generate_legal_moves(&board);
    let castle_moves: Vec<_> = moves.iter()
        .filter(|&&m| move_flags(m) == FLAG_CASTLE)
        .collect();
    assert_eq!(castle_moves.len(), 2); // Kingside + queenside
}

#[test]
fn test_promotion() {
    let board = Board::from_fen("8/P7/8/8/8/8/8/4K2k w - - 0 1");
    let moves = generate_legal_moves(&board);
    let promo_moves: Vec<_> = moves.iter()
        .filter(|&&m| move_flags(m) == FLAG_PROMOTION)
        .collect();
    assert_eq!(promo_moves.len(), 4); // Q, R, B, N
}

#[test]
fn test_checkmate_detection() {
    // Scholar's mate position - black is checkmated
    let board = Board::from_fen("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3");
    let moves = generate_legal_moves(&board);
    assert_eq!(moves.len(), 0);
    assert!(in_check(&board));
}

#[test]
fn test_stalemate_detection() {
    let board = Board::from_fen("k7/8/1K6/8/8/8/8/8 b - - 0 1");
    let moves = generate_legal_moves(&board);
    // Black king on a8, white king on b6 - black has moves
    // Let me use a real stalemate position
    let board = Board::from_fen("k7/8/2K5/8/8/8/8/8 b - - 0 1");
    let moves = generate_legal_moves(&board);
    // Black king on a8 with white king on c6
    // a8 king can go to: a7 (attacked by c6), b8 (not attacked), b7 (attacked by c6)
    // So not stalemate - let me find proper stalemate
    let board = Board::from_fen("K7/8/1k6/8/8/8/8/8 b - - 0 1");
    // This isn't stalemate either. Let me use a known one:
    let board = Board::from_fen("k7/8/1K1Q4/8/8/8/8/8 b - - 0 1");
    // King on a8, White K b6 Q d6 - black king: a8 can go to a7(attacked by K and Q), b8(attacked by Q), b7(attacked by K)
    // Wait - checking properly:
    // a7: attacked by Kb6? yes (adjacent). attacked by Qd6? Q on d6 can reach a3,b4,c5,d1-d8,e6,f6... a7 is not on Q's line
    // Actually let me use the classic stalemate
    let board = Board::from_fen("k7/2Q5/1K6/8/8/8/8/8 b - - 0 1");
    let moves = generate_legal_moves(&board);
    // Ka8: can go a7 (Kb6 attacks), b8 (Qc7 attacks b8)... actually Qc7 attacks b8 diag? No, c7 to b8 is diagonal yes.
    // a7: Kb6 attacks. b7: Kb6 and Qc7 attack.
    // So 0 legal moves and not in check (Qc7 doesn't attack a8 directly, Kb6 doesn't attack a8)
    // Qc7: can it see a8? c7 to a8 is not a straight line (different file and rank, not diagonal)
    // Actually... is black king in check? Q on c7, king on a8. Not same rank, not same file, not same diagonal. Not in check.
    // Kb6: doesn't attack a8 (distance 2). So it's stalemate!
    assert_eq!(moves.len(), 0);
    assert!(!in_check(&board));
}

#[test]
fn test_uci_to_move() {
    let board = Board::new();
    let m = uci_to_move(&board, "e2e4").unwrap();
    assert_eq!(move_to_uci(m), "e2e4");
}

#[test]
fn test_make_move_basic() {
    let board = Board::new();
    let m = uci_to_move(&board, "e2e4").unwrap();
    let new_board = make_move(&board, m);
    assert_eq!(new_board.side, Color::Black);
    assert!(new_board.piece_at(sq(4, 3)).is_some()); // e4
    assert!(new_board.piece_at(sq(4, 1)).is_none()); // e2 now empty
}

#[test]
fn test_zobrist_consistency() {
    let board = Board::new();
    let m1 = uci_to_move(&board, "e2e4").unwrap();
    let b1 = make_move(&board, m1);
    let m2 = uci_to_move(&b1, "e7e5").unwrap();
    let b2 = make_move(&b1, m2);

    // Same position reached differently should have same zobrist
    let board2 = Board::from_fen(&b2.to_fen());
    assert_eq!(b2.zobrist, board2.zobrist);
}
