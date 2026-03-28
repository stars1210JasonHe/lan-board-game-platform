use std::time::{Duration, Instant};

use crate::chess;
use crate::xiangqi;

const MAX_DEPTH: i32 = 64;
const TT_SIZE: usize = 1 << 20; // ~1M entries

#[derive(Clone, Copy, PartialEq, Eq)]
enum TTFlag {
    Exact,
    LowerBound, // beta cutoff
    UpperBound, // alpha not improved
}

#[derive(Clone, Copy)]
struct TTEntry {
    key: u64,
    depth: i32,
    score: i32,
    flag: TTFlag,
    best_move_idx: u16, // index into move list (or 0xFFFF for none)
}

struct TranspositionTable {
    entries: Vec<Option<TTEntry>>,
}

impl TranspositionTable {
    fn new() -> Self {
        Self { entries: vec![None; TT_SIZE] }
    }

    fn probe(&self, key: u64) -> Option<&TTEntry> {
        let idx = (key as usize) % TT_SIZE;
        self.entries[idx].as_ref().filter(|e| e.key == key)
    }

    fn store(&mut self, key: u64, depth: i32, score: i32, flag: TTFlag, best_move_idx: u16) {
        let idx = (key as usize) % TT_SIZE;
        // Replace if deeper or same position
        if let Some(existing) = &self.entries[idx] {
            if existing.key == key || depth >= existing.depth {
                self.entries[idx] = Some(TTEntry { key, depth, score, flag, best_move_idx });
            }
        } else {
            self.entries[idx] = Some(TTEntry { key, depth, score, flag, best_move_idx });
        }
    }
}

// Killer moves table
struct KillerMoves {
    killers: [[u32; 2]; MAX_DEPTH as usize], // store move as u32 for comparison
}

impl KillerMoves {
    fn new() -> Self {
        Self { killers: [[0; 2]; MAX_DEPTH as usize] }
    }

    fn add(&mut self, ply: usize, mv: u32) {
        if ply < MAX_DEPTH as usize {
            if self.killers[ply][0] != mv {
                self.killers[ply][1] = self.killers[ply][0];
                self.killers[ply][0] = mv;
            }
        }
    }

    fn is_killer(&self, ply: usize, mv: u32) -> bool {
        ply < MAX_DEPTH as usize && (self.killers[ply][0] == mv || self.killers[ply][1] == mv)
    }
}

// History heuristic table
struct HistoryTable {
    scores: [[i32; 64]; 64], // [from][to] for chess (squares fit in 64)
}

impl HistoryTable {
    fn new() -> Self {
        Self { scores: [[0; 64]; 64] }
    }

    fn add(&mut self, from: usize, to: usize, depth: i32) {
        if from < 64 && to < 64 {
            self.scores[from][to] += depth * depth;
        }
    }

    fn get(&self, from: usize, to: usize) -> i32 {
        if from < 64 && to < 64 { self.scores[from][to] } else { 0 }
    }
}

// ===================== CHESS SEARCH =====================

struct ChessSearchState {
    tt: TranspositionTable,
    killers: KillerMoves,
    history: HistoryTable,
    nodes: u64,
    deadline: Instant,
    stopped: bool,
}

impl ChessSearchState {
    fn check_time(&mut self) {
        self.nodes += 1;
        if self.nodes % 4096 == 0 && Instant::now() >= self.deadline {
            self.stopped = true;
        }
    }
}

fn chess_quiescence(board: &chess::board::Board, mut alpha: i32, beta: i32, state: &mut ChessSearchState) -> i32 {
    if state.stopped { return 0; }
    state.check_time();

    let stand_pat = chess::eval::evaluate(board);
    if stand_pat >= beta { return beta; }
    if stand_pat > alpha { alpha = stand_pat; }

    let captures = chess::moves::generate_captures(board);
    for m in captures {
        let new_board = chess::moves::make_move(board, m);
        let score = -chess_quiescence(&new_board, -beta, -alpha, state);
        if state.stopped { return 0; }
        if score >= beta { return beta; }
        if score > alpha { alpha = score; }
    }
    alpha
}

fn chess_alpha_beta(
    board: &chess::board::Board,
    depth: i32,
    mut alpha: i32,
    beta: i32,
    ply: usize,
    state: &mut ChessSearchState,
) -> i32 {
    if state.stopped { return 0; }
    state.check_time();

    if depth <= 0 {
        return chess_quiescence(board, alpha, beta, state);
    }

    // Check terminal
    if let Some(score) = chess::eval::is_terminal(board) {
        return if score == -chess::eval::MATE_SCORE {
            score + ply as i32 // prefer shorter mates
        } else {
            score
        };
    }

    // TT probe
    let tt_move_idx;
    if let Some(entry) = state.tt.probe(board.zobrist) {
        tt_move_idx = entry.best_move_idx;
        if entry.depth >= depth {
            match entry.flag {
                TTFlag::Exact => return entry.score,
                TTFlag::LowerBound => { if entry.score >= beta { return entry.score; } }
                TTFlag::UpperBound => { if entry.score <= alpha { return entry.score; } }
            }
        }
    } else {
        tt_move_idx = 0xFFFF;
    }

    let mut moves = chess::moves::generate_legal_moves(board);
    if moves.is_empty() {
        return if chess::moves::in_check(board) {
            -chess::eval::MATE_SCORE + ply as i32
        } else {
            chess::eval::DRAW_SCORE
        };
    }

    // Move ordering
    order_chess_moves(&mut moves, board, tt_move_idx, ply, state);

    let mut best_score = -chess::eval::MATE_SCORE - 1;
    let mut best_move_idx: u16 = 0;
    let original_alpha = alpha;

    for (i, &m) in moves.iter().enumerate() {
        let new_board = chess::moves::make_move(board, m);
        let score = -chess_alpha_beta(&new_board, depth - 1, -beta, -alpha, ply + 1, state);
        if state.stopped { return 0; }

        if score > best_score {
            best_score = score;
            best_move_idx = i as u16;
        }
        if score > alpha { alpha = score; }
        if alpha >= beta {
            // Killer move (non-capture)
            if board.piece_at(chess::moves::move_to(m)).is_none() {
                state.killers.add(ply, m as u32);
                state.history.add(
                    chess::moves::move_from(m) as usize,
                    chess::moves::move_to(m) as usize,
                    depth,
                );
            }
            break;
        }
    }

    // Store in TT
    let flag = if best_score <= original_alpha {
        TTFlag::UpperBound
    } else if best_score >= beta {
        TTFlag::LowerBound
    } else {
        TTFlag::Exact
    };
    state.tt.store(board.zobrist, depth, best_score, flag, best_move_idx);

    best_score
}

fn order_chess_moves(
    moves: &mut Vec<chess::moves::Move>,
    board: &chess::board::Board,
    tt_move_idx: u16,
    ply: usize,
    state: &ChessSearchState,
) {
    let mut scored: Vec<(i32, usize)> = moves.iter().enumerate().map(|(i, &m)| {
        let mut score = 0i32;

        // TT move gets highest priority
        if tt_move_idx != 0xFFFF && i == tt_move_idx as usize {
            score += 10_000_000;
        }

        let to = chess::moves::move_to(m);
        let flags = chess::moves::move_flags(m);

        // Captures: MVV-LVA
        if let Some((_, captured)) = board.piece_at(to) {
            let from = chess::moves::move_from(m);
            let attacker_val = board.piece_at(from).map(|(_, p)| chess::eval::piece_value(p)).unwrap_or(0);
            score += 1_000_000 + chess::eval::piece_value(captured) * 10 - attacker_val;
        }

        // Promotions
        if flags == chess::moves::FLAG_PROMOTION {
            score += 900_000;
        }

        // En passant
        if flags == chess::moves::FLAG_EP {
            score += 1_000_100;
        }

        // Killer moves
        if state.killers.is_killer(ply, m as u32) {
            score += 500_000;
        }

        // History heuristic
        let from = chess::moves::move_from(m) as usize;
        let to_sq = chess::moves::move_to(m) as usize;
        score += state.history.get(from, to_sq);

        (score, i)
    }).collect();

    scored.sort_unstable_by(|a, b| b.0.cmp(&a.0));
    let ordered: Vec<chess::moves::Move> = scored.iter().map(|&(_, i)| moves[i]).collect();
    *moves = ordered;
}

pub fn iterative_deepening_chess(board: &chess::board::Board, time_limit: Duration) -> Option<chess::moves::Move> {
    let deadline = Instant::now() + time_limit;
    let mut state = ChessSearchState {
        tt: TranspositionTable::new(),
        killers: KillerMoves::new(),
        history: HistoryTable::new(),
        nodes: 0,
        deadline,
        stopped: false,
    };

    let mut best_move: Option<chess::moves::Move> = None;
    let moves = chess::moves::generate_legal_moves(board);
    if moves.is_empty() { return None; }
    if moves.len() == 1 { return Some(moves[0]); }

    best_move = Some(moves[0]);

    for depth in 1..=MAX_DEPTH {
        state.stopped = false;
        let mut best_score = -chess::eval::MATE_SCORE - 1;
        let mut best_at_depth: Option<chess::moves::Move> = None;
        let mut ordered_moves = moves.clone();

        order_chess_moves(&mut ordered_moves, board, 0xFFFF, 0, &state);

        // Put previous best move first
        if let Some(prev_best) = best_move {
            if let Some(pos) = ordered_moves.iter().position(|&m| m == prev_best) {
                ordered_moves.swap(0, pos);
            }
        }

        for &m in &ordered_moves {
            let new_board = chess::moves::make_move(board, m);
            let score = -chess_alpha_beta(&new_board, depth - 1, -chess::eval::MATE_SCORE, -best_score.max(-chess::eval::MATE_SCORE), 1, &mut state);

            if state.stopped { break; }

            if score > best_score {
                best_score = score;
                best_at_depth = Some(m);
            }
        }

        if !state.stopped {
            best_move = best_at_depth.or(best_move);
            eprintln!("info depth {} score {} nodes {} pv {}",
                depth, best_score, state.nodes,
                best_move.map(chess::moves::move_to_uci).unwrap_or_default());
        } else if best_at_depth.is_some() {
            // Partial results from this depth are unreliable, keep previous
        }

        if state.stopped || best_score.unsigned_abs() > chess::eval::MATE_SCORE as u32 - 100 {
            break;
        }
    }

    best_move
}

// ===================== XIANGQI SEARCH =====================

struct XiangqiSearchState {
    tt: TranspositionTable,
    killers: KillerMoves,
    history: [[i32; 90]; 90], // 10*9 = 90 squares
    nodes: u64,
    deadline: Instant,
    stopped: bool,
}

impl XiangqiSearchState {
    fn check_time(&mut self) {
        self.nodes += 1;
        if self.nodes % 4096 == 0 && Instant::now() >= self.deadline {
            self.stopped = true;
        }
    }
}

fn xq_sq(r: u8, c: u8) -> usize {
    r as usize * 9 + c as usize
}

fn xq_move_key(m: xiangqi::moves::Move) -> u32 {
    ((m.0 as u32) << 24) | ((m.1 as u32) << 16) | ((m.2 as u32) << 8) | (m.3 as u32)
}

fn xiangqi_quiescence(board: &xiangqi::board::Board, mut alpha: i32, beta: i32, state: &mut XiangqiSearchState) -> i32 {
    if state.stopped { return 0; }
    state.check_time();

    let stand_pat = xiangqi::eval::evaluate(board);
    if stand_pat >= beta { return beta; }
    if stand_pat > alpha { alpha = stand_pat; }

    let captures = xiangqi::moves::generate_captures(board);
    for m in captures {
        let new_board = xiangqi::moves::make_move(board, m);
        let score = -xiangqi_quiescence(&new_board, -beta, -alpha, state);
        if state.stopped { return 0; }
        if score >= beta { return beta; }
        if score > alpha { alpha = score; }
    }
    alpha
}

fn xiangqi_alpha_beta(
    board: &xiangqi::board::Board,
    depth: i32,
    mut alpha: i32,
    beta: i32,
    ply: usize,
    state: &mut XiangqiSearchState,
) -> i32 {
    if state.stopped { return 0; }
    state.check_time();

    if depth <= 0 {
        return xiangqi_quiescence(board, alpha, beta, state);
    }

    if let Some(score) = xiangqi::eval::is_terminal(board) {
        return if score == -xiangqi::eval::MATE_SCORE {
            score + ply as i32
        } else {
            score
        };
    }

    // TT probe
    let tt_move_idx;
    if let Some(entry) = state.tt.probe(board.zobrist) {
        tt_move_idx = entry.best_move_idx;
        if entry.depth >= depth {
            match entry.flag {
                TTFlag::Exact => return entry.score,
                TTFlag::LowerBound => { if entry.score >= beta { return entry.score; } }
                TTFlag::UpperBound => { if entry.score <= alpha { return entry.score; } }
            }
        }
    } else {
        tt_move_idx = 0xFFFF;
    }

    let mut moves = xiangqi::moves::generate_legal_moves(board);
    if moves.is_empty() {
        return if xiangqi::moves::is_in_check(board, board.side) {
            -xiangqi::eval::MATE_SCORE + ply as i32
        } else {
            xiangqi::eval::DRAW_SCORE
        };
    }

    order_xiangqi_moves(&mut moves, board, tt_move_idx, ply, state);

    let mut best_score = -xiangqi::eval::MATE_SCORE - 1;
    let mut best_move_idx: u16 = 0;
    let original_alpha = alpha;

    for (i, &m) in moves.iter().enumerate() {
        let new_board = xiangqi::moves::make_move(board, m);
        let score = -xiangqi_alpha_beta(&new_board, depth - 1, -beta, -alpha, ply + 1, state);
        if state.stopped { return 0; }

        if score > best_score {
            best_score = score;
            best_move_idx = i as u16;
        }
        if score > alpha { alpha = score; }
        if alpha >= beta {
            if board.grid[m.2 as usize][m.3 as usize].is_none() {
                state.killers.add(ply, xq_move_key(m));
                let from = xq_sq(m.0, m.1);
                let to = xq_sq(m.2, m.3);
                state.history[from][to] += depth * depth;
            }
            break;
        }
    }

    let flag = if best_score <= original_alpha {
        TTFlag::UpperBound
    } else if best_score >= beta {
        TTFlag::LowerBound
    } else {
        TTFlag::Exact
    };
    state.tt.store(board.zobrist, depth, best_score, flag, best_move_idx);

    best_score
}

fn order_xiangqi_moves(
    moves: &mut Vec<xiangqi::moves::Move>,
    board: &xiangqi::board::Board,
    tt_move_idx: u16,
    ply: usize,
    state: &XiangqiSearchState,
) {
    let mut scored: Vec<(i32, usize)> = moves.iter().enumerate().map(|(i, &m)| {
        let mut score = 0i32;

        if tt_move_idx != 0xFFFF && i == tt_move_idx as usize {
            score += 10_000_000;
        }

        // Captures: MVV-LVA
        if let Some(target) = board.grid[m.2 as usize][m.3 as usize] {
            let attacker = board.grid[m.0 as usize][m.1 as usize].unwrap();
            score += 1_000_000 + xiangqi::eval::piece_value(target.piece) * 10
                - xiangqi::eval::piece_value(attacker.piece);
        }

        // Killer
        if state.killers.is_killer(ply, xq_move_key(m)) {
            score += 500_000;
        }

        // History
        let from = xq_sq(m.0, m.1);
        let to = xq_sq(m.2, m.3);
        if from < 90 && to < 90 {
            score += state.history[from][to];
        }

        (score, i)
    }).collect();

    scored.sort_unstable_by(|a, b| b.0.cmp(&a.0));
    let ordered: Vec<xiangqi::moves::Move> = scored.iter().map(|&(_, i)| moves[i]).collect();
    *moves = ordered;
}

pub fn iterative_deepening_xiangqi(board: &xiangqi::board::Board, time_limit: Duration) -> Option<xiangqi::moves::Move> {
    let deadline = Instant::now() + time_limit;
    let mut state = XiangqiSearchState {
        tt: TranspositionTable::new(),
        killers: KillerMoves::new(),
        history: [[0; 90]; 90],
        nodes: 0,
        deadline,
        stopped: false,
    };

    let mut best_move: Option<xiangqi::moves::Move> = None;
    let moves = xiangqi::moves::generate_legal_moves(board);
    if moves.is_empty() { return None; }
    if moves.len() == 1 { return Some(moves[0]); }

    best_move = Some(moves[0]);

    for depth in 1..=MAX_DEPTH {
        state.stopped = false;
        let mut best_score = -xiangqi::eval::MATE_SCORE - 1;
        let mut best_at_depth: Option<xiangqi::moves::Move> = None;
        let mut ordered_moves = moves.clone();

        order_xiangqi_moves(&mut ordered_moves, board, 0xFFFF, 0, &state);

        if let Some(prev_best) = best_move {
            if let Some(pos) = ordered_moves.iter().position(|&m| m == prev_best) {
                ordered_moves.swap(0, pos);
            }
        }

        for &m in &ordered_moves {
            let new_board = xiangqi::moves::make_move(board, m);
            let score = -xiangqi_alpha_beta(&new_board, depth - 1, -xiangqi::eval::MATE_SCORE, -best_score.max(-xiangqi::eval::MATE_SCORE), 1, &mut state);

            if state.stopped { break; }

            if score > best_score {
                best_score = score;
                best_at_depth = Some(m);
            }
        }

        if !state.stopped {
            best_move = best_at_depth.or(best_move);
            eprintln!("info depth {} score {} nodes {} pv {}",
                depth, best_score, state.nodes,
                best_move.map(xiangqi::moves::move_to_coord).unwrap_or_default());
        }

        if state.stopped || best_score.unsigned_abs() > xiangqi::eval::MATE_SCORE as u32 - 100 {
            break;
        }
    }

    best_move
}
