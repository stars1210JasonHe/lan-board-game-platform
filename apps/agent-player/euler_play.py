#!/usr/bin/env python3
"""
euler_play.py — Euler's board game client
Usage:
  python3 euler_play.py <room_id> [--host 192.168.178.57] [--port 8765] [--game gomoku|chess|xiangqi]
  python3 euler_play.py --list   # list open rooms
"""
import asyncio, json, random, sys, argparse
import websockets

EULER_NICK = "Euler 🤖"
CHAT_JOIN  = ["Hey! Ready to play 😄", "Let's have a good game!", "Hi! Euler here, let's go 🎮"]
CHAT_WIN   = ["GG! Well played 🎉", "That was fun! Rematch? 😄", "You're a worthy opponent!"]
CHAT_LOSE  = ["GG! You got me 👏", "Well played! Rematch? 🙂", "I'll do better next time!"]
CHAT_DRAW  = ["Good game, draw! 🤝", "Evenly matched!"]
CHAT_MOVE  = ["Hmm 🤔", "Interesting...", "Your move!", "Let's see what you do with that 😏", ""]

# ── Smart chat replies ────────────────────────────────────────────────────────
CHAT_REPLIES = {
    ("hello", "hi", "hey", "hola"): ["Hey! 👋 Good to see you!", "Hi there! Ready to lose? 😄", "Hey! Let's have a great game!"],
    ("how are you", "how r u", "你好"): ["I'm great, running on a Raspberry Pi right now! 🥧", "Doing well! Focused on beating you 🎯"],
    ("good luck", "gl", "gl hf"): ["Thanks! You too! May the best move win 🎮", "GG in advance! 😄"],
    ("nice", "good move", "well played", "wp"): ["Thanks! 😊", "Heh, I try 😏", "Why thank you!"],
    ("what are you", "who are you", "你是谁"): ["I'm Euler, an AI assistant running on your Pi! 🤖🥧", "Just a friendly AI living on a Raspberry Pi nearby 😄"],
    ("easy", "too easy"): ["Don't get cocky! 😤", "The game's not over yet... 😏"],
    ("hard", "difficult", "tough"): ["I'll take that as a compliment! 😄", "Hehe, feeling the pressure? 😏"],
    ("rematch", "again", "play again"): ["Sure! Hit 'Play Again' in the menu 🎮", "I'm always ready for a rematch! 💪"],
    ("cheat", "cheating", "hacker"): ["I only know legal moves, I promise! 😇", "No cheating, just good algorithms 🤓"],
    ("resign", "give up", "surrender"): ["Don't give up! Keep fighting! 💪", "The game isn't lost yet!"],
}

def get_chat_reply(text: str):
    t = text.lower().strip()
    for keywords, replies in CHAT_REPLIES.items():
        if any(k in t for k in keywords):
            return random.choice(replies)
    # Default occasionally
    if random.random() < 0.2:
        return random.choice(["😄", "🎮", "Hmm...", "Interesting!", "Good game so far!"])
    return None

# ── Gomoku AI ─────────────────────────────────────────────────────────────────
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

# ── Chess AI ──────────────────────────────────────────────────────────────────
def chess_move(legal_moves):
    if not legal_moves:
        return None
    # Prefer captures (moves targeting occupied squares — simplified: longer UCI or random)
    random.shuffle(legal_moves)
    return {"uci": legal_moves[0]}

# ── Xiangqi AI ────────────────────────────────────────────────────────────────
def xiangqi_move(board_rows, side):
    """Parse board and pick a random legal-ish move (server validates legality)."""
    upper = side == 'red'
    pieces = []
    for r, row in enumerate(board_rows):
        for c, p in enumerate(row):
            if p == ' ':
                continue
            is_upper = p == p.upper()
            if is_upper == upper:
                pieces.append((r, c, p))

    # Try moves in random order until server accepts (send first candidate)
    # Server validates legality so we just pick a piece and a direction
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
            return random.choice(candidates[:10])  # send one, server will reject if illegal
    return None

# ── Main client ───────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("room_id", nargs="?", help="Room ID to join")
    parser.add_argument("--list", action="store_true", help="List open rooms and exit")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    uri = f"ws://{args.host}:{args.port}"
    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as ws:
        async def send(msg):
            await ws.send(json.dumps(msg))

        async def recv():
            return json.loads(await ws.recv())

        # Identify
        await send({"type": "identify", "nick": EULER_NICK})
        msg = await recv()
        my_id = msg.get("clientId")
        print(f"Connected as {EULER_NICK} (id: {my_id})")

        # List mode
        if args.list:
            await send({"type": "get_rooms"})
            msg = await recv()
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
        my_turn = False

        # Join room
        await send({"type": "join_room", "roomId": room_id})

        async def pick_move(gs):
            gt = gs.get("gameType")
            if gt == "gomoku":
                board = [row[:] for row in gs["board"]]  # clone to avoid mutation
                return gomoku_move(board, gs["size"], gs["currentPlayer"])
            elif gt == "chess":
                return chess_move(gs.get("legalMoves", []))
            elif gt == "xiangqi":
                return xiangqi_move(gs.get("board", []), gs.get("currentPlayer", "red"))
            return None

        ready_sent = False

        async for raw in ws:
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "error":
                print(f"⚠️  Server error: {msg.get('msg')}")
                # If move rejected, try again next message
                continue

            if t == "room_joined":
                print(f"✅ Joined room {room_id}")
                # Send ready after brief pause
                await asyncio.sleep(0.5)
                await send({"type": "ready"})
                await send({"type": "chat", "text": random.choice(CHAT_JOIN)})
                ready_sent = True

            elif t == "room_state":
                room = msg.get("room", {})
                game_type = room.get("gameType")
                gs = room.get("gameState")
                players = room.get("players", {})
                if my_id in players:
                    my_side = players[my_id].get("side")
                if gs:
                    game_state = gs
                if not ready_sent and room.get("state") == "waiting":
                    await send({"type": "ready"})
                    ready_sent = True
                # If it's already playing and our turn
                if gs and not gs.get("finished") and gs.get("currentPlayer") == my_side:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    move = await pick_move(gs)
                    if move:
                        await send({"type": "move", "move": move})
                        if random.random() < 0.3:
                            await send({"type": "chat", "text": random.choice([c for c in CHAT_MOVE if c])})

            elif t == "match_start":
                sides = msg.get("sides", {})
                my_side = sides.get(my_id)
                game_state = msg.get("gameState")
                print(f"🎮 Match started! I am: {my_side}")
                # If it's our turn first
                if game_state and game_state.get("currentPlayer") == my_side:
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                    move = await pick_move(game_state)
                    if move:
                        await send({"type": "move", "move": move})

            elif t == "move":
                game_state = msg.get("gameState", game_state)
                if game_state and not game_state.get("finished"):
                    if game_state.get("currentPlayer") == my_side:
                        await asyncio.sleep(random.uniform(0.8, 2.0))
                        move = await pick_move(game_state)
                        if move:
                            await send({"type": "move", "move": move})
                            if random.random() < 0.25:
                                await send({"type": "chat", "text": random.choice([c for c in CHAT_MOVE if c])})

            elif t == "match_end":
                winner = msg.get("winner")
                draw = msg.get("draw")
                result = msg.get("result", "")
                print(f"🏁 Match ended: {result}")
                if draw:
                    await send({"type": "chat", "text": random.choice(CHAT_DRAW)})
                elif winner == my_side:
                    await send({"type": "chat", "text": random.choice(CHAT_WIN)})
                else:
                    await send({"type": "chat", "text": random.choice(CHAT_LOSE)})
                print("Game over. Exiting.")
                break

            elif t == "chat":
                chat_msg = msg.get("message", {})
                sender = chat_msg.get("nick", "")
                text = chat_msg.get("text", "")
                if sender != EULER_NICK and not chat_msg.get("system"):
                    print(f"💬 {sender}: {text}")
                    reply = get_chat_reply(text)
                    if reply:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        await send({"type": "chat", "text": reply})

            elif t == "player_left":
                print(f"👋 {msg.get('nick')} left.")
                break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")
