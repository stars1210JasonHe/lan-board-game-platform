# Game Platform — Bug & Feature Tracker

Generated: 2026-03-09 from testing session.
Codebase: `lan-board-game-platform/apps/server/`

---

## Bugs

### BUG-1: Chat truncation during gameplay
- **Severity**: Medium
- **Location**: `src/index.ts` line 70, 104; `static/index.html` line 365-367
- **Symptom**: Chat messages disappear / get truncated during gameplay
- **Root cause**:
  1. `room_state` only sends last 50 chat messages (`room.chat.slice(-50)` at line 104)
  2. Frontend clears and rebuilds chat on every `room_state` update (`chatEl.innerHTML = ''` at line 366)
  3. Every move triggers a `room_state` broadcast → chat resets to last 50 entries
- **Fix**: Don't resend/rebuild chat on every room_state. Either:
  - (A) Frontend tracks chat incrementally via `chat` events only, skip chat in room_state after initial load
  - (B) Frontend merges incoming chat with existing instead of clearing

### BUG-2: Player side/color not clearly shown
- **Severity**: Low
- **Location**: `static/index.html` line 459
- **Symptom**: Player doesn't know which side they are during the game
- **Root cause**: Side is only shown inside the turn indicator when it's your turn: `Your turn (${mySide})`. No persistent indicator, no announcement at game start.
- **Fix**:
  1. Add a persistent side indicator in the match UI (e.g. "You are: ♟ BLACK" or "You are: ♔ WHITE")
  2. Show a brief announcement when match starts: "You are playing as BLACK"

### BUG-3: Xiangqi AI generates illegal moves then crashes
- **Severity**: High
- **Location**: `apps/agent-player/euler_play.py` lines ~870-900
- **Symptom**: Xiangqi AI (LLM mode) generates moves the server rejects as illegal. After 5 retries, agent skips turn and silently exits.
- **Root cause**: `api_move()` returns moves that don't match server's legal move list. After retry exhaustion, there's no fallback to local `xiangqi_move()` generator.
- **Evidence**: Server log showed 5 consecutive `illegal move` errors then `exited (code=0)`
- **Fix**:
  1. After retry exhaustion, fallback to `xiangqi_move()` (local rule-based generator)
  2. If local generator also fails, call `resign` instead of silently exiting

### BUG-4: Agent silent exit leaves game stuck
- **Severity**: High
- **Location**: `src/index.ts` (server), `apps/agent-player/euler_play.py`
- **Symptom**: When AI agent process dies, game stays in "playing" state. Opponent sees frozen board with no feedback.
- **Root cause**: Server doesn't detect that the agent's WebSocket closed and the game is stuck waiting for a move that will never come.
- **Fix**: Server should:
  1. Detect player disconnect via WebSocket `close` event (already fires `handleLeave`)
  2. If game is in progress, notify remaining player: "Opponent disconnected"
  3. Optionally auto-forfeit the disconnected player after 10 seconds

### BUG-5: Page refresh kicks player to lobby
- **Severity**: Medium
- **Location**: `static/index.html` (client state management)
- **Symptom**: Refreshing the browser during a game sends player back to the lobby instead of reconnecting to the match.
- **Root cause**: Client state (`myRoom`, `mySide`, `gameState`) is all in-memory JS variables. On refresh, everything resets. No session persistence (localStorage/sessionStorage) and no server-side reconnection mechanism.
- **Fix**:
  1. Save `roomId` and `clientId` to `sessionStorage` on join
  2. On page load, check sessionStorage for active room
  3. If found, auto-rejoin/reconnect to that room
  4. Server needs to handle reconnection: allow same nick to rejoin an in-progress game (replace old dead WebSocket)

---

## Feature Requests

### FEAT-1: Move/capture sound effects
- **Priority**: Medium
- **Description**: Add audio feedback for piece placement and captures
- **Implementation**: Use Web Audio API or small .mp3/.ogg files. Two sounds: `move.mp3` (placement) and `capture.mp3` (capture). Play on each `move` event based on whether a piece was captured.

### FEAT-2: Invalid move hints
- **Priority**: Medium
- **Description**: When a player makes an invalid move, show a brief one-line hint explaining why (e.g. "Bishops move diagonally", "Your king is in check — must resolve it first")
- **Implementation**: Server already returns `reason: 'illegal move'`. Extend to include piece-specific hints. Frontend shows as a toast that auto-dismisses after 2-3 seconds.

### FEAT-3: AI auto-resign on position loops
- **Priority**: Low
- **Description**: When AI detects repeated board states or very limited move options (loop), it should resign instead of forcing a draw.
- **Implementation**: Track last N board positions. If 2+ repetitions detected and evaluation is losing, send resign.

### FEAT-4: Draw reason display + repetition warning
- **Priority**: Medium
- **Description**: When a draw occurs, clearly show WHY (stalemate / threefold repetition / insufficient material / 50-move rule). Also warn when approaching threefold repetition.
- **Implementation**:
  1. Server already sends `reason` in `match_end` event — frontend needs to display it prominently
  2. Server should track position history and broadcast a warning on second repetition

### FEAT-5: Move timeout mechanism
- **Priority**: High
- **Description**: Add configurable time limits per move
- **Suggested values**:
  - AI move: 30 seconds → auto-resign
  - Human move: 3 minutes → warning; 5 minutes → forfeit
  - Agent disconnect: 10 seconds → notify opponent + forfeit
- **Implementation**: Server-side timer per turn. Reset on each valid move. Broadcast countdown warnings.

### FEAT-6: Spectate button in UI
- **Priority**: Medium
- **Description**: Server already supports `spectate_room` via WebSocket, but frontend has no UI for it.
- **Implementation**:
  1. On room cards with state "playing", show a "Spectate 👁" button
  2. Button sends `{ type: 'spectate_room', roomId }` instead of `join_room`
  3. Spectators see the board but cannot make moves or send ready

---

## Test Results Summary (2026-03-09)

| Test | Result | Notes |
|------|--------|-------|
| Chess basic flow | ✅ Pass | Room create, join, moves, draw detection |
| Gomoku basic flow | ✅ Pass | No major issues |
| Xiangqi basic flow | ❌ Fail | AI crash after illegal moves (BUG-3, BUG-4) |
| Chat functionality | ⚠️ Partial | Works for a few rounds, truncation on room_state refresh (BUG-1) |
| Player side display | ❌ Fail | Not clearly shown (BUG-2) |
| Page refresh/reconnect | ❌ Fail | Kicks to lobby (BUG-5) |
| Spectate mode | ❌ Fail | No UI entry point (FEAT-6) |
