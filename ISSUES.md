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
