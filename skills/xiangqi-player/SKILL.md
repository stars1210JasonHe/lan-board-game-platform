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
3. Capture high-value pieces (trade up: give 馬/炮 for 車)
4. NEVER sacrifice material just for check — only check if it leads to checkmate, wins material, or gains a decisive advantage
5. Before playing a check, count: will you LOSE more material than you gain? If yes, don't check
6. NEVER repeat the same move — pick a different one each time
7. Don't hang pieces — before every move, ask: can opponent capture this piece for free?
8. Remember: Kings (帥/將) cannot face each other on the same file with nothing between them

## Opening

- 中炮 (center cannon): C on column e attacks opponent center
- 飞相/起馬: develop elephant or knight first for defense
- Develop 車 to open files early — 車 is the strongest piece
- Don't move the same piece twice without reason

## Middlegame

- 車 controls open files; double 車 on same file is powerful
- 炮 needs a platform piece to capture — position pieces as cannon mounts
- 馬 is strong in close combat but weak from far; bring 馬 to center
- Trade pieces when ahead in material; avoid trades when behind
- Attack the palace: target 仕/象 to expose the King
- Common tactics: 重炮 (double cannon on same file), 馬後炮 (knight + cannon combo), 闷宫 (smothered mate)

## Endgame

- 單車必勝 (single 車 beats lone King with proper technique)
- 車 + 兵 vs 仕象全 is usually winning
- 炮需要架 — cannon alone is weak in endgame without platform pieces
- Push pawns across river — they gain sideways movement and become more dangerous
- King should stay protected; only expose for final checkmate sequence

## Before You Move — Checklist

Think through these BEFORE picking a move:
1. What is my opponent threatening? (captures, checks, 將軍)
2. Which of MY pieces are under attack right now?
3. Can I capture a higher-value piece?
4. Does my move leave any piece undefended?
5. After my move, can opponent capture anything for free?
6. Are the Kings (帥/將) facing each other on same file? (illegal!)

## Output

Reply with ONLY the coordinate, nothing else:
```
b0c2
```
