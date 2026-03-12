# Xiangqi Attack Detection & FEN Support via cchess

## Overview

Add attacked-pieces analysis for xiangqi (like we already have for chess via `python-chess`),
using the installed `cchess` library (walker8088, v1.25.5).

Also pass the xiangqi FEN into the LLM prompt for better positional understanding.

---

## 1. Installed Library: `cchess` (walker8088 v1.25.5)

**Important:** This is the walker8088 package from PyPI, NOT the windshadow233
`python-chinese-chess` from GitHub. They share the `cchess` import name but have
completely different APIs.

### Key API Summary

| Operation | Method |
|-----------|--------|
| Create board from FEN | `cchess.ChessBoard(fen_str)` |
| Get all pieces | `board.get_pieces(color)` where `color` = `cchess.RED` or `cchess.BLACK` |
| Get piece at square | `board.get_piece((x, y))` returns `Piece` or `None` |
| Piece species | `piece.species` (lowercase: `'k'`, `'r'`, `'n'`, etc.) |
| Piece color | `piece.color` (`cchess.RED=1`, `cchess.BLACK=2`) |
| Piece FEN char | `piece.fench` (`'R'` = red rook, `'n'` = black knight) |
| Check movement | `piece.is_valid_move((x, y))` — movement rules only |
| Board-level validity | `board.is_valid_move(from, to)` — includes turn + friendly-fire check |
| Pseudo-legal moves | `list(board.create_moves())` — current player only |
| Leaves king in check? | `board.is_checked_move(from, to)` — True if illegal (self-check) |
| Coordinate to ICCS | `cchess.pos2iccs((fx,fy), (tx,ty))` → `'h2h4'` |
| ICCS to coordinate | `cchess.iccs2pos('h2h4')` → `((7,2), (7,4))` |
| Piece name in Chinese | `cchess.fench_to_text('R')` → `'车'` |

### Coordinate System

- `(x, y)` where `x` = column (0-8, left to right = a-i), `y` = row (0-9, bottom to top)
- Row 0 = Red's back rank, Row 9 = Black's back rank
- ICCS notation: `a0` through `i9` (column letter + row number)

---

## 2. Critical Finding: `piece.is_valid_move()` Does NOT Filter Friendly Pieces

`piece.is_valid_move(target)` only checks piece movement rules (trajectories, blocking
for knight leg / bishop eye / cannon mount, palace boundaries, river crossing). It does
**NOT** check whether the target square contains a friendly piece.

**Tested and confirmed:**
```python
board = cchess.ChessBoard(cchess.FULL_INIT_FEN)
rook = board.get_piece((0, 0))  # Red Rook at a0
rook.is_valid_move((1, 0))  # True! (Red Knight is there — own piece)
rook.is_valid_move((0, 3))  # True! (Red Pawn is there — own piece)
```

In contrast, `board.is_valid_move(from, to)` checks both friendly-fire AND whose turn
it is, making it unsuitable for off-turn attack detection.

**Solution:** For attack detection, use `piece.is_valid_move()` + manual friendly-piece
filter:

```python
def is_attacking(piece, target_sq, board):
    """Check if piece can attack target_sq (must be enemy or empty)."""
    if not piece.is_valid_move(target_sq):
        return False
    target_piece = board.get_piece(target_sq)
    if target_piece and target_piece.color == piece.color:
        return False
    return True
```

---

## 3. Implementation Plan

### 3a. New function: `xiangqi_attacked_pieces_info(fen)`

Add to `ask_move.py`, mirroring `chess_attacked_pieces_info()`.

```python
def xiangqi_attacked_pieces_info(fen: str) -> str:
    """Analyze which pieces are under attack for xiangqi using cchess."""
    import cchess

    # cchess expects FEN without the trailing " - - 0 1" suffix,
    # but with the side-to-move field: "rnbakabnr/... w"
    # Strip the extra fields if present (our xiangqi_board_to_fen adds them)
    fen_parts = fen.split()
    short_fen = f"{fen_parts[0]} {fen_parts[1]}"  # board + side only

    board = cchess.ChessBoard(short_fen)

    # Determine side to move
    side = cchess.RED if fen_parts[1] == 'w' else cchess.BLACK
    opp = cchess.BLACK if side == cchess.RED else cchess.RED

    PIECE_NAMES = {
        'k': 'King', 'a': 'Advisor', 'b': 'Elephant',
        'n': 'Horse', 'r': 'Chariot', 'c': 'Cannon', 'p': 'Soldier',
    }

    def piece_name(piece):
        return PIECE_NAMES.get(piece.species, 'piece')

    def square_name(x, y):
        return chr(ord('a') + x) + str(y)

    def get_attackers(attacking_color, target_sq):
        """Get all pieces of attacking_color that can reach target_sq."""
        result = []
        for p in board.get_pieces(attacking_color):
            if p.is_valid_move(target_sq):
                target_p = board.get_piece(target_sq)
                if target_p and target_p.color == p.color:
                    continue  # Can't capture own piece
                result.append(p)
        return result

    # Our pieces under attack by opponent
    our_attacked = []
    for p in board.get_pieces(side):
        sq = (p.x, p.y)
        attackers = get_attackers(opp, sq)
        if attackers:
            att_str = ", ".join(
                f"{piece_name(a).lower()}" for a in attackers
            )
            our_attacked.append(f"{piece_name(p)} on {square_name(p.x, p.y)} (by {att_str})")

    # Opponent pieces we can capture
    opp_capturable = []
    for p in board.get_pieces(opp):
        sq = (p.x, p.y)
        attackers = get_attackers(side, sq)
        if attackers:
            defended = len(get_attackers(opp, sq)) > 0
            defense_str = "defended" if defended else "undefended"
            opp_capturable.append(f"{piece_name(p)} on {square_name(p.x, p.y)} ({defense_str})")

    lines = []
    if our_attacked:
        lines.append(f"Your pieces under attack: {', '.join(our_attacked)}")
    if opp_capturable:
        lines.append(f"Opponent pieces you can capture: {', '.join(opp_capturable)}")
    return "\n".join(lines)
```

### 3b. Generate xiangqi FEN and pass it to `ask_move.py`

In `euler_play.py`, the FEN is already computed via `xiangqi_board_to_fen()` but only
used for Fairy-Stockfish. We need to also pass it to `ask_move.py` when using LLM mode.

**Changes in `euler_play.py`** (around line 707):

Currently:
```python
if gt == "chess" and gs.get("fen"):
    cmd += ["--fen", gs["fen"]]
```

Add xiangqi FEN generation and pass it:
```python
if gt == "chess" and gs.get("fen"):
    cmd += ["--fen", gs["fen"]]
elif gt == "xiangqi":
    xiangqi_fen = xiangqi_board_to_fen(board_rows, current_player)
    cmd += ["--fen", xiangqi_fen]
```

Where `board_rows` and `current_player` need to be derived from the game state `gs`.
The board data should already be available from `gs["board"]` (the 10-row array) and
`gs["currentPlayer"]` (the current player color string).

### 3c. Wire up in `build_user_prompt()` in `ask_move.py`

Currently, attack info is only computed for chess. Add xiangqi support:

```python
attack_info = ""
if game == "chess" and fen:
    try:
        attack_info = chess_attacked_pieces_info(fen)
    except Exception as e:
        print(f"[ask_move] attack info error: {e}", file=sys.stderr)
elif game == "xiangqi" and fen:
    try:
        attack_info = xiangqi_attacked_pieces_info(fen)
    except Exception as e:
        print(f"[ask_move] xiangqi attack info error: {e}", file=sys.stderr)
```

Also add FEN to the xiangqi prompt section:
```python
if game == "xiangqi":
    # ... existing board + legal moves ...
    extra = ""
    if fen:
        extra += f"\nFEN: {fen}"
    if attack_info:
        extra += f"\n{attack_info}"
    # ... rest of prompt ...
```

---

## 4. FEN Format Considerations

Our `xiangqi_board_to_fen()` produces: `rnbakabnr/9/1c5c1/... w - - 0 1`

The `cchess.ChessBoard()` constructor expects just: `rnbakabnr/9/1c5c1/... w`

**Solution:** Strip trailing fields before passing to cchess:
```python
fen_parts = fen.split()
short_fen = f"{fen_parts[0]} {fen_parts[1]}"
```

This is safe because our FEN always has the board and side-to-move as the first two fields.

---

## 5. Limitations and Issues

### 5.1 No built-in `is_attacked_by()` / `attackers()` methods
Unlike `python-chess`, the walker8088 `cchess` has no direct attack detection API.
We must iterate all pieces and call `piece.is_valid_move()` + filter friendly pieces.
This is O(n * m) where n = attacking pieces and m = target squares, but with only
16 pieces per side on a 90-square board, performance is fine.

### 5.2 `piece.is_valid_move()` allows "capturing" own pieces
Must manually filter: check `board.get_piece(target).color != attacker.color`.
Forgetting this filter would produce false attack reports.

### 5.3 No pin/x-ray detection
`piece.is_valid_move()` does not consider whether moving the piece would expose its
own king to check (pins). So a pinned piece is still reported as an attacker even if
it can't legally move. This is acceptable for tactical awareness — the AI should know
the piece *would* attack if not pinned.

### 5.4 `board.is_valid_move()` checks turn
Cannot use `board.is_valid_move()` for off-turn attack detection (e.g., checking what
the opponent threatens). Must use per-piece `is_valid_move()` instead.

### 5.5 No `board.push()` / `board.pop()` — moves mutate the board
`board.move()` permanently mutates the board (no undo stack). If we ever need to
analyze positions after hypothetical moves, we'd need `board.copy()` first. For
current-position attack detection, this is not an issue.

### 5.6 Alternative library (windshadow233) exists but conflicts
The windshadow233 `python-chinese-chess` has a python-chess-like API with built-in
`is_attacked_by()`, `attackers()`, `legal_moves`, and `push()`/`pop()`. However:
- Same import name `cchess` — would conflict with installed walker8088 package
- Not on PyPI (must install from GitHub)
- Would require uninstalling current `cchess` first
- Current walker8088 library is sufficient for our needs

---

## 6. Testing Approach

Before integrating, test the attack detection function standalone:

```python
import cchess

# Starting position — no attacks expected (pieces too far apart)
fen = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"
result = xiangqi_attacked_pieces_info(fen)
assert result == "", f"Expected no attacks at start, got: {result}"

# Tactical position — cannon threatens through a screen piece
fen = "r1bakab1r/9/1cn2c2n/p1p1C1p1p/4P4/9/P1P3P1P/2N1C1N2/9/R1BAKAB1R w"
result = xiangqi_attacked_pieces_info(fen)
assert "Soldier" in result or "capture" in result.lower()
print(result)
```

---

## 7. Summary of Changes

| File | Change |
|------|--------|
| `apps/agent-player/ask_move.py` | Add `xiangqi_attacked_pieces_info(fen)` function |
| `apps/agent-player/ask_move.py` | Wire xiangqi attack info into `build_user_prompt()` |
| `apps/agent-player/ask_move.py` | Add FEN line to xiangqi prompt |
| `apps/agent-player/euler_play.py` | Pass xiangqi FEN via `--fen` flag to `ask_move.py` |

No new dependencies needed — `cchess` is already installed.
