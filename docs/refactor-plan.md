# Refactoring Plan: AI Move & Chat Architecture

## Overview

This document covers six refactoring tasks to simplify the AI move/chat pipeline
in the LAN board game platform. The current architecture has accumulated
duplication, dead code, and convoluted fallback paths across `euler_play.py`,
`ask_move.py`, and the server's `llm.ts`/`index.ts`.

---

## Current Architecture

```
Human player (browser)
  │
  ├─ WebSocket ─► apps/server/src/index.ts (game logic, room mgmt)
  │                   │
  │                   ├─ /api/move ─► llmChat() ─► openclaw CLI / direct API
  │                   ├─ /api/chat ─► llmChat() ─► openclaw CLI / direct API
  │                   └─ spawnEulerAgent() ─► euler_play.py (subprocess)
  │
  └─ euler_play.py (WebSocket client)
       │
       ├─ pick_move() ─► 3 fallback layers:
       │     1. api_move()       → server /api/move → llmChat()
       │     2. engine mode      → Stockfish / Fairy-Stockfish
       │     3. local fallback   → xiangqi_move() / chess_move() / gomoku_move()
       │
       ├─ ai_chess_move()    → subprocess ask_move.py  (UNUSED by pick_move)
       ├─ ai_xiangqi_move()  → subprocess ask_move.py  (UNUSED by pick_move)
       │
       ├─ chat_reply() / event_reply() ─► 2 paths:
       │     openclaw  → api_chat() → server /api/chat → llmChat()
       │     direct    → chat_via_direct_api() → ask_move.py functions
       │
       └─ ask_move.py (outside repo, at workspace/skills/game-player/)
             ├─ reads SKILL.md from its own directory (single combined file)
             └─ 5 LLM backends: openclaw, anthropic, openai, openrouter, ollama
```

### Problems

1. `ask_move.py` lives outside the repo (`~/.openclaw/workspace/skills/game-player/`)
2. `pick_move()` has 3 tangled fallback layers — hard to reason about
3. Xiangqi piece movement logic is copy-pasted: `xiangqi_move()` (L466-577) and `ai_xiangqi_move()` (L582-664)
4. `ai_chess_move()` (L688-725) and `ai_xiangqi_move()` (L582-685) are never called from `pick_move()`
5. Chat has two independent code paths with duplicated dispatch logic
6. `llmChat()` in `llm.ts` is only reachable via server HTTP endpoints — after refactor it may become dead code

---

## Proposed Architecture

```
euler_play.py (WebSocket client)
  │
  ├─ pick_move(gs) ─► single dispatch:
  │     │
  │     ├─ engine mode → Stockfish / Fairy-Stockfish (unchanged)
  │     │
  │     ├─ LLM mode   → subprocess ask_move.py (in-repo)
  │     │                  reads skills/{game}-player/SKILL.md
  │     │                  supports: openclaw, anthropic, openai, openrouter, ollama
  │     │
  │     └─ fallback    → local generators (gomoku_move, chess_move, xiangqi_move)
  │
  ├─ chat_dispatch(text, context) ─► unified:
  │     openclaw → api_chat() → server /api/chat
  │     direct   → subprocess ask_move.py --chat mode
  │
  └─ xiangqi piece logic → single xiangqi_legal_moves() used by both
       xiangqi_move() and ask_move.py call
```

---

## Task 1: Move ask_move.py Into the Repo

### Current State

- **Location**: `~/.openclaw/workspace/skills/game-player/ask_move.py` (outside repo)
- **Reference**: `euler_play.py:23-24` — `ASK_MOVE_PATH` navigates `../../../skills/game-player/ask_move.py`
- **SKILL.md loading**: `ask_move.py:11-12` reads `SKILL.md` from its own directory (a single combined file)
- **Section parsing**: `ask_move.py:21-49` — `load_system_prompt()` parses markers like `## Xiangqi (Chinese Chess) Rules` and `## Chess (International Chess) Rules`

### Proposed Changes

1. **Copy** `ask_move.py` to `apps/agent-player/ask_move.py`
2. **Update `ASK_MOVE_PATH`** in `euler_play.py:23-24`:
   ```python
   ASK_MOVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ask_move.py")
   ```
3. **Change `load_system_prompt()`** to read per-game SKILL.md files:
   ```python
   REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

   def load_system_prompt(game: str) -> str:
       skill_path = os.path.join(REPO_ROOT, "skills", f"{game}-player", "SKILL.md")
       try:
           text = open(skill_path).read()
           # Strip YAML frontmatter
           if text.startswith('---'):
               end = text.index('---', 3)
               text = text[end+3:].strip()
           return f"You are an expert {game} player.\n\n{text}\n\n" \
                  "When asked for a move, reply with ONLY the move in the format shown above."
       except FileNotFoundError:
           return f"You are an expert {game} player."
   ```
4. **Update `_SECRETS_DIR`** in `ask_move.py:183` to use the new relative path
5. **Add `--game gomoku` support** to `ask_move.py:296` (currently only chess/xiangqi)
6. **Remove** the old file from `skills/game-player/` (or leave as deprecated symlink)

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `apps/agent-player/ask_move.py` | new | Moved file |
| `apps/agent-player/euler_play.py` | L23-24 | Update ASK_MOVE_PATH |
| `apps/agent-player/ask_move.py` | L10-12 | New SKILL.md loading |
| `apps/agent-player/ask_move.py` | L21-49 | Rewrite load_system_prompt() |
| `apps/agent-player/ask_move.py` | L183 | Update _SECRETS_DIR path |
| `apps/agent-player/ask_move.py` | L296 | Add gomoku to --game choices |

### Risks

- Old `ask_move.py` may still be referenced by other tooling outside the repo
- SKILL.md format differences between combined vs per-game files (section markers no longer needed)
- `_SECRETS_DIR` path changes — secrets loading could break if relative paths wrong

### Testing

- [ ] `python3 apps/agent-player/ask_move.py --game chess --side white --board-json '...' --engine anthropic` works
- [ ] `python3 apps/agent-player/ask_move.py --game xiangqi --side red --board-json '...' --engine openclaw` works
- [ ] Verify SKILL.md content is correctly loaded (no YAML frontmatter in system prompt)
- [ ] Verify secrets are found from new path

---

## Task 2: Simplify pick_move() Fallback Layers (3 → 1)

### Current State

`euler_play.py:857-930` — `pick_move()` has three interleaved paths:

```
Layer 1 (L866-873): mode == 'ai'    → api_move() → server /api/move → llmChat()
Layer 2 (L876-900): mode == 'engine' → Stockfish/Fairy-Stockfish subprocess
Layer 3 (L902-930): mode == 'euler'  → api_move() → server /api/move → llmChat()
                                       + local fallback (xiangqi_move/chess_move)
```

Mode 'ai' and 'euler' both call `api_move()` identically. The only difference is 'euler'
has an `if ai_chat and mode == 'euler'` guard (L913, 923), making it confusing.

### Proposed Changes

Collapse into a single linear dispatch:

```python
async def pick_move(gs):
    """Returns (move, used_fallback) tuple."""
    if not gs or gs.get("finished"):
        return None, False
    gt = gs.get("gameType")

    # 1. Engine mode: Stockfish / Fairy-Stockfish
    if mode == 'engine' and gt in ('chess', 'xiangqi'):
        result = await _engine_move(gs, gt)
        if result:
            return result, False
        print("Engine failed, falling to LLM")

    # 2. LLM mode: ask_move.py (direct subprocess, no server round-trip)
    if gt in ('chess', 'xiangqi'):
        result = await _llm_move(gs, gt)
        if result:
            return result, False
        print("LLM failed, falling to local")
    elif gt == 'gomoku':
        # Gomoku: try LLM, else minimax
        result = await _llm_move(gs, gt)
        if result:
            return result, False

    # 3. Local fallback (always available)
    return _local_move(gs, gt), gt != 'gomoku'  # gomoku minimax isn't a "fallback"
```

This removes the mode='ai' vs mode='euler' distinction for LLM moves — both now
call `ask_move.py` directly instead of routing through the server.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `apps/agent-player/euler_play.py` | L857-930 | Rewrite pick_move() |
| `apps/agent-player/euler_play.py` | L54-80 | Remove api_move() (no longer needed for moves) |
| `apps/agent-player/euler_play.py` | L738-746 | Remove --mode 'ai' vs 'euler' distinction |

### Risks

- Removing the server `/api/move` path means the server's retry logic (3 retries with
  corrective prompts, `index.ts:617-626`) is lost — must replicate in ask_move.py
- Gomoku currently has no ask_move.py support — needs Task 1 completion first
- mode='euler' users who expect server-side LLM routing will get ask_move.py instead

### Testing

- [ ] `--mode euler` plays chess correctly via ask_move.py
- [ ] `--mode engine` plays chess via Stockfish, falls back to ask_move.py on failure
- [ ] Gomoku still works with minimax fallback
- [ ] Xiangqi plays correctly end-to-end
- [ ] `--mode ai` flag either removed or aliased to unified behavior

---

## Task 3: Deduplicate Xiangqi Piece Logic

### Current State

The xiangqi piece movement rules are implemented **twice**:

**Copy 1**: `xiangqi_move()` at `euler_play.py:466-577`
- Helper functions: `in_bounds`, `is_enemy`, `is_empty`, `can_target` (L472-485)
- `piece_moves(r, c, p)` for K, A, B, N, R, C, P (L487-553)
- Collects moves, prefers captures, returns random (L556-577)

**Copy 2**: `ai_xiangqi_move()` at `euler_play.py:582-664`
- Identical helpers: `in_bounds`, `is_enemy`, `is_empty`, `can_target` (L588-597)
- Identical piece movement logic inline (not in a function) (L606-664)
- Used only to build `legal_moves` list for ask_move.py input

The two copies are nearly identical — same helper functions, same piece movement
rules, same variable names. The only difference is `xiangqi_move()` wraps the logic
in `piece_moves()` and returns a random move, while `ai_xiangqi_move()` inlines it
and feeds the list to ask_move.py.

### Proposed Changes

Extract a shared `xiangqi_legal_moves(board_rows, side)` function:

```python
def xiangqi_legal_moves(board_rows, side):
    """Generate all pseudo-legal xiangqi moves for the given side.
    Returns list of {fromRow, fromCol, toRow, toCol} dicts."""
    upper = side == 'red'
    board = [list(row) for row in board_rows]

    def in_bounds(r, c): return 0 <= r <= 9 and 0 <= c <= 8
    def is_enemy(r, c): ...
    def is_empty(r, c): ...
    def can_target(r, c): ...
    def piece_moves(r, c, p): ...  # existing logic from xiangqi_move()

    moves = []
    for r, row in enumerate(board):
        for c, p in enumerate(row):
            if p == ' ': continue
            if (p == p.upper()) != upper: continue
            for nr, nc in piece_moves(r, c, p):
                moves.append({"fromRow": r, "fromCol": c, "toRow": nr, "toCol": nc})
    return moves


def xiangqi_move(board_rows, side):
    """Pick a random xiangqi move, preferring captures."""
    moves = xiangqi_legal_moves(board_rows, side)
    if not moves: return None
    board = [list(row) for row in board_rows]
    upper = side == 'red'
    captures = [m for m in moves if board[m["toRow"]][m["toCol"]] != ' '
                and (board[m["toRow"]][m["toCol"]].isupper() != upper)]
    return random.choice(captures) if captures else random.choice(moves)
```

Then `ai_xiangqi_move()` (before removal in Task 4) would simply call
`xiangqi_legal_moves()` instead of duplicating the logic.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `apps/agent-player/euler_play.py` | L466-577 | Extract xiangqi_legal_moves(), simplify xiangqi_move() |
| `apps/agent-player/euler_play.py` | L582-664 | Replace inline logic with xiangqi_legal_moves() call |

### Risks

- Subtle differences between the two copies could exist (verify with diff)
- `xiangqi_move()` operates on mutable board copy — ensure `xiangqi_legal_moves()`
  doesn't mutate its input

### Testing

- [ ] Diff the two implementations line-by-line to confirm they're semantically identical
- [ ] Play 5+ xiangqi games to verify move generation still works
- [ ] Verify captured pieces are still preferred in xiangqi_move()
- [ ] Run against Fairy-Stockfish to confirm no illegal moves

---

## Task 4: Remove ai_chess_move() and ai_xiangqi_move(), Unify in pick_move()

### Current State

- **`ai_chess_move()`** (`euler_play.py:688-725`): Converts UCI legal moves to
  fromRow/fromCol format, calls ask_move.py subprocess, converts result back to UCI.
  **Never called from pick_move() or anywhere in the main loop.**

- **`ai_xiangqi_move()`** (`euler_play.py:582-685`): Generates legal moves (duplicated
  logic — Task 3), calls ask_move.py subprocess, falls back to `xiangqi_move()`.
  **Never called from pick_move() or anywhere in the main loop.**

Both functions exist as orphaned code. The `pick_move()` function routes LLM moves
through `api_move()` (server HTTP endpoint) instead.

### Proposed Changes

1. **Delete `ai_chess_move()`** (L688-725) entirely
2. **Delete `ai_xiangqi_move()`** (L582-685) entirely
3. **Add `_llm_move()` helper** to pick_move() that calls ask_move.py directly:

```python
async def _llm_move(gs, gt):
    """Call ask_move.py as subprocess for LLM-based move."""
    side = my_side or gs.get("currentPlayer", "")
    board_json = json.dumps({
        "board": gs.get("board", []),
        "legalMoves": _get_legal_moves(gs, gt),
    })
    cmd = [sys.executable, ASK_MOVE_PATH, "--game", gt, "--side", side,
           "--board-json", board_json, "--engine", ai_engine, "--timeout", "50"]
    if ai_model:
        cmd += ["--model", ai_model]
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        )
        return _parse_ask_move_output(result.stdout.strip(), gt)
    except Exception as e:
        print(f"ask_move.py error: {e}")
        return None
```

4. **The UCI ↔ coordinate conversion** from `ai_chess_move()` should be absorbed into
   the `_parse_ask_move_output()` helper

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `apps/agent-player/euler_play.py` | L582-725 | Delete ai_xiangqi_move() and ai_chess_move() |
| `apps/agent-player/euler_play.py` | new | Add _llm_move() helper near pick_move() |
| `apps/agent-player/euler_play.py` | new | Add _parse_ask_move_output() helper |

### Risks

- `ai_chess_move()` has UCI conversion logic (L694-722) that must be preserved in the
  new `_llm_move()` / `_parse_ask_move_output()`
- Need to verify that legal moves format from game_state matches what ask_move.py expects
- If chess game_state doesn't include board rows (only FEN), need alternative path

### Testing

- [ ] Play chess game end-to-end in LLM mode — verify UCI moves are correctly generated
- [ ] Play xiangqi game end-to-end — verify coordinate moves work
- [ ] Verify no references to deleted functions remain (`grep -r ai_chess_move`, `grep -r ai_xiangqi_move`)
- [ ] Test with each ai_engine: openclaw, anthropic, openai

---

## Task 5: Unify Chat Dispatch

### Current State

Chat routing has two independent paths with duplicated dispatch logic:

**Path 1 — `api_chat()`** (`euler_play.py:83-95`):
- Calls server `POST /api/chat`
- Server uses `llmChat()` which routes through openclaw CLI or direct API
- Used when `ai_engine == "openclaw"`

**Path 2 — `chat_via_direct_api()`** (`euler_play.py:98-121`):
- Imports `ask_move` module directly via `sys.path` manipulation (L101)
- Calls `ask_move.call_openai()` / `call_openrouter()` / `call_anthropic()` directly
- Used when `ai_engine != "openclaw"`

The dispatch is duplicated in **two places**:
- `chat_reply()` at L776-794
- `event_reply()` at L796-806

Both have identical `if ai_engine == "openclaw": api_chat() else: chat_via_direct_api()` logic.

### Proposed Changes

Keep both paths (openclaw → server API, direct → ask_move.py functions), but unify
the dispatch into a single function:

```python
async def chat_dispatch(text: str, context: str = "", game_type: str = "") -> str | None:
    """Route chat to the appropriate backend."""
    if ai_engine == "openclaw":
        return await api_chat(base_url, text, context, game_type)
    else:
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat_via_direct_api(text, context, ai_engine, ai_model)
        )
```

Then simplify `chat_reply()` and `event_reply()`:

```python
async def chat_reply(text, context="", gt=""):
    if ai_chat:
        reply = await chat_dispatch(text, context, gt)
        if reply: return reply
    # keyword fallback...

async def event_reply(text, fallback_key, context="", gt=""):
    if ai_chat:
        reply = await chat_dispatch(text, context, gt)
        if reply: return reply
    return random.choice(CANNED.get(fallback_key, ["..."]))
```

Also clean up `chat_via_direct_api()`:
- Remove `sys.path` manipulation (L101) — after Task 1, ask_move.py is in the same directory
- Import at module level instead of inside the function

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `apps/agent-player/euler_play.py` | L98-121 | Clean up chat_via_direct_api() imports |
| `apps/agent-player/euler_play.py` | L776-806 | Add chat_dispatch(), simplify chat_reply/event_reply |

### Risks

- `api_chat()` includes `game_type` parameter; `chat_via_direct_api()` does not — need to
  ensure game_type context is passed in both paths
- The server's `/api/chat` endpoint (index.ts:735-764) adds `CHAT_SYSTEM_CONTEXT` — the
  direct path builds its own system prompt. These should be kept consistent.

### Testing

- [ ] Test chat with `--ai-engine openclaw` — replies come through server API
- [ ] Test chat with `--ai-engine anthropic` — replies come through direct API
- [ ] Verify game context is included in both paths
- [ ] Verify canned fallback still works when AI chat fails

---

## Task 6: Server llmChat() — Document or Remove

### Current State

**`llm.ts`** exports:
- `llmChat()` (L164-177) — routes to `chatOpenClaw()` or `chatDirectAPI()`
- `getSkill()` (L182-187) — returns pre-loaded SKILL.md content
- `getLLMProvider()` (L189-191) — returns provider name
- `getLLMModel()` (L193-195) — returns model name

**Usage in `index.ts`**:
- `handleApiMove()`: chess (L618), xiangqi (L672), gomoku (L710)
- `handleApiChat()`: L751
- Import at L11: `import { llmChat, getSkill } from './llm.js'`

`llmChat()` is **NOT dead code today** — it's actively called by the `/api/move` and
`/api/chat` HTTP endpoints. However, after Tasks 2 and 4, the euler agent will no
longer call `/api/move` (it will use ask_move.py directly). The `/api/chat` endpoint
is still used for openclaw-mode chat (Task 5 keeps this path).

### Analysis

After the refactor:
- `/api/move` — only called by euler agent in mode='euler'. After Task 2, euler mode
  will use ask_move.py directly. **This endpoint becomes dead code.**
- `/api/chat` — still called by euler agent when `ai_engine == "openclaw"`.
  **This endpoint remains alive.**

So `llmChat()` itself won't be dead code, but `handleApiMove()` (index.ts:570-731)
and the move-specific skill loading in `llm.ts` (L78-83) will become dead.

### Proposed Changes

**Option A: Keep and document** (recommended for now)
- Add comments documenting that `/api/move` is only used as a fallback / for external clients
- Keep the endpoint functional for potential external consumers (curl, other bots)
- Mark move-related session IDs (`euler-chess-moves`, etc.) as deprecated

**Option B: Remove `/api/move` entirely**
- Delete `handleApiMove()` (index.ts:570-731)
- Remove chess/xiangqi skill loading from `llm.ts` (L78-83)
- Keep `llmChat()` for `/api/chat` only
- Simplify `llm.ts` to only export chat functionality

### Files Changed (Option A)

| File | Lines | Change |
|------|-------|--------|
| `apps/server/src/index.ts` | L570 | Add deprecation comment to handleApiMove() |
| `apps/server/src/llm.ts` | L78-83 | Document skill loading as move-endpoint-only |

### Files Changed (Option B)

| File | Lines | Change |
|------|-------|--------|
| `apps/server/src/index.ts` | L570-731 | Delete handleApiMove() |
| `apps/server/src/index.ts` | L819-821 | Remove /api/move route |
| `apps/server/src/llm.ts` | L78-83 | Remove chess/xiangqi skill loading |
| `apps/server/src/llm.ts` | L182-187 | Remove getSkill() export |

### Risks

- `/api/move` might be used by other clients or debugging tools
- Removing it breaks the `--mode euler` fallback path if Task 2 isn't fully complete
- `getLLMProvider()` and `getLLMModel()` may be used by the frontend for display

### Testing

- [ ] After refactor, verify `/api/chat` still works
- [ ] If Option B: verify no runtime errors from removed imports
- [ ] Check frontend doesn't call `/api/move` directly
- [ ] Grep codebase for `/api/move` references outside euler_play.py

---

## Execution Order

Tasks have dependencies:

```
Task 1 (move ask_move.py) ──► Task 4 (remove ai_*_move, add _llm_move)
                                │
Task 3 (dedup xiangqi) ────────┘
                                │
                                ▼
                          Task 2 (simplify pick_move)
                                │
                                ▼
                          Task 5 (unify chat dispatch)
                                │
                                ▼
                          Task 6 (document/remove llmChat)
```

**Recommended order**: 1 → 3 → 4 → 2 → 5 → 6

Each task should be a separate commit with tests passing before moving to the next.

---

## Full Testing Checklist

### Functional Tests

- [ ] Chess: LLM mode (ask_move.py), engine mode (Stockfish), local fallback
- [ ] Xiangqi: LLM mode, engine mode (Fairy-Stockfish), local fallback
- [ ] Gomoku: LLM mode (if added), minimax fallback
- [ ] Chat: openclaw engine, direct API engine (anthropic/openai/openrouter)
- [ ] Mode switching via `/engine` and `/euler` in-game commands
- [ ] Illegal move retry logic still works (MAX_ILLEGAL_RETRIES)
- [ ] Position loop detection still works (FEAT-3)

### Integration Tests

- [ ] Server spawns euler agent (`spawnEulerAgent`) — agent connects, plays, chats
- [ ] Human vs AI: full game lifecycle (create room → play → match end → rematch)
- [ ] Multiple AI engines: `AI_ENGINE=anthropic`, `AI_ENGINE=openrouter`
- [ ] Secrets loading from `.secrets/` directory works from new ask_move.py location

### Regression Tests

- [ ] No broken imports (`grep -r "from ask_move" .`, `grep -r "import ask_move" .`)
- [ ] No orphaned references (`grep -r ai_chess_move .`, `grep -r ai_xiangqi_move .`)
- [ ] WebSocket reconnection still works
- [ ] Match history DB recording unchanged

---

## Line Reference Summary

| Function / Symbol | File | Lines | Status After Refactor |
|---|---|---|---|
| `ASK_MOVE_PATH` | euler_play.py | 23-24 | Updated path |
| `api_move()` | euler_play.py | 54-80 | Removed (or kept for fallback) |
| `api_chat()` | euler_play.py | 83-95 | Kept (openclaw chat path) |
| `chat_via_direct_api()` | euler_play.py | 98-121 | Cleaned up imports |
| `xiangqi_move()` | euler_play.py | 466-577 | Refactored to use xiangqi_legal_moves() |
| `ai_xiangqi_move()` | euler_play.py | 582-685 | **Deleted** |
| `ai_chess_move()` | euler_play.py | 688-725 | **Deleted** |
| `pick_move()` | euler_play.py | 857-930 | Simplified to 1 dispatch layer |
| `chat_reply()` | euler_play.py | 776-794 | Uses chat_dispatch() |
| `event_reply()` | euler_play.py | 796-806 | Uses chat_dispatch() |
| `load_system_prompt()` | ask_move.py | 21-49 | Reads skills/{game}-player/SKILL.md |
| `ENGINES` dict | ask_move.py | 285-291 | Unchanged |
| `llmChat()` | llm.ts | 164-177 | Kept for /api/chat |
| `getSkill()` | llm.ts | 182-187 | Deprecated or removed |
| `handleApiMove()` | index.ts | 570-731 | Deprecated or removed |
| `handleApiChat()` | index.ts | 735-764 | Kept |

---

## Task 7: Unify Move Output Format (SAN vs Coordinates)

### Problem

Two different output formats exist:

| Source | Format | Example |
|--------|--------|---------|
| External `ask_move.py` (current) | Coordinates `fromRow,fromCol,toRow,toCol` | `6,4,4,4` |
| GitHub `skills/chess-player/SKILL.md` | SAN notation | `Nf3` |

After the refactor, `ask_move.py` will read GitHub's SKILL.md which instructs the LLM to output SAN. But `euler_play.py` communicates with the server using coordinate/UCI format internally. This mismatch will cause move parsing failures.

### Options

| Option | Pros | Cons |
|--------|------|------|
| **A: LLM outputs SAN → ask_move.py converts to coordinates** | SAN is natural for LLMs (in training data), shorter output, fewer tokens | Needs SAN→UCI→coordinate conversion logic |
| **B: Modify SKILL.md to request coordinates** | No conversion needed | Coordinates unnatural for LLM, worse move quality |
| **C: LLM outputs SAN → euler_play.py converts** | Clean separation (ask_move returns SAN, euler_play handles conversion) | euler_play.py needs python-chess for SAN parsing |

### Recommendation: Option A

- LLM outputs SAN (e.g. `Nf3`) — this is what it's best at
- `ask_move.py` converts SAN → `fromRow,fromCol,toRow,toCol` using python-chess (already available)
- `euler_play.py` receives coordinates as before — no change needed downstream
- For xiangqi: LLM outputs coordinate notation (e.g. `b0c2`) since no standard SAN exists; `ask_move.py` converts to `fromRow,fromCol,toRow,toCol`

### Affected Files

| File | Change |
|------|--------|
| `ask_move.py` | `parse_move()` accepts SAN input, converts to coordinate output |
| `skills/chess-player/SKILL.md` | Already requests SAN — no change |
| `skills/xiangqi-player/SKILL.md` | Verify coordinate format matches |
| `euler_play.py` | No change (still receives coordinates) |

### Risk

- SAN parsing depends on knowing the current board position (same SAN can mean different moves)
- `ask_move.py` needs access to python-chess `Board` object with current FEN to resolve SAN
- Must pass `--fen` argument to `ask_move.py` for chess SAN resolution

### Execution Order

After Task 2 (move ask_move.py), before Task 4 (unify pick_move).
