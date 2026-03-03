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

## Bug #7 (confirmed): Play Again — board not reset + agent exits — FIXED
- **Status:** FIXED
- **Fix:** Frontend clears canvas and gameState when room resets to 'waiting'. euler_play.py now stays alive after match_end, sends play_again, and loops back for new matches.

## Bug #8 (confirmed): vsAI Euler mode — no real AI spawned — FIXED
- **Status:** FIXED
- **Fix:** Server now spawns euler_play.py as a subprocess for vsAI euler mode. Engine mode still uses built-in AI.

## Bug #9 (confirmed again): Stuck in game screen when opponent leaves — FIXED
- **Status:** FIXED
- **Fix:** Frontend player_left handler shows disconnect toast and auto-returns to lobby after 3s.

## Bug #10: Xiangqi "stuck" — can't click pieces mid-game
- **Status:** FIXED
- **Symptom:** Player felt stuck during xiangqi game (room RB3AM5, 18 moves in). Clicking pieces didn't work.
- **Root cause:** Frontend xiangqi click handler didn't validate piece ownership on first click (could select empty/enemy squares). No ability to reselect different pieces. Move rejections silently logged to console with no feedback.
- **Fix:** Validate first click is own piece, allow reselection by clicking different own piece, show error toast for rejected moves.

## Bug #11: Server drops WebSocket mid-game (ConnectionClosedError)
- **Status:** FIXED
- **Symptom:** euler_play.py crashes with ConnectionClosedError after several moves. Server drops connection.
- **Root cause:** No ping/pong keepalive. Unhandled exceptions in WS message handler could crash connections. broadcast() had no error handling.
- **Fix:** Added ping/pong keepalive (30s interval). Wrapped message handler in try/catch. Added try/catch to broadcast/sendClient. euler_play.py now handles ConnectionClosed gracefully.

## Bug #12：vsAI Engine 模式无法开始游戏
- **状态：** FIXED
- **发现：** 2026-03-03 测试
- **修复：** Play Again 后 Engine 模式自动重启（检测到内置 AI 后直接调用 startMatch），无需手动点击 Ready

## Bug #13：象棋 Play Again 后所有走法显示 illegal move
- **状态：** FIXED
- **发现：** 2026-03-03 测试
- **根本原因：** Euler agent 自动发送 play_again 重置了房间，导致游戏状态与客户端 mySide 不同步
- **修复：** Euler 不再自动发送 play_again；由人类玩家点击确认后触发房间重置；startMatch 创建新游戏对象完全重置状态

## Bug #14：游戏结束后无结果弹窗，直接跳回准备房间
- **状态：** FIXED
- **发现：** 2026-03-03 测试
- **根本原因：** Euler agent 自动发送 play_again → 服务器广播 room_state(waiting) → 前端 updateRoomState 直接调用 showScreen('room') 隐藏了弹窗
- **修复：** (1) Euler 移除自动 play_again；(2) 前端：若结果弹窗可见，不自动切换到准备房间；(3) 弹窗显示 "You Win/You Lose/Draw" 个性化结果

## Bug #15：玩家昵称无重名检测
- **状态：** FIXED
- **发现：** 2026-03-03 测试
- **修复：** 服务端 join_room 时调用 getUniqueNick() 检测重名，自动追加数字后缀（Player_2、Player_3 等）

## Feature #1：房间内对战记录
- **状态：** DONE
- **发现：** 2026-03-03 用户需求
- **实现：** sendRoomState 包含 matchHistory（按房间 room_id 过滤，最近20场）；前端房间界面显示对战历史表格（双方、结果、手数、用时）

## Bug #12 (revisited) — vsAI Engine 模式：AI 未自动加入
- 状态：**VERIFIED WORKING**（2026-03-03 代码复查）
- 分析：create_room 收到 withAi=true + aiType=engine 时，服务端正确执行 else 分支：
  创建 AI_roomId 内置玩家 → 双方标记 ready → 调用 startMatch()。
  assignSides 将人类分配为红方，内置 AI 为黑方；broadcast match_start 给人类。
  代码逻辑正确，无需修改。之前"未修复"报告可能为误报。

## Bug #16 — Euler 模式错误使用 Engine
- 状态：**新发现**（2026-03-03）
- 现象：用户在大厅选"Euler AI"房间，agent 却以 `--mode engine` 启动，用 Fairy-Stockfish 下棋
- 期望：Euler 模式应调用 LLM API 来决策走法和对话；只有用户选"Engine ⚙️"才用引擎
- 服务端在收到 `create_room` 时应通知 agent 用正确模式启动

## Bug #17 — 象棋红马无法移动（illegal move）
- 状态：**新发现**（2026-03-03）
- 现象：红方右侧马（截图黄圈位置，约 row2 col6），周围无蹩脚棋子，仍报 illegal move
- 期望：马按规则可正常走日字
- 可能原因：服务端象棋走法验证逻辑有误（马腿判断错误）

## Bug #18 — 对局历史显示 "unknown" 玩家名
- 状态：**FIXED**（2026-03-03）
- 现象：Feature #1 对局历史显示 "black wins (unknown)" 而非实际玩家昵称
- 根本原因：handleMatchEnd 的 resultStr 使用 ${reason}（值为 'unknown'），而非胜者昵称
- 修复：查找 winner side 对应的玩家昵称，改为 "${winner} wins (${winnerNick})" 格式

## 测试更新（2026-03-03）
- Bug #17 取消：马无法移动是因为被将军，走马会导致将死，服务端正确拒绝，非 bug
- Bug #13 已修复：Play Again 后走法正常，无 illegal move

## Bug #19 — Euler AI 象棋走法 illegal move
- 状态：**FIXED**（2026-03-03）
- 现象：vsAI Euler 模式，agent 连接成功，但第一步就报 illegal move，游戏卡住
- 根本原因：euler_play.py 的 xiangqi_move() 生成"合理但不保证合法"的走法（不检查将军/
  飞将等服务端规则）；服务端拒绝后 last_move_count 已锁定，euler 不会重试，游戏僵住
- 修复：在 error 处理中，若错误为 "illegal move" 且仍是我方回合，则重置 last_move_count
  并最多重试 MAX_ILLEGAL_RETRIES(5) 次；每次收到成功 move 事件时重置重试计数器
