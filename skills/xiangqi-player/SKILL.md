---
name: xiangqi-player
description: Play Xiangqi (Chinese Chess) as an AI opponent. Select the best move from a list of legal moves given a board position. Use when processing xiangqi move requests in board game sessions.
---

# Xiangqi Player

Pick the best move from the legal moves list. Reply with ONLY the coordinate.

## Coordinate System

Board: 9 columns (a-i, left→right) × 10 rows (0-9, bottom→top).
Move format: `{from}{to}`, e.g. `b0c2` = column b row 0 → column c row 2.

```
Row 9: a9 b9 c9 d9 e9 f9 g9 h9 i9   ← Black back rank
  ─────────── River ───────────
Row 0: a0 b0 c0 d0 e0 f0 g0 h0 i0   ← Red back rank
```

Red: rows 0-2 (bottom). Black: rows 7-9 (top).
Palace: columns d-f, rows 0-2 (Red) / 7-9 (Black).

## Pieces

| Letter | Name | Value | Movement |
|--------|------|-------|----------|
| R/r | 車 Rook | 9 | Any distance orthogonal |
| C/c | 炮 Cannon | 4.5 | Moves like Rook; captures by jumping over 1 piece |
| N/n | 馬 Knight | 4 | L-shape (1+2), blocked if leg occupied |
| B/b | 象 Elephant | 2 | 2 steps diagonal, cannot cross river, blocked if eye occupied |
| A/a | 仕 Advisor | 2 | 1 step diagonal, stays in palace |
| K/k | 帥將 King | — | 1 step orthogonal, stays in palace |
| P/p | 兵卒 Pawn | 1→2 | Forward 1; after crossing river also sideways 1 |

Uppercase = Red, lowercase = Black.

## FEN

`/` separates rows from row 9 (top) to row 0 (bottom). Numbers = empty squares.
`RNBAKABNR/9/1C5C1/P1P1P1P1P/9/9/p1p1p1p1p/1c5c1/9/rnbakabnr r` = start, Red to move.

## Strategy Priority

1. Checkmate — always play it
2. Escape check — mandatory
3. Capture high-value pieces (especially 車)
4. Develop 馬 and 炮 to active squares
5. Control center file (column e)
6. Keep 仕 and 象 formation intact for King safety
7. Push pawns across river (they gain sideways movement)
8. Connect 車s on open files
9. NEVER sacrifice material just for check — only check if it leads to checkmate, wins material, or gains a decisive advantage
10. Before playing a check, count: will you LOSE more material than you gain? If yes, don't check
11. NEVER repeat the same move — if you played a move recently, pick a different one

For opening lines, see `references/openings.md`.

## Output

Reply with ONLY the coordinate, nothing else:
```
b0c2
```
