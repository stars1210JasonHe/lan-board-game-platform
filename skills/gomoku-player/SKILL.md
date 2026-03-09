---
name: gomoku-player
description: Play Gomoku (Five in a Row) as an AI opponent using local minimax algorithm. No LLM needed — uses depth-5 iterative deepening with alpha-beta pruning and 3-second time limit.
---

# Gomoku Player

Gomoku uses a local minimax algorithm, not LLM. No API calls needed.

## Algorithm

- Minimax with alpha-beta pruning
- Iterative deepening: depth 3 → 4 → 5
- 3-second time limit per move
- Candidate moves: only cells within 2 squares of existing stones
- Move ordering by heuristic score for better pruning

## Board

15×15 grid. Player 1 (Black) goes first. First to 5 in a row wins.
