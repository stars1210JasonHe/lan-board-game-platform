#!/usr/bin/env python3
"""
xiangqi_attack.py — Pure Python xiangqi attack detection.

Board: 10×9 grid, row 0 = Black's back rank (top), row 9 = Red's back rank (bottom).
Pieces: uppercase = Red (R,N,B,A,K,C,P), lowercase = Black (r,n,b,a,k,c,p).
Also accepts H/h (Horse) and E/e (Elephant) in FEN.
"""

RED = 'red'
BLACK = 'black'

PIECE_NAMES = {
    'k': 'King', 'a': 'Advisor', 'b': 'Elephant', 'e': 'Elephant',
    'n': 'Horse', 'h': 'Horse', 'r': 'Chariot', 'c': 'Cannon', 'p': 'Soldier',
}

# Horse move deltas: (dr, dc, block_dr, block_dc)
_HORSE_MOVES = [
    (-2, -1, -1, 0), (-2, 1, -1, 0),
    (2, -1, 1, 0),   (2, 1, 1, 0),
    (-1, -2, 0, -1),  (-1, 2, 0, 1),
    (1, -2, 0, -1),   (1, 2, 0, 1),
]


def piece_side(ch):
    """Return 'red', 'black', or None for empty."""
    if not ch or ch == ' ' or ch == '.':
        return None
    return RED if ch.isupper() else BLACK


def fen_to_board(fen):
    """Parse xiangqi FEN → (board, side).
    board: list of 10 rows, each a list of 9 chars (' ' = empty).
    side: 'red' or 'black'.
    """
    parts = fen.split()
    board = []
    for row_str in parts[0].split('/'):
        row = []
        for ch in row_str:
            if ch.isdigit():
                row.extend([' '] * int(ch))
            else:
                row.append(ch)
        board.append(row[:9] + [' '] * max(0, 9 - len(row)))
    while len(board) < 10:
        board.append([' '] * 9)
    side = RED if len(parts) < 2 or parts[1] == 'w' else BLACK
    return board, side


def copy_board(board):
    return [row[:] for row in board]


def apply_move(board, fr, fc, tr, tc):
    """Apply move in-place. Returns captured piece char (or ' ')."""
    captured = board[tr][tc]
    board[tr][tc] = board[fr][fc]
    board[fr][fc] = ' '
    return captured


def _in_palace(r, c, side):
    if not (3 <= c <= 5):
        return False
    return (7 <= r <= 9) if side == RED else (0 <= r <= 2)


def _can_attack(board, pr, pc, tr, tc):
    """Can the piece at (pr,pc) reach (tr,tc) by movement rules?
    Checks geometry and path obstructions only — does NOT check target side."""
    piece = board[pr][pc]
    if not piece or piece == ' ':
        return False
    pt = piece.lower()
    side = RED if piece.isupper() else BLACK
    dr, dc = tr - pr, tc - pc

    # ── Rook / Chariot ──
    if pt == 'r':
        if (dr != 0) == (dc != 0) or (dr == 0 and dc == 0):
            return False
        if dr == 0:
            step = 1 if dc > 0 else -1
            for c in range(pc + step, tc, step):
                if board[pr][c] != ' ':
                    return False
        else:
            step = 1 if dr > 0 else -1
            for r in range(pr + step, tr, step):
                if board[r][pc] != ' ':
                    return False
        return True

    # ── Horse ──
    if pt in ('n', 'h'):
        for mdr, mdc, blr, blc in _HORSE_MOVES:
            if dr == mdr and dc == mdc:
                lr, lc = pr + blr, pc + blc
                return 0 <= lr <= 9 and 0 <= lc <= 8 and board[lr][lc] == ' '
        return False

    # ── Cannon ──
    if pt == 'c':
        if (dr != 0) == (dc != 0) or (dr == 0 and dc == 0):
            return False
        count = 0
        if dr == 0:
            step = 1 if dc > 0 else -1
            for c in range(pc + step, tc, step):
                if board[pr][c] != ' ':
                    count += 1
        else:
            step = 1 if dr > 0 else -1
            for r in range(pr + step, tr, step):
                if board[r][pc] != ' ':
                    count += 1
        return count == 1 if board[tr][tc] != ' ' else count == 0

    # ── Elephant ──
    if pt in ('b', 'e'):
        if abs(dr) != 2 or abs(dc) != 2:
            return False
        if side == RED and tr < 5:
            return False
        if side == BLACK and tr > 4:
            return False
        return board[pr + dr // 2][pc + dc // 2] == ' '

    # ── Advisor ──
    if pt == 'a':
        return abs(dr) == 1 and abs(dc) == 1 and _in_palace(tr, tc, side)

    # ── King ──
    if pt == 'k':
        return abs(dr) + abs(dc) == 1 and _in_palace(tr, tc, side)

    # ── Pawn / Soldier ──
    if pt == 'p':
        if side == RED:
            if pr >= 5:  # Before crossing river
                return dr == -1 and dc == 0
            return (dr == -1 and dc == 0) or (dr == 0 and abs(dc) == 1)
        else:
            if pr <= 4:  # Before crossing river
                return dr == 1 and dc == 0
            return (dr == 1 and dc == 0) or (dr == 0 and abs(dc) == 1)

    return False


def is_attacked_by(board, row, col, by_side):
    """Is square (row,col) attacked by any piece of by_side?"""
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p == ' ' or piece_side(p) != by_side:
                continue
            if _can_attack(board, r, c, row, col):
                t = board[row][col]
                if t != ' ' and piece_side(t) == by_side:
                    continue  # Can't capture own piece
                return True
    return False


def get_attackers(board, row, col, by_side):
    """List of (piece_char, r, c) for all by_side pieces attacking (row,col)."""
    result = []
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p == ' ' or piece_side(p) != by_side:
                continue
            if _can_attack(board, r, c, row, col):
                t = board[row][col]
                if t != ' ' and piece_side(t) == by_side:
                    continue
                result.append((p, r, c))
    return result


def is_defended(board, row, col, by_side):
    """Is (row,col) defended by any OTHER piece of by_side?"""
    for r in range(10):
        for c in range(9):
            if r == row and c == col:
                continue
            p = board[r][c]
            if p == ' ' or piece_side(p) != by_side:
                continue
            if _can_attack(board, r, c, row, col):
                return True
    return False


def _square_name(col, row):
    return chr(ord('a') + col) + str(row)


def get_attacked_pieces_info(board, side):
    """Return human-readable attack info string (same format as old cchess version)."""
    opp = BLACK if side == RED else RED

    our_attacked = []
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p == ' ' or piece_side(p) != side:
                continue
            atks = get_attackers(board, r, c, opp)
            if atks:
                att_str = ", ".join(
                    PIECE_NAMES.get(a[0].lower(), 'piece').lower() for a in atks
                )
                name = PIECE_NAMES.get(p.lower(), 'piece')
                our_attacked.append(f"{name} on {_square_name(c, r)} (by {att_str})")

    opp_capturable = []
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p == ' ' or piece_side(p) != opp:
                continue
            atks = get_attackers(board, r, c, side)
            if atks:
                defended_flag = is_defended(board, r, c, opp)
                defense_str = "defended" if defended_flag else "undefended"
                name = PIECE_NAMES.get(p.lower(), 'piece')
                opp_capturable.append(
                    f"{name} on {_square_name(c, r)} ({defense_str})"
                )

    lines = []
    if our_attacked:
        lines.append(f"Your pieces under attack: {', '.join(our_attacked)}")
    if opp_capturable:
        lines.append(f"Opponent pieces you can capture: {', '.join(opp_capturable)}")
    return "\n".join(lines)
