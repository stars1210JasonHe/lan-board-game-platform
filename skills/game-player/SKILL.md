---
name: game-player
description: Play board games (Chess, Xiangqi/Chinese Chess, Gomoku) as an AI opponent. Triggered when the LLM needs to select a move in a board game given a position and legal moves list. Handles move selection, strategy, and game-specific coordinate formats. Use when processing /api/move requests for chess, xiangqi, or gomoku game sessions.
---

# Game Player

AI move selection for board games. Given a board position and legal moves list, pick the strongest move.

## Supported Games

| Game | Format | Strategy Source |
|------|--------|----------------|
| Chess | SAN (e.g. `Nf3`) | LLM with FEN + legal moves |
| Xiangqi | Coordinate (e.g. `b0c2`) | LLM with FEN + legal moves → see `references/rules-xiangqi.md` |
| Gomoku | Local minimax (depth 5) | Algorithm, no LLM needed |

## Move Selection Protocol

1. Receive: board state (FEN) + legal moves list + move history
2. Analyze position using piece values and strategy priorities
3. Pick ONE move from the legal moves list
4. Reply with ONLY the move notation — no explanation

If move is rejected: receive error feedback, pick a DIFFERENT move from legal list.
Max 3 retries. After 3 failures: random legal move fallback.

## Chess

Piece values: Q=9 R=5 B=3 N=3 P=1.
Strategy: checkmate > escape check > capture > develop pieces > control center > castle early > connect rooks.
Output: one SAN move (e.g. `Nf3`, `O-O`, `exd5`).

## Xiangqi

Full rules, coordinate system, piece movements, and strategy in `references/rules-xiangqi.md`. Read it when handling xiangqi moves.

Key points:
- Coordinates: columns a-i (left→right), rows 0-9 (bottom→top)
- Red at rows 0-2, Black at rows 7-9
- Piece values: R=9 C=4.5 N=4 B=2 A=2 P=1(→2 after river)
- Output: one coordinate (e.g. `b0c2`)

## Gomoku

Handled by local minimax algorithm (depth 5, iterative deepening, 3s time limit). No LLM call needed.
