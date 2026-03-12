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
3. Capture hanging/higher-value pieces (trade up: give B/N for R/Q)
4. NEVER sacrifice material just for check — only check if it leads to checkmate, wins material, or gains a decisive advantage
5. Before playing a check, count: will you LOSE more material than you gain? If yes, don't check
6. NEVER repeat the same move — pick a different one each time
7. Don't hang pieces — before every move, ask: can opponent capture this piece for free?

## Opening (moves 1-10)

- Control center with e4/d4
- Knights before bishops
- Castle before move 10
- Don't bring queen out early
- Don't move the same piece twice without reason

## Middlegame (moves 10-30)

- Trade pieces when ahead in material; avoid trades when behind
- Create threats: forks, pins, skewers, discovered attacks
- Connect rooks — clear back rank
- Control open files with rooks
- Avoid pawn weaknesses (doubled, isolated, backward)

## Endgame (moves 30+)

- Activate the King — move it to center
- Push passed pawns toward promotion
- Rook belongs behind passed pawns (yours or opponent's)
- K+Q vs K: drive King to edge, then checkmate
- K+R vs K: drive King to edge with opposition

## Output

Reply with ONLY one SAN move, nothing else:
```
Nf3
```
