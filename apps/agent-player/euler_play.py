#!/usr/bin/env python3
"""
euler_play.py — Euler's board game client (AI-powered via game server API)

Architecture:
  - Game moves: tries server API (/api/move) first, falls back to local algorithm
  - In-game chat: routed via server API (/api/chat)
  - Local algorithms: gomoku/chess/xiangqi always available as fallback

Usage:
  python3 euler_play.py <room_id> [--host 192.168.178.57] [--port 8765]
  python3 euler_play.py --list   # list open rooms
"""
import asyncio, json, random, sys, argparse, re
from urllib.request import urlopen, Request
from urllib.error import URLError
import websockets

EULER_NICK = "Euler 🤖"


# ── HTTP API helpers ──────────────────────────────────────────────────────────

def api_post(base_url: str, endpoint: str, data: dict, timeout: float = 35) -> dict | None:
    """POST JSON to server API, return parsed response or None on failure."""
    url = f"{base_url}{endpoint}"
    body = json.dumps(data).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (URLError, TimeoutError, json.JSONDecodeError, Exception) as e:
        print(f"⚠️ API {endpoint} error: {e}")
        return None


async def api_move(base_url: str, game_state: dict, side: str) -> dict | None:
    """Request an AI move from the server API."""
    data = {
        "board": game_state.get("board", []),
        "size": game_state.get("size", 15),
        "currentPlayer": game_state.get("currentPlayer"),
        "currentPlayerName": game_state.get("currentPlayerName"),
        "moveCount": game_state.get("moveCount", 0),
        "gameType": game_state.get("gameType", "gomoku"),
        "side": side,
    }
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: api_post(base_url, "/api/move", data)
    )
    if result and "row" in result and "col" in result:
        print(f"🧠 AI chose: ({result['row']}, {result['col']})")
        return {"row": result["row"], "col": result["col"]}
    if result and "error" in result:
        print(f"⚠️ AI move: {result['error']}")
    return None


async def api_chat(base_url: str, text: str, game_context: str = "", game_type: str = "") -> str | None:
    """Request a chat reply from the server API."""
    data = {"text": text}
    if game_context:
        data["gameContext"] = game_context
    if game_type:
        data["gameType"] = game_type
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: api_post(base_url, "/api/chat", data, timeout=20)
    )
    if result and result.get("reply"):
        return result["reply"]
    return None


# ── Board summary ─────────────────────────────────────────────────────────────

def board_summary(game_state: dict) -> str:
    """Create a brief board summary for context."""
    if not game_state:
        return ""
    parts = []
    gt = game_state.get("gameType", "")
    if gt:
        parts.append(f"game={gt}")
    cp = game_state.get("currentPlayer")
    if cp:
        parts.append(f"current_turn={cp}")
    mc = game_state.get("moveCount", 0)
    if mc:
        parts.append(f"moves={mc}")
    finished = game_state.get("finished")
    if finished:
        parts.append("FINISHED")
    return ", ".join(parts)


# ── Gomoku AI (local fallback) ────────────────────────────────────────────────

def gomoku_move(board, size, player):
    opp = 2 if player == 1 else 1
    empties = [(r, c) for r in range(size) for c in range(size) if board[r][c] == 0]
    if not empties:
        return None

    def score(r, c, p):
        dirs = [(0,1),(1,0),(1,1),(1,-1)]
        best = 0
        for dr, dc in dirs:
            count = 1
            for s in (1, -1):
                nr, nc = r+s*dr, c+s*dc
                while 0<=nr<size and 0<=nc<size and board[nr][nc] == p:
                    count += 1; nr += s*dr; nc += s*dc
            best = max(best, count)
        return best

    # Win move
    for r, c in empties:
        board[r][c] = player
        if score(r, c, player) >= 5:
            board[r][c] = 0
            return {"row": r, "col": c}
        board[r][c] = 0

    # Block opponent win
    for r, c in empties:
        board[r][c] = opp
        if score(r, c, opp) >= 5:
            board[r][c] = 0
            return {"row": r, "col": c}
        board[r][c] = 0

    # Score-based best
    best_score, best_move = -1, None
    for r, c in empties:
        board[r][c] = player
        s1 = score(r, c, player)
        board[r][c] = opp
        s2 = score(r, c, opp)
        board[r][c] = 0
        s = s1 * 2 + s2
        center = size // 2
        s -= (abs(r-center) + abs(c-center)) * 0.1
        if s > best_score:
            best_score, best_move = s, (r, c)

    if best_move:
        return {"row": best_move[0], "col": best_move[1]}
    return {"row": empties[0][0], "col": empties[0][1]}


# ── Chess AI (local fallback) ─────────────────────────────────────────────────

def chess_move(legal_moves):
    if not legal_moves:
        return None
    random.shuffle(legal_moves)
    return {"uci": legal_moves[0]}


# ── Xiangqi AI (local fallback) ───────────────────────────────────────────────

def xiangqi_move(board_rows, side):
    upper = side == 'red'
    pieces = []
    for r, row in enumerate(board_rows):
        for c, p in enumerate(row):
            if p == ' ':
                continue
            is_upper = p == p.upper()
            if is_upper == upper:
                pieces.append((r, c, p))

    random.shuffle(pieces)
    for r, c, p in pieces:
        candidates = []
        for dr in range(-9, 10):
            for dc in range(-8, 9):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r+dr, c+dc
                if 0 <= nr <= 9 and 0 <= nc <= 8:
                    candidates.append({"fromRow": r, "fromCol": c, "toRow": nr, "toCol": nc})
        if candidates:
            return random.choice(candidates[:10])
    return None


# ── Main client ───────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("room_id", nargs="?", help="Room ID to join")
    parser.add_argument("--list", action="store_true", help="List open rooms and exit")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-ai-chat", action="store_true",
                        help="Disable AI chat, use canned replies (fallback)")
    args = parser.parse_args()

    ai_chat = not args.no_ai_chat
    base_url = f"http://{args.host}:{args.port}"
    ws_uri = f"ws://{args.host}:{args.port}"
    print(f"Connecting to {ws_uri}...")
    if ai_chat:
        print("🧠 AI chat enabled (via server API)")
    else:
        print("💬 Using canned chat replies (--no-ai-chat)")

    # Fallback canned replies (used when --no-ai-chat or API fails)
    CANNED = {
        "join": ["Hey! Ready to play 😄", "Let's have a good game!", "Hi! Euler here 🎮"],
        "win": ["GG! Well played 🎉", "That was fun! Rematch? 😄"],
        "lose": ["GG! You got me 👏", "Well played! Rematch? 🙂"],
        "draw": ["Good game, draw! 🤝", "Evenly matched!"],
        "move": ["Hmm 🤔", "Interesting...", "Your move!", ""],
    }

    async def chat_reply(text: str, context: str = "", gt: str = "") -> str | None:
        if ai_chat:
            reply = await api_chat(base_url, text, context, gt)
            if reply:
                return reply
        # Fallback to simple keyword match
        t = text.lower().strip()
        if any(k in t for k in ("hi", "hello", "hey")):
            return random.choice(["Hey! 👋", "Hi! Let's play! 😄"])
        if any(k in t for k in ("gg", "good game", "well played")):
            return random.choice(["GG! 🤝", "Thanks! Good game!"])
        if random.random() < 0.2:
            return random.choice(["😄", "🎮", "Hmm..."])
        return None

    async def event_reply(text: str, fallback_key: str, context: str = "", gt: str = "") -> str:
        if ai_chat:
            reply = await api_chat(base_url, text, context, gt)
            if reply:
                return reply
        return random.choice(CANNED.get(fallback_key, ["😄"]))

    async with websockets.connect(ws_uri) as ws:
        async def send_ws(msg):
            await ws.send(json.dumps(msg))

        async def recv_ws():
            return json.loads(await ws.recv())

        # Identify
        await send_ws({"type": "identify", "nick": EULER_NICK})
        msg = await recv_ws()
        my_id = msg.get("clientId")
        print(f"Connected as {EULER_NICK} (id: {my_id})")

        # List mode
        if args.list:
            await send_ws({"type": "get_rooms"})
            msg = await recv_ws()
            rooms = msg.get("rooms", [])
            if not rooms:
                print("No open rooms.")
            else:
                print(f"\n{'ID':<10} {'Game':<10} {'Players':<10} State")
                print("-" * 45)
                for r in rooms:
                    players = ", ".join(p["nick"] for p in r.get("players", []))
                    print(f"{r['id']:<10} {r['gameType']:<10} {players:<25} {r['state']}")
            return

        if not args.room_id:
            print("Error: provide a room_id or use --list")
            sys.exit(1)

        room_id = args.room_id.upper()
        my_side = None
        game_type = None
        game_state = None
        opponent_nick = "opponent"

        # Join room
        await send_ws({"type": "join_room", "roomId": room_id})

        async def pick_move(gs):
            gt = gs.get("gameType")
            if gt == "gomoku":
                if ai_chat:
                    ai_result = await api_move(base_url, gs, my_side)
                    if ai_result:
                        return ai_result
                    print("⚠️ AI move failed, falling back to algorithm")
                # Fallback to static algorithm
                board = [row[:] for row in gs["board"]]
                return gomoku_move(board, gs["size"], gs["currentPlayer"])
            elif gt == "chess":
                return chess_move(gs.get("legalMoves", []))
            elif gt == "xiangqi":
                return xiangqi_move(gs.get("board", []), gs.get("currentPlayer", "red"))
            return None

        def is_my_turn(gs):
            """Check if it's our turn (handles number vs string comparison)."""
            if not gs or gs.get("finished"):
                return False
            cur = gs.get("currentPlayer")
            cur_name = gs.get("currentPlayerName", cur)
            return cur == my_side or cur_name == my_side

        ready_sent = False

        async for raw in ws:
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "error":
                print(f"⚠️  Server error: {msg.get('msg')}")
                continue

            if t == "room_joined":
                print(f"✅ Joined room {room_id}")
                await asyncio.sleep(0.5)
                await send_ws({"type": "ready"})
                ready_sent = True

                # Send a greeting
                greeting = await event_reply(
                    "Just joined the game room, say hi!",
                    "join", "", game_type or ""
                )
                await send_ws({"type": "chat", "text": greeting})

            elif t == "room_state":
                room = msg.get("room", {})
                game_type = room.get("gameType")
                gs = room.get("gameState")
                players = room.get("players", {})
                if my_id in players:
                    my_side = players[my_id].get("side")
                # Find opponent nick
                for pid, pinfo in players.items():
                    if pid != my_id:
                        opponent_nick = pinfo.get("nick", "opponent")
                if gs:
                    game_state = gs
                if not ready_sent and room.get("state") == "waiting":
                    await send_ws({"type": "ready"})
                    ready_sent = True
                if gs and not gs.get("finished") and is_my_turn(gs):
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    move = await pick_move(gs)
                    if move:
                        await send_ws({"type": "move", "move": move})

            elif t == "match_start":
                sides = msg.get("sides", {})
                my_side = sides.get(my_id)
                game_state = msg.get("gameState")
                print(f"🎮 Match started! I am: {my_side}")

                if game_state and is_my_turn(game_state):
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                    move = await pick_move(game_state)
                    if move:
                        await send_ws({"type": "move", "move": move})

            elif t == "move":
                game_state = msg.get("gameState", game_state)
                if game_state and not game_state.get("finished"):
                    if is_my_turn(game_state):
                        await asyncio.sleep(random.uniform(0.8, 2.0))
                        move = await pick_move(game_state)
                        if move:
                            await send_ws({"type": "move", "move": move})
                            # Occasionally comment on our own move
                            if random.random() < 0.25:
                                ctx = board_summary(game_state)
                                comment = await event_reply(
                                    "I just made a move, react briefly",
                                    "move", ctx, game_type or ""
                                )
                                if comment:
                                    await send_ws({"type": "chat", "text": comment})

            elif t == "match_end":
                winner = msg.get("winner")
                draw = msg.get("draw")
                result = msg.get("result", "")
                ctx = board_summary(game_state) if game_state else ""
                print(f"🏁 Match ended: {result}")

                if draw:
                    reply = await event_reply("Game ended in a draw", "draw", ctx, game_type or "")
                elif winner == my_side:
                    reply = await event_reply("I won the game!", "win", ctx, game_type or "")
                else:
                    reply = await event_reply("I lost the game", "lose", ctx, game_type or "")
                await send_ws({"type": "chat", "text": reply})
                print("Game over. Exiting.")
                break

            elif t == "chat":
                chat_msg = msg.get("message", {})
                sender = chat_msg.get("nick", "")
                text = chat_msg.get("text", "")
                if sender != EULER_NICK and not chat_msg.get("system"):
                    print(f"💬 {sender}: {text}")
                    ctx = board_summary(game_state) if game_state else ""
                    reply = await chat_reply(text, ctx, game_type or "")
                    if reply:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        await send_ws({"type": "chat", "text": reply})

            elif t == "player_left":
                print(f"👋 {msg.get('nick')} left.")
                break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")
