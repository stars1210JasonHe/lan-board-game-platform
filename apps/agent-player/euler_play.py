#!/usr/bin/env python3
"""
euler_play.py — Euler's board game client (AI-powered via game server API)

Architecture:
  - Two AI modes: "euler" (LLM via /api/move) and "engine" (Stockfish/Fairy-Stockfish)
  - In-game chat: routed via server API (/api/chat) in both modes
  - In-game commands: /engine [difficulty] to switch to engine, /euler to switch to LLM
  - Difficulty levels: beginner, easy, medium, hard, max (engine Skill Level)
  - Local algorithms: gomoku (minimax) / chess / xiangqi always available as fallback

Usage:
  python3 euler_play.py <room_id> [--host 192.168.178.57] [--port 8765]
  python3 euler_play.py <room_id> --mode engine --difficulty hard
  python3 euler_play.py --list   # list open rooms
"""
import asyncio, json, random, sys, argparse, re, subprocess
from urllib.request import urlopen, Request
from urllib.error import URLError
import websockets

EULER_NICK = "Euler 🤖"

# ── Engine config ─────────────────────────────────────────────────────────────

ENGINES = {
    'chess': '/usr/games/stockfish',
    'xiangqi': '/usr/games/fairy-stockfish',
}

DIFFICULTY_SKILL = {'beginner': 2, 'easy': 6, 'medium': 12, 'hard': 16, 'max': 20}
DIFFICULTY_TIME = {'beginner': 0.2, 'easy': 0.5, 'medium': 1.0, 'hard': 2.0, 'max': 3.0}
VALID_DIFFICULTIES = list(DIFFICULTY_SKILL.keys())


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


# ── Engine AI (Stockfish / Fairy-Stockfish) ──────────────────────────────────

def xiangqi_board_to_fen(board_rows, current_player):
    """Convert xiangqi board (array of row strings) to FEN for fairy-stockfish.
    Board has Red (uppercase) at row 0 (top), reversed to match standard FEN."""
    fen_rows = []
    # Reverse: our row 9 → FEN first row (rank 9 = Black back rank)
    for row_str in reversed(board_rows):
        fen_row = ''
        empty = 0
        for ch in row_str:
            if ch == ' ':
                empty += 1
            else:
                if empty > 0:
                    fen_row += str(empty)
                    empty = 0
                fen_row += ch
        if empty > 0:
            fen_row += str(empty)
        fen_rows.append(fen_row)
    color = 'w' if current_player == 'red' else 'b'
    return f"{'/'.join(fen_rows)} {color} - - 0 1"


def engine_chess_move(fen, difficulty='medium'):
    """Get a move from Stockfish for chess using python-chess."""
    import chess
    import chess.engine
    skill = DIFFICULTY_SKILL.get(difficulty, 12)
    time_limit = DIFFICULTY_TIME.get(difficulty, 1.0)
    engine = chess.engine.SimpleEngine.popen_uci(ENGINES['chess'])
    try:
        engine.configure({"Skill Level": skill})
        board = chess.Board(fen)
        result = engine.play(board, chess.engine.Limit(time=time_limit))
        return {"uci": result.move.uci()}
    finally:
        engine.quit()


def engine_xiangqi_move(board_rows, current_player, difficulty='medium'):
    """Get a move from Fairy-Stockfish for xiangqi."""
    skill = DIFFICULTY_SKILL.get(difficulty, 12)
    time_ms = int(DIFFICULTY_TIME.get(difficulty, 1.0) * 1000)
    fen = xiangqi_board_to_fen(board_rows, current_player)

    proc = subprocess.Popen(
        [ENGINES['xiangqi']],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True
    )
    try:
        commands = (
            f"uci\nsetoption name UCI_Variant value xiangqi\n"
            f"setoption name Skill Level value {skill}\nisready\n"
            f"position fen {fen}\ngo movetime {time_ms}\n"
        )
        proc.stdin.write(commands)
        proc.stdin.flush()

        import time
        deadline = time.monotonic() + (time_ms / 1000) + 10  # timeout buffer
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line == '':  # EOF — engine died
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith('bestmove'):
                uci_move = line.split()[1]
                # Fairy-stockfish xiangqi uses 1-indexed ranks (1-10), parse with regex
                m = re.match(r'^([a-i])(\d+)([a-i])(\d+)$', uci_move)
                if m:
                    from_col = ord(m.group(1)) - ord('a')
                    from_row = int(m.group(2)) - 1  # 1-indexed to 0-indexed
                    to_col = ord(m.group(3)) - ord('a')
                    to_row = int(m.group(4)) - 1
                    return {"fromRow": from_row, "fromCol": from_col,
                            "toRow": to_row, "toCol": to_col}
    finally:
        try:
            proc.stdin.write('quit\n')
            proc.stdin.flush()
        except Exception:
            pass
        proc.terminate()
    return None


# ── Gomoku AI (minimax with alpha-beta) ──────────────────────────────────────

def gomoku_move(board, size, player):
    """Minimax-based gomoku AI with alpha-beta pruning (depth 3).
    Detects open-fours, double-threes, and critical threats."""
    opp = 2 if player == 1 else 1
    DIRS = [(0, 1), (1, 0), (1, 1), (1, -1)]
    center = size // 2

    def check_win(r, c, p):
        for dr, dc in DIRS:
            count = 1
            for s in (1, -1):
                nr, nc = r + s * dr, c + s * dc
                while 0 <= nr < size and 0 <= nc < size and board[nr][nc] == p:
                    count += 1; nr += s * dr; nc += s * dc
            if count >= 5:
                return True
        return False

    def get_candidates():
        """Cells within 2 of existing stones."""
        cands = set()
        has_stone = False
        for r in range(size):
            for c in range(size):
                if board[r][c] != 0:
                    has_stone = True
                    for dr in range(-2, 3):
                        for dc in range(-2, 3):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == 0:
                                cands.add((nr, nc))
        if not has_stone:
            return [(center, center)]
        return list(cands)

    def line_score(r, c, p):
        """Score for placing p at (r,c): count patterns in all directions."""
        total = 0
        open_threes = 0
        for dr, dc in DIRS:
            count = 1
            open_ends = 0
            # Positive direction
            nr, nc = r + dr, c + dc
            while 0 <= nr < size and 0 <= nc < size and board[nr][nc] == p:
                count += 1; nr += dr; nc += dc
            if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == 0:
                open_ends += 1
            # Negative direction
            nr, nc = r - dr, c - dc
            while 0 <= nr < size and 0 <= nc < size and board[nr][nc] == p:
                count += 1; nr -= dr; nc -= dc
            if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == 0:
                open_ends += 1

            if count >= 5:
                total += 100000
            elif count == 4:
                total += 50000 if open_ends == 2 else (5000 if open_ends == 1 else 0)
            elif count == 3:
                if open_ends == 2:
                    total += 5000
                    open_threes += 1
                elif open_ends == 1:
                    total += 500
            elif count == 2:
                total += 200 if open_ends == 2 else (50 if open_ends == 1 else 0)
        # Double-three bonus
        if open_threes >= 2:
            total += 50000
        return total

    def heuristic_score(r, c):
        """Quick scoring for move ordering."""
        board[r][c] = player
        s1 = line_score(r, c, player)
        board[r][c] = opp
        s2 = line_score(r, c, opp)
        board[r][c] = 0
        return s1 + s2

    def evaluate():
        """Static evaluation scanning all stones."""
        score = 0
        for r in range(size):
            for c in range(size):
                p = board[r][c]
                if p == 0:
                    continue
                for dr, dc in DIRS:
                    # Only count in positive direction to avoid double-counting
                    nr, nc = r - dr, c - dc
                    if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == p:
                        continue  # Not the start of this line
                    count = 1
                    nr, nc = r + dr, c + dc
                    while 0 <= nr < size and 0 <= nc < size and board[nr][nc] == p:
                        count += 1; nr += dr; nc += dc
                    if count < 2:
                        continue
                    open_ends = 0
                    # Check end after the line
                    if 0 <= nr < size and 0 <= nc < size and board[nr][nc] == 0:
                        open_ends += 1
                    # Check end before the line
                    br, bc = r - dr, c - dc
                    if 0 <= br < size and 0 <= bc < size and board[br][bc] == 0:
                        open_ends += 1

                    val = 0
                    if count >= 5:
                        val = 100000
                    elif count == 4:
                        val = 50000 if open_ends >= 2 else (5000 if open_ends == 1 else 0)
                    elif count == 3:
                        val = 5000 if open_ends >= 2 else (500 if open_ends == 1 else 0)
                    elif count == 2:
                        val = 200 if open_ends >= 2 else (50 if open_ends == 1 else 0)
                    score += val if p == player else -val
        return score

    def minimax(depth, alpha, beta, is_max):
        cands = get_candidates()
        if not cands:
            return 0, None

        # Order candidates by heuristic (top 15)
        scored = sorted(cands, key=lambda m: -heuristic_score(m[0], m[1]))[:15]
        best_move = scored[0]

        if is_max:
            max_eval = -999999
            for r, c in scored:
                board[r][c] = player
                if check_win(r, c, player):
                    board[r][c] = 0
                    return 100000 + depth, (r, c)
                if depth <= 1:
                    val = evaluate()
                else:
                    val, _ = minimax(depth - 1, alpha, beta, False)
                board[r][c] = 0
                if val > max_eval:
                    max_eval = val
                    best_move = (r, c)
                alpha = max(alpha, val)
                if beta <= alpha:
                    break
            return max_eval, best_move
        else:
            min_eval = 999999
            for r, c in scored:
                board[r][c] = opp
                if check_win(r, c, opp):
                    board[r][c] = 0
                    return -100000 - depth, (r, c)
                if depth <= 1:
                    val = evaluate()
                else:
                    val, _ = minimax(depth - 1, alpha, beta, True)
                board[r][c] = 0
                if val < min_eval:
                    min_eval = val
                    best_move = (r, c)
                beta = min(beta, val)
                if beta <= alpha:
                    break
            return min_eval, best_move

    # Quick checks first: instant win or block
    empties = [(r, c) for r in range(size) for c in range(size) if board[r][c] == 0]
    if not empties:
        return None

    for r, c in empties:
        board[r][c] = player
        if check_win(r, c, player):
            board[r][c] = 0
            return {"row": r, "col": c}
        board[r][c] = 0

    for r, c in empties:
        board[r][c] = opp
        if check_win(r, c, opp):
            board[r][c] = 0
            return {"row": r, "col": c}
        board[r][c] = 0

    # Minimax search (depth 3)
    _, move = minimax(3, -999999, 999999, True)
    if move:
        return {"row": move[0], "col": move[1]}
    return {"row": center, "col": center}


# ── Chess AI (local fallback) ─────────────────────────────────────────────────

def chess_move(legal_moves):
    if not legal_moves:
        return None
    random.shuffle(legal_moves)
    return {"uci": legal_moves[0]}


# ── Xiangqi AI (local fallback) ───────────────────────────────────────────────

def xiangqi_move(board_rows, side):
    """Basic xiangqi move generator using simple piece movement rules.
    Generates plausible (not guaranteed legal) moves; server validates."""
    upper = side == 'red'
    board = [list(row) for row in board_rows]

    def in_bounds(r, c):
        return 0 <= r <= 9 and 0 <= c <= 8

    def is_enemy(r, c):
        p = board[r][c]
        if p == ' ':
            return False
        return (p == p.upper()) != upper

    def is_empty(r, c):
        return board[r][c] == ' '

    def can_target(r, c):
        return in_bounds(r, c) and (is_empty(r, c) or is_enemy(r, c))

    def piece_moves(r, c, p):
        t = p.upper()
        moves = []
        if t == 'K':
            palace_rows = range(0, 3) if upper else range(7, 10)
            for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
                nr, nc = r+dr, c+dc
                if in_bounds(nr, nc) and nr in palace_rows and 3 <= nc <= 5 and can_target(nr, nc):
                    moves.append((nr, nc))
        elif t == 'A':
            palace_rows = range(0, 3) if upper else range(7, 10)
            for dr, dc in [(1,1),(1,-1),(-1,1),(-1,-1)]:
                nr, nc = r+dr, c+dc
                if in_bounds(nr, nc) and nr in palace_rows and 3 <= nc <= 5 and can_target(nr, nc):
                    moves.append((nr, nc))
        elif t == 'B':
            home = range(0, 5) if upper else range(5, 10)
            for dr, dc in [(2,2),(2,-2),(-2,2),(-2,-2)]:
                nr, nc = r+dr, c+dc
                mr, mc = r+dr//2, c+dc//2
                if in_bounds(nr, nc) and nr in home and is_empty(mr, mc) and can_target(nr, nc):
                    moves.append((nr, nc))
        elif t == 'N':
            for dr, dc, br, bc in [(-1,0,-2,1),(-1,0,-2,-1),(1,0,2,1),(1,0,2,-1),(0,-1,1,-2),(0,-1,-1,-2),(0,1,1,2),(0,1,-1,2)]:
                sr, sc = r+dr, c+dc
                if in_bounds(sr, sc) and is_empty(sr, sc):
                    nr, nc = r+br, c+bc
                    if in_bounds(nr, nc) and can_target(nr, nc):
                        moves.append((nr, nc))
        elif t == 'R':
            for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
                nr, nc = r+dr, c+dc
                while in_bounds(nr, nc):
                    if is_empty(nr, nc):
                        moves.append((nr, nc))
                    else:
                        if is_enemy(nr, nc):
                            moves.append((nr, nc))
                        break
                    nr += dr; nc += dc
        elif t == 'C':
            for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
                nr, nc = r+dr, c+dc
                jumped = False
                while in_bounds(nr, nc):
                    if not jumped:
                        if is_empty(nr, nc):
                            moves.append((nr, nc))
                        else:
                            jumped = True
                    else:
                        if not is_empty(nr, nc):
                            if is_enemy(nr, nc):
                                moves.append((nr, nc))
                            break
                    nr += dr; nc += dc
        elif t == 'P':
            fwd = 1 if upper else -1
            crossed = r >= 5 if upper else r <= 4
            nr, nc = r+fwd, c
            if in_bounds(nr, nc) and can_target(nr, nc):
                moves.append((nr, nc))
            if crossed:
                for dc in [-1, 1]:
                    if in_bounds(r, c+dc) and can_target(r, c+dc):
                        moves.append((r, c+dc))
        return moves

    # Collect all moves, prefer captures
    all_moves = []
    captures = []
    pieces = []
    for r, row in enumerate(board):
        for c, p in enumerate(row):
            if p == ' ':
                continue
            if (p == p.upper()) == upper:
                pieces.append((r, c, p))

    for r, c, p in pieces:
        for nr, nc in piece_moves(r, c, p):
            move = {"fromRow": r, "fromCol": c, "toRow": nr, "toCol": nc}
            all_moves.append(move)
            if is_enemy(nr, nc):
                captures.append(move)

    if captures:
        return random.choice(captures)
    if all_moves:
        return random.choice(all_moves)
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
    parser.add_argument("--mode", choices=["euler", "engine"], default=None,
                        help="AI mode: euler (LLM) or engine (Stockfish/Fairy-Stockfish)")
    parser.add_argument("--difficulty", choices=VALID_DIFFICULTIES, default=None,
                        help="Engine difficulty level")
    args = parser.parse_args()

    ai_chat = not args.no_ai_chat
    base_url = f"http://{args.host}:{args.port}"
    ws_uri = f"ws://{args.host}:{args.port}"

    # AI mode state (can be changed in-game via commands)
    mode = args.mode or 'euler'
    difficulty = args.difficulty or 'medium'
    cli_mode_set = args.mode is not None  # True if user explicitly set mode via CLI

    print(f"Connecting to {ws_uri}...")
    print(f"🎯 Mode: {mode} | Difficulty: {difficulty}")
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
        last_move_count = -1  # track moveCount we last acted on to prevent duplicate moves

        # Join room
        await send_ws({"type": "join_room", "roomId": room_id})

        async def pick_move(gs):
            nonlocal mode, difficulty
            gt = gs.get("gameType")

            # Engine mode for chess/xiangqi
            if mode == 'engine' and gt in ('chess', 'xiangqi'):
                try:
                    if gt == 'chess':
                        fen = gs.get('fen')
                        legal = gs.get('legalMoves', [])
                        if fen:
                            result = await asyncio.get_event_loop().run_in_executor(
                                None, lambda: engine_chess_move(fen, difficulty)
                            )
                            if result and (not legal or result['uci'] in legal):
                                print(f"⚙️ Engine chose: {result}")
                                return result
                            elif result:
                                print(f"⚠️ Engine move {result} not in legal moves, falling back")
                    elif gt == 'xiangqi':
                        board_rows = gs.get('board', [])
                        cur = gs.get('currentPlayer', 'red')
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: engine_xiangqi_move(board_rows, cur, difficulty)
                        )
                        if result:
                            print(f"⚙️ Engine chose: {result}")
                            return result
                except Exception as e:
                    print(f"⚠️ Engine error: {e}, falling back")

            # Euler/LLM mode or fallback
            if gt == "gomoku":
                if ai_chat and mode == 'euler':
                    ai_result = await api_move(base_url, gs, my_side)
                    if ai_result:
                        return ai_result
                    print("⚠️ AI move failed, falling back to minimax")
                # Minimax algorithm
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

        async def try_move(gs):
            """Send a move if it's our turn and we haven't already acted on this moveCount."""
            nonlocal last_move_count
            mc = gs.get("moveCount", 0)
            if mc == last_move_count:
                return  # already sent a move for this state
            last_move_count = mc
            move = await pick_move(gs)
            if move:
                await send_ws({"type": "move", "move": move})
            return move

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
                # Read room AI config (if not explicitly set via CLI)
                if not cli_mode_set:
                    room_ai_type = room.get("aiType")
                    room_difficulty = room.get("difficulty")
                    if room_ai_type in ('euler', 'engine'):
                        mode = room_ai_type
                    if room_difficulty in VALID_DIFFICULTIES:
                        difficulty = room_difficulty
                    print(f"📋 Room config: mode={mode}, difficulty={difficulty}")
                if gs:
                    game_state = gs
                if not ready_sent and room.get("state") == "waiting":
                    await send_ws({"type": "ready"})
                    ready_sent = True
                if gs and not gs.get("finished") and is_my_turn(gs):
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    await try_move(gs)

            elif t == "match_start":
                sides = msg.get("sides", {})
                my_side = sides.get(my_id)
                game_state = msg.get("gameState")
                print(f"🎮 Match started! I am: {my_side} (mode={mode})")

                if game_state and is_my_turn(game_state):
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                    await try_move(game_state)

            elif t == "move":
                game_state = msg.get("gameState", game_state)
                if game_state and not game_state.get("finished"):
                    if is_my_turn(game_state):
                        await asyncio.sleep(random.uniform(0.8, 2.0))
                        move = await try_move(game_state)
                        if move:
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

                    # In-game commands
                    stripped = text.strip().lower()
                    if stripped.startswith('/engine'):
                        parts = stripped.split()
                        new_diff = parts[1] if len(parts) > 1 else difficulty
                        if new_diff not in VALID_DIFFICULTIES:
                            new_diff = 'medium'
                        mode = 'engine'
                        difficulty = new_diff
                        print(f"⚙️ Switched to engine mode ({difficulty})")
                        await send_ws({"type": "chat",
                                       "text": f"⚙️ Switched to engine mode ({difficulty})"})
                        continue
                    elif stripped == '/euler':
                        mode = 'euler'
                        print("🤖 Switched to Euler AI mode")
                        await send_ws({"type": "chat",
                                       "text": "🤖 Switched to Euler AI mode"})
                        continue

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
