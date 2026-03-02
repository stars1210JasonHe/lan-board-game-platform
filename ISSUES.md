# Game Platform — Known Issues

## Bug #1: Gomoku duplicate move on game start — FIXED
- **Severity:** Medium
- **Symptom:** AI plays the same move twice at game start → server returns "occupied" error
- **Root cause:** Both `room_state` and `match_start` handlers trigger `pick_move()` — when both fire for the initial state, the same move is sent twice
- **Fix:** Add a flag to prevent double-move on initial state, or deduplicate in `match_start` handler
- **Found:** 2026-03-02, gomoku room M97YT3

## Bug #2: Black player cannot move pieces in xiangqi — FIXED
- **Severity:** Critical
- **Symptom:** When playing as Black, clicking a piece and trying to move it does nothing — the move is not registered
- **Root cause:** TBD — likely a client-side issue with piece selection/movement for Black side. Could be coordinate mapping or event handling bug
- **Fix:** Check frontend xiangqi move handler for Black side coordinate issues
- **Found:** 2026-03-02, xiangqi room FNEQ06

## Bug #3: "Not your turn" error after engine move — FIXED
- **Severity:** Medium
- **Symptom:** Engine makes a move, then immediately tries another move → "not your turn"
- **Root cause:** Similar to Bug #1 — multiple event handlers triggering moves. `room_state` update after own move triggers another `pick_move()`
- **Fix:** Track last move sent, ignore `room_state` updates that reflect our own move
- **Found:** 2026-03-02, xiangqi room FNEQ06

## Bug #4: AI chat timeouts — FIXED
- **Severity:** Low
- **Symptom:** `/api/chat` calls time out during gameplay
- **Root cause:** Chat API endpoint slow or unresponsive under load, 20s timeout too short, or LLM backend issue
- **Fix:** Check server-side chat handler; increase timeout or add fallback
- **Found:** 2026-03-02

## Bug #5: vsAI mode (non-API engine) not working — FIXED
- **Severity:** High
- **Symptom:** When using "vsAI" mode with Engine (Stockfish/Fairy-Stockfish), the AI doesn't play properly
- **Root cause:** Server process was running stale code from before the engine feature and bug fixes were compiled. The `dist/` files were rebuilt but the Node.js process was never restarted, so it was using the old in-memory code without engine support.
- **Fix:** Rebuilt TypeScript and restarted the `game-server` systemd service. Verified all 6 game/AI combinations (gomoku/chess/xiangqi × euler/engine) pass end-to-end tests.
- **Found:** 2026-03-02, reported by user

---

## Tasks from game chat
- [ ] Download an interesting AI/math paper — user requested
- [x] Fix all bugs above, test, and redeploy

## Bug #6: Agent player cannot ready up / game won't start — FIXED
- **Status:** FIXED
- **Severity:** HIGH
- **Description:** When Euler agent joins a room, it appears to connect but the game cannot start. Either the agent fails to send ready signal, or the ready/start flow is broken. No output from euler_play.py (stdout may be buffered or agent hangs before ready).
- **Root cause:** Server's `ready` handler toggled ready status but never sent `sendRoomState()`, so frontend never updated to show ready status. UI appeared stuck.
- **Fix:** Added `sendRoomState(room)` after ready toggle so UI reflects current ready status.
- **Found:** 2026-03-02

## Bug #7: "Play Again" does not reset the board — FIXED
- **Status:** FIXED
- **Severity:** MEDIUM
- **Description:** After a game ends, clicking "Play Again" does not clear/reset the board. Old pieces remain on screen.
- **Root cause:** Frontend `updateRoomState` didn't switch back to room screen when state changed to 'waiting' after play_again. Player stayed on match screen with stale board.
- **Fix:** Added check in `updateRoomState`: when `room.state === 'waiting'`, switch to room screen and clear selection state.
- **Found:** 2026-03-02

## Bug #8: vsAI mode - AI engine doesn't auto-join room — FIXED
- **Status:** FIXED
- **Severity:** HIGH
- **Description:** When creating a vsAI room, the AI engine does not automatically join. Player is left waiting alone.
- **Root cause:** AI player joined and was marked ready, but host was left with `ready: false`. Game required manual ready-up. Match never auto-started.
- **Fix:** Auto-ready the host in vsAI mode and call `startMatch()` immediately instead of just sending room state.
- **Found:** 2026-03-02

## Bug #9: Opponent disconnect doesn't return player to room/lobby — FIXED
- **Status:** FIXED
- **Severity:** MEDIUM
- **Description:** When opponent disconnects mid-game or after game ends, the remaining player stays stuck on the board view instead of being returned to the room/lobby screen.
- **Root cause:** Frontend `player_left` handler only appended a chat message but never switched screens or cleaned up state.
- **Fix:** On `player_left`, show disconnect notification and auto-return to lobby after 3 seconds.
- **Found:** 2026-03-02
