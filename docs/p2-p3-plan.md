# P2-P3 Implementation Plan

Phase 2 and Phase 3 improvements from `docs/ai-improvement-plan.md`.

---

## Task 1: Anti-blunder verification (chess + xiangqi)

### Goal

After the LLM picks a move, simulate it on the board and check if the opponent can immediately capture an undefended piece worth >= 3 (knight/bishop/rook/queen for chess; horse/cannon/chariot for xiangqi). If so, re-prompt the LLM with feedback. Max 2 retries, then accept the move.

### Files to change

| File | Action |
|------|--------|
| `apps/agent-player/ask_move.py` | Add `check_blunder_chess()`, `check_blunder_xiangqi()`, and `anti_blunder_wrap()` |

### Design

The anti-blunder logic wraps the existing engine call in `main()`. It does NOT change any engine function signatures. Flow:

```
main()
  ├── call engine → get response
  ├── parse_move() → get candidate move
  ├── check_blunder(fen, move, game) → returns blunder description or None
  │   ├── chess: use python-chess to push move, scan opponent captures
  │   └── xiangqi: use cchess to push move, scan opponent captures
  ├── if blunder found and retries < 2:
  │   ├── build feedback message: "Your move {SAN} hangs your {piece}. Pick a different move."
  │   ├── re-call engine with conversation history [user_prompt, assistant_response, user_feedback]
  │   └── loop
  └── output final move
```

### Functions to add

#### `check_blunder_chess(fen: str, uci_move: str) -> str | None`

```python
def check_blunder_chess(fen: str, uci_move: str) -> str | None:
    """Check if a chess move hangs a piece worth >= 3.
    Returns description string if blunder found, None otherwise."""
    import chess
    PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci_move)
    board.push(move)

    # Now it's opponent's turn. Check all opponent legal moves.
    for opp_move in board.legal_moves:
        captured = board.piece_at(opp_move.to_square)
        if captured and captured.color == (not board.turn):
            # This is our piece being captured
            cap_value = PIECE_VALUES.get(captured.piece_type, 0)
            if cap_value >= 3:
                # Is the target square defended by us after the capture?
                board.push(opp_move)
                # After opponent captures, can we recapture?
                can_recapture = any(
                    m.to_square == opp_move.to_square for m in board.legal_moves
                )
                board.pop()
                if not can_recapture:
                    piece_name = chess.piece_name(captured.piece_type).title()
                    san = chess.Board(fen).san(move)
                    return f"Your move {san} hangs your {piece_name}"
    return None
```

#### `check_blunder_xiangqi(fen: str, move_coords: str) -> str | None`

```python
def check_blunder_xiangqi(fen: str, move_coords: str) -> str | None:
    """Check if a xiangqi move hangs a piece worth >= 3 (Horse=4, Cannon=4.5, Chariot=9).
    Returns description string if blunder found, None otherwise."""
    import cchess
    PIECE_VALUES = {'r': 9, 'c': 4.5, 'n': 4, 'b': 2, 'a': 2, 'p': 1, 'k': 0}
    PIECE_NAMES = {'r': 'Chariot', 'c': 'Cannon', 'n': 'Horse',
                   'b': 'Elephant', 'a': 'Advisor', 'p': 'Pawn', 'k': 'King'}

    fen_parts = fen.split()
    short_fen = f"{fen_parts[0]} {fen_parts[1]}"
    board = cchess.ChessBoard(short_fen)
    our_color = cchess.RED if fen_parts[1] == 'w' else cchess.BLACK
    opp_color = cchess.BLACK if our_color == cchess.RED else cchess.RED

    # Parse move_coords "fr,fc,tr,tc" into cchess move format
    parts = move_coords.split(",")
    fr, fc, tr, tc = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    # Execute our move on the board
    # (cchess move execution — need to verify API)

    # After our move: scan all opponent pieces, check if they can capture
    # any of our pieces worth >= 3 that are undefended
    for opp_piece in board.get_pieces(opp_color):
        for our_piece in board.get_pieces(our_color):
            sq = (our_piece.x, our_piece.y)
            val = PIECE_VALUES.get(our_piece.species, 0)
            if val >= 3 and opp_piece.is_valid_move(sq):
                # Check if defended
                defended = False
                for defender in board.get_pieces(our_color):
                    if (defender.x, defender.y) != sq and defender.is_valid_move(sq):
                        defended = True
                        break
                if not defended:
                    name = PIECE_NAMES.get(our_piece.species, 'piece')
                    return f"Your move hangs your {name}"
    return None
```

**Note:** The cchess library's move-execution API needs to be verified during implementation. If `cchess.ChessBoard` doesn't support `push()`-style mutation, we may need to construct a new FEN after the move and create a fresh board.

#### Modify `main()` — anti-blunder retry loop

The retry loop goes in `main()` after the initial engine call + `parse_move()`, wrapping lines ~513-517:

```python
# After getting initial response + parsed move:
MAX_BLUNDER_RETRIES = 2
blunder_retries = 0
candidate_move = move  # from parse_move()
candidate_response = response

while candidate_move and candidate_move != 'resign' and blunder_retries < MAX_BLUNDER_RETRIES:
    blunder_msg = None
    if args.game == "chess" and args.fen:
        # Convert coord move back to UCI for check
        parts = candidate_move.split(",")
        uci = chr(ord('a')+int(parts[1])) + str(8-int(parts[0])) + \
              chr(ord('a')+int(parts[3])) + str(8-int(parts[2]))
        blunder_msg = check_blunder_chess(args.fen, uci)
    elif args.game == "xiangqi" and args.fen:
        blunder_msg = check_blunder_xiangqi(args.fen, candidate_move)

    if not blunder_msg:
        break  # Move is safe

    blunder_retries += 1
    print(f"[ask_move] Blunder detected (retry {blunder_retries}): {blunder_msg}", file=sys.stderr)
    feedback = f"{blunder_msg}. Pick a different move."

    # Re-call engine with feedback conversation
    messages = [
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": candidate_response},
        {"role": "user", "content": feedback},
    ]
    # Call engine with messages (anthropic/openai/openrouter support this)
    response2 = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                          messages=messages)
    if response2:
        candidate_response = response2
        candidate_move = parse_move(response2, legal_moves, fen=args.fen, san_moves=san_moves)
    else:
        break  # Engine failed, accept current move
```

**Engine compatibility note:** The `messages` parameter is already supported by `call_anthropic()`, `call_openai()`, `call_openrouter()`, and `call_ollama()`. For `call_openclaw()`, the session-based approach with `--message` flag handles multi-turn naturally, but we'll need to pass the feedback as a follow-up message. This may require a small adjustment to `call_openclaw()` to accept a `feedback` string and send it as a second call.

### Testing approach

1. **Unit test with known blunder positions:**
   - FEN where moving a knight leaves a rook undefended → `check_blunder_chess()` should detect it
   - FEN where moving a horse leaves a chariot undefended → `check_blunder_xiangqi()` should detect it
2. **Unit test with safe positions:**
   - Verify `check_blunder_chess()` returns `None` for normal developing moves
3. **Integration test:** Run `ask_move.py` with a position where the LLM commonly blunders, verify retry happens (visible in stderr logs)
4. **Manual play-test:** Play 3-5 games against AI, watch for reduced piece-hanging

### Rollback strategy

All changes are in `ask_move.py` only. The anti-blunder check is a pure wrapper — removing the while-loop and the two `check_blunder_*` functions restores original behavior. No other files are affected.

---

## Task 2: Chess attacked pieces info

### Goal

Add `chess_attacked_pieces_info(fen)` to show which of our pieces are under attack and which opponent pieces we can capture (with defended/undefended status). This was previously implemented in commit `5eb687f` but reverted in `2fe0c31`. The xiangqi equivalent (`xiangqi_attacked_pieces_info`) already exists and works — this is the chess counterpart.

### Files to change

| File | Action |
|------|--------|
| `apps/agent-player/ask_move.py` | Add `chess_attacked_pieces_info()`, modify `build_user_prompt()` |

### Recovery from commit 5eb687f

The function from the reverted commit is usable as-is. Key code to recover:

#### Add `chess_attacked_pieces_info(fen)` — after `xiangqi_attacked_pieces_info()` (line ~135)

```python
def chess_attacked_pieces_info(fen: str) -> str:
    """Analyze which pieces are under attack for chess using python-chess."""
    import chess
    board = chess.Board(fen)
    side = board.turn
    opp = not side

    PIECE_NAMES = {
        chess.PAWN: "Pawn", chess.KNIGHT: "Knight", chess.BISHOP: "Bishop",
        chess.ROOK: "Rook", chess.QUEEN: "Queen", chess.KING: "King",
    }

    # Our pieces under attack by opponent
    our_attacked = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == side and board.is_attacked_by(opp, sq):
            attackers = board.attackers(opp, sq)
            att_names = []
            for att_sq in attackers:
                att_piece = board.piece_at(att_sq)
                if att_piece:
                    att_names.append(PIECE_NAMES.get(att_piece.piece_type, "piece").lower())
            sq_name = chess.square_name(sq)
            piece_name = PIECE_NAMES.get(piece.piece_type, "piece")
            att_str = ", ".join(att_names) if att_names else "opponent"
            our_attacked.append(f"{piece_name} on {sq_name} (by {att_str})")

    # Opponent pieces we can capture
    opp_capturable = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == opp and board.is_attacked_by(side, sq):
            sq_name = chess.square_name(sq)
            piece_name = PIECE_NAMES.get(piece.piece_type, "piece")
            defended = board.is_attacked_by(opp, sq)
            defense_str = "defended" if defended else "undefended"
            opp_capturable.append(f"{piece_name} on {sq_name} ({defense_str})")

    lines = []
    if our_attacked:
        lines.append(f"Your pieces under attack: {', '.join(our_attacked)}")
    if opp_capturable:
        lines.append(f"Opponent pieces you can capture: {', '.join(opp_capturable)}")
    return "\n".join(lines)
```

#### Modify `build_user_prompt()` — add chess attack info

Current code (line ~144-149) only does xiangqi:

```python
    attack_info = ""
    if game == "xiangqi" and fen:
        try:
            attack_info = xiangqi_attacked_pieces_info(fen)
        except Exception as e:
            print(f"[ask_move] xiangqi attack info error: {e}", file=sys.stderr)
```

Change to handle both:

```python
    attack_info = ""
    if game == "xiangqi" and fen:
        try:
            attack_info = xiangqi_attacked_pieces_info(fen)
        except Exception as e:
            print(f"[ask_move] xiangqi attack info error: {e}", file=sys.stderr)
    elif game == "chess" and fen:
        try:
            attack_info = chess_attacked_pieces_info(fen)
        except Exception as e:
            print(f"[ask_move] chess attack info error: {e}", file=sys.stderr)
```

Then in the chess SAN branch (line ~151-161), append `attack_info`:

```python
    if game == "chess" and san_moves:
        moves_str = ", ".join(san_moves)
        extra = ""
        if attack_info:
            extra += f"\n{attack_info}"
        return (
            f"{board_str}\n\n"
            f"FEN: {fen}\n"
            f"Legal moves (SAN): [{moves_str}]"
            f"{extra}\n\n"
            f"Pick the BEST move. Reply with ONLY the SAN notation.\n"
            f"Example: Nf3\n"
            f"No explanation — just the move."
        )
```

### Why it was reverted last time

Commit `2fe0c31` reverted `5eb687f` along with the xiangqi version (`6c54b69`). The xiangqi version was then re-added separately in `1b15726` (using cchess instead of manual calculation). The chess version was never re-added. The revert was likely a blanket undo to fix an issue with the combined commit — the chess part was simply not re-applied afterward.

### Testing approach

1. **Unit test:** Call `chess_attacked_pieces_info()` with known FEN positions:
   - Position where a knight is attacked by a pawn → should show "Knight on d4 (by pawn)"
   - Position where we can capture an undefended bishop → should show "Bishop on c5 (undefended)"
   - Starting position → should return empty string (no pieces under attack)
2. **Prompt inspection:** Run `ask_move.py` with `--game chess --fen <test-fen>` and capture stderr/stdout to verify the attack info appears in the prompt
3. **Play-test:** Play 2-3 chess games, verify AI responds to attacked pieces more reliably

### Rollback strategy

Remove `chess_attacked_pieces_info()` function and revert the two edits in `build_user_prompt()`. The xiangqi path is untouched.

---

## Task 3: PGN format for chess

### Goal

Track PGN move history (SAN notation) throughout a chess game in `euler_play.py` and pass it to `ask_move.py` so the LLM sees "Game so far: 1. e4 e5 2. Nf3 Nc6 ..." in the prompt. Research shows LLMs play stronger with PGN because training data contains millions of PGN-formatted games.

### Files to change

| File | Action |
|------|--------|
| `apps/agent-player/euler_play.py` | Track PGN history, pass via `--pgn` arg |
| `apps/agent-player/ask_move.py` | Accept `--pgn` arg, include in chess prompt |

### Design

#### euler_play.py — PGN tracking

In `main()`, alongside the existing `position_history` dict (~line 670), add:

```python
pgn_moves = []    # SAN moves: ["e4", "e5", "Nf3", "Nc6", ...]
pgn_fen = None    # FEN before each move, for SAN conversion
```

**When to update:** After each `"move"` message is received (~line 930). The server sends `gameState` which contains `fen` and `lastMove` (UCI format). Convert UCI to SAN using the *previous* FEN:

```python
elif t == "move":
    illegal_retries = 0
    prev_fen = game_state.get("fen") if game_state else None
    game_state = msg.get("gameState", game_state)

    # Track PGN for chess
    if game_type == "chess" and prev_fen:
        last_move_uci = msg.get("move") or msg.get("gameState", {}).get("lastMoveUci")
        if last_move_uci:
            try:
                import chess
                b = chess.Board(prev_fen)
                m = chess.Move.from_uci(last_move_uci)
                san = b.san(m)
                pgn_moves.append(san)
            except Exception as e:
                print(f"[pgn] SAN conversion failed: {e}")
```

**Important:** We need to capture the FEN *before* the move is applied. The server's `gameState.fen` in the `"move"` message is the FEN *after* the move. So we must save the previous FEN before updating `game_state`.

**Alternative approach (simpler):** If the server doesn't provide the pre-move FEN reliably, we can maintain a local `chess.Board` object in `euler_play.py`:

```python
pgn_board = None   # chess.Board tracking game state

# On match_start:
if game_type == "chess":
    import chess
    pgn_board = chess.Board()
    pgn_moves = []

# On move:
if game_type == "chess" and pgn_board:
    last_move_uci = ...  # extract from message
    try:
        m = chess.Move.from_uci(last_move_uci)
        pgn_moves.append(pgn_board.san(m))
        pgn_board.push(m)
    except Exception:
        pass
```

This is more reliable because we always have the correct pre-move board state.

**Reset on match start** (~line 918) and match end (~line 997):

```python
pgn_moves = []
pgn_board = None  # or chess.Board() for chess
```

**Pass to ask_move.py** — in `_llm_move()` (~line 706):

```python
if gt == "chess" and pgn_moves:
    cmd += ["--pgn", " ".join(_format_pgn(pgn_moves))]

def _format_pgn(moves: list) -> list:
    """Format moves as PGN: ['1.', 'e4', 'e5', '2.', 'Nf3', 'Nc6', ...]"""
    parts = []
    for i in range(0, len(moves), 2):
        num = i // 2 + 1
        parts.append(f"{num}.")
        parts.append(moves[i])
        if i + 1 < len(moves):
            parts.append(moves[i + 1])
    return parts
```

Or simply pass the raw list and let `ask_move.py` format it.

#### ask_move.py — accept and use PGN

**Add CLI argument** in `main()` (~line 449):

```python
parser.add_argument("--pgn", default=None, help="PGN move history for chess")
```

**Pass to `build_user_prompt()`** — add `pgn` parameter:

```python
def build_user_prompt(game, board, side, legal_moves,
                      fen=None, san_moves=None, pgn=None):
```

**Include in chess prompt** — in the chess SAN branch:

```python
    if game == "chess" and san_moves:
        moves_str = ", ".join(san_moves)
        extra = ""
        if pgn:
            extra += f"\nGame so far: {pgn}"
        if attack_info:
            extra += f"\n{attack_info}"
        return (
            f"{board_str}\n\n"
            f"FEN: {fen}\n"
            f"Legal moves (SAN): [{moves_str}]"
            f"{extra}\n\n"
            ...
        )
```

**In `main()`, pass it through:**

```python
user_prompt = build_user_prompt(args.game, board, args.side, legal_moves,
                                fen=args.fen, san_moves=san_moves,
                                pgn=args.pgn)
```

### Token budget consideration

PGN grows linearly with game length. A 40-move game = ~80 half-moves ≈ 120 tokens. A 60-move game ≈ 180 tokens. This is acceptable given `max_tokens: 64` is for output only and typical chess games rarely exceed 80 moves.

If token budget becomes an issue later, truncate to the last N moves:

```python
if pgn and len(pgn) > 200:  # character limit
    pgn = "... " + pgn[-200:]
```

### Extracting the move from server messages

Need to verify what field contains the UCI move in the `"move"` WebSocket message. Check the server's message format:

```python
# euler_play.py currently handles "move" messages around line 929:
elif t == "move":
    game_state = msg.get("gameState", game_state)
```

The `msg` likely contains `msg["move"]` with the UCI string, or it's embedded in `msg["gameState"]["lastMoveUci"]`. During implementation, add a debug print to inspect the actual message structure from the server.

**Fallback:** If we can't reliably extract UCI from server messages, we can diff the FEN before/after to determine the move. But the local `chess.Board` approach avoids this entirely.

### Testing approach

1. **Unit test for PGN formatting:** Given `["e4", "e5", "Nf3", "Nc6"]`, output should be `"1. e4 e5 2. Nf3 Nc6"`
2. **Integration test:** Run `ask_move.py --game chess --fen <mid-game-fen> --pgn "1. e4 e5 2. Nf3 Nc6 3. Bb5"` and verify the PGN appears in the prompt (capture via debug output)
3. **Play-test:** Play a full game, verify PGN accumulates correctly in logs
4. **Regression:** Verify xiangqi and gomoku are unaffected (no `--pgn` arg passed)

### Rollback strategy

- `euler_play.py`: Remove `pgn_moves`, `pgn_board` variables and the tracking code in the `"move"` handler. Remove `--pgn` from the `cmd` construction in `_llm_move()`.
- `ask_move.py`: Remove `--pgn` argument, remove `pgn` parameter from `build_user_prompt()`. No other code is affected.

---

## Implementation Order

Recommended sequence:

1. **Task 2 first** (chess attacked pieces) — smallest change, recovers known-good code from 5eb687f, independent of other tasks
2. **Task 3 second** (PGN format) — moderate complexity, touches both files but is self-contained
3. **Task 1 last** (anti-blunder) — most complex, benefits from Task 2 being in place (attack info helps the LLM avoid blunders in the first place, reducing retry frequency)

### Dependency graph

```
Task 2 (attacked pieces) ──┐
                            ├──► Task 1 (anti-blunder) uses same python-chess/cchess imports
Task 3 (PGN format) ───────┘
```

Tasks 2 and 3 are independent of each other and could be done in parallel. Task 1 should come after both because:
- The `build_user_prompt()` changes from Task 2 and Task 3 should be stable before adding the retry loop
- Anti-blunder re-prompting should include the PGN and attack info in the feedback prompt

### Estimated diff size

| Task | Files | Lines added | Lines modified |
|------|-------|-------------|----------------|
| Task 1 | 1 (ask_move.py) | ~80 | ~15 |
| Task 2 | 1 (ask_move.py) | ~40 | ~10 |
| Task 3 | 2 (euler_play.py, ask_move.py) | ~50 | ~10 |

Total: ~170 new lines, ~35 modified lines across 2 files.
