---
name: chess-player
description: Play Chess as an AI opponent. Select the best move from a list of legal moves given a FEN position. Use when processing chess move requests in board game sessions.
---

# Chess Player

Pick the best move from the legal moves list. Reply with ONLY the SAN notation.

## Piece Values

Q=9, R=5, B=3, N=3, P=1.

## Strategy Priority

1. Checkmate — always play it
2. Escape check — mandatory
3. Capture hanging/higher-value pieces
4. Develop knights and bishops (before move 10)
5. Control center (e4, d4, e5, d5)
6. Castle early for King safety
7. Connect rooks — clear back rank
8. Create threats — forks, pins, discovered attacks
9. Don't hang pieces
10. NEVER sacrifice material just for check — only check if it leads to checkmate, wins material, or gains a decisive positional advantage
11. Before playing a check, count: will you LOSE more material than you gain? If yes, don't check

## Opening Principles

- Control center with e4/d4
- Knights before bishops
- Castle before move 10
- Don't repeat moves without reason
- Don't bring queen out early

For common opening lines, see `references/openings.md`.

## Output

Reply with ONLY one SAN move, nothing else:
```
Nf3
```
