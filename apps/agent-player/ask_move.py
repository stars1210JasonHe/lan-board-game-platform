#!/usr/bin/env python3
"""
ask_move.py — Ask an LLM for the best move given a board state.

Usage:
  python3 ask_move.py --game xiangqi --side red --board-json '{"board":[...],"legalMoves":[...]}' --engine openclaw
"""
import argparse, json, os, random, re, subprocess, sys, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(SCRIPT_DIR, "..", "..", "skills")

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "openrouter": "anthropic/claude-haiku-4.5",
    "ollama": "llama3",
}


def load_system_prompt(game: str) -> str:
    """Load SKILL.md for the given game from skills/{game}-player/SKILL.md."""
    game_skill_map = {
        "chess": "chess-player",
        "xiangqi": "xiangqi-player",
        "gomoku": "gomoku-player",
    }
    skill_name = game_skill_map.get(game, f"{game}-player")
    skill_path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
    try:
        with open(skill_path, "r") as f:
            text = f.read()
        # Strip YAML frontmatter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                text = text[end + 3:].strip()
        return text
    except FileNotFoundError:
        return f"You are an expert {game} player."


def render_board(game: str, board: list, side: str) -> str:
    """Render the board visually for the LLM prompt."""
    lines = [f"Game: {game} | You are playing as: {side}", ""]
    if game == "xiangqi":
        lines.append("     0 1 2 3 4 5 6 7 8")
        lines.append("    ╔═════════════════╗")
        for i, row in enumerate(board):
            pieces = " ".join(ch if ch != " " else "·" for ch in row)
            river = "  ── river ──" if i == 4 else ""
            lines.append(f"  {i} ║{pieces}║{river}")
        lines.append("    ╚═════════════════╝")
    else:
        lines.append("     0 1 2 3 4 5 6 7")
        for i, row in enumerate(board):
            pieces = " ".join(ch if ch != "." else "·" for ch in row)
            lines.append(f"  {i} │{pieces}│")
    return "\n".join(lines)


def xiangqi_attacked_pieces_info(fen: str) -> str:
    """Analyze which pieces are under attack for xiangqi using cchess."""
    import cchess

    fen_parts = fen.split()
    short_fen = f"{fen_parts[0]} {fen_parts[1]}"
    board = cchess.ChessBoard(short_fen)

    side = cchess.RED if fen_parts[1] == 'w' else cchess.BLACK
    opp = cchess.BLACK if side == cchess.RED else cchess.RED

    PIECE_NAMES = {
        'k': 'King', 'a': 'Advisor', 'b': 'Elephant',
        'n': 'Horse', 'r': 'Chariot', 'c': 'Cannon', 'p': 'Soldier',
    }

    def piece_name(piece):
        return PIECE_NAMES.get(piece.species, 'piece')

    def square_name(x, y):
        return chr(ord('a') + x) + str(y)

    def get_attackers(attacking_color, target_sq):
        result = []
        for p in board.get_pieces(attacking_color):
            if p.is_valid_move(target_sq):
                target_p = board.get_piece(target_sq)
                if target_p and target_p.color == p.color:
                    continue
                result.append(p)
        return result

    def is_defended(target_sq, defending_color):
        for p in board.get_pieces(defending_color):
            if (p.x, p.y) == target_sq:
                continue
            if p.is_valid_move(target_sq):
                return True
        return False

    our_attacked = []
    for p in board.get_pieces(side):
        sq = (p.x, p.y)
        attackers = get_attackers(opp, sq)
        if attackers:
            att_str = ", ".join(f"{piece_name(a).lower()}" for a in attackers)
            our_attacked.append(f"{piece_name(p)} on {square_name(p.x, p.y)} (by {att_str})")

    opp_capturable = []
    for p in board.get_pieces(opp):
        sq = (p.x, p.y)
        attackers = get_attackers(side, sq)
        if attackers:
            defended = is_defended(sq, opp)
            defense_str = "defended" if defended else "undefended"
            opp_capturable.append(f"{piece_name(p)} on {square_name(p.x, p.y)} ({defense_str})")

    lines = []
    if our_attacked:
        lines.append(f"Your pieces under attack: {', '.join(our_attacked)}")
    if opp_capturable:
        lines.append(f"Opponent pieces you can capture: {', '.join(opp_capturable)}")
    return "\n".join(lines)


def build_user_prompt(game: str, board: list, side: str, legal_moves: list,
                      fen: str | None = None, san_moves: list | None = None) -> str:
    """Build the user prompt with board + legal moves + tactical info."""
    board_str = render_board(game, board, side)

    # Attacked pieces info for xiangqi
    attack_info = ""
    if game == "xiangqi" and fen:
        try:
            attack_info = xiangqi_attacked_pieces_info(fen)
        except Exception as e:
            print(f"[ask_move] xiangqi attack info error: {e}", file=sys.stderr)

    if game == "chess" and san_moves:
        # Chess with SAN: show FEN and SAN legal moves
        moves_str = ", ".join(san_moves)
        return (
            f"{board_str}\n\n"
            f"FEN: {fen}\n"
            f"Legal moves (SAN): [{moves_str}]\n\n"
            f"Pick the BEST move. Reply with ONLY the SAN notation.\n"
            f"Example: Nf3\n"
            f"No explanation — just the move."
        )
    else:
        # Xiangqi / fallback: coordinate format
        moves_str = ", ".join(
            f"{m['fromRow']},{m['fromCol']},{m['toRow']},{m['toCol']}" for m in legal_moves
        )
        extra = ""
        if game == "xiangqi" and fen:
            extra += f"\nFEN: {fen}"
        if attack_info:
            extra += f"\n{attack_info}"
        return (
            f"{board_str}\n\n"
            f"Legal moves: [{moves_str}]"
            f"{extra}\n\n"
            f"Pick the BEST move. Reply with ONLY one line: fromRow,fromCol,toRow,toCol\n"
            f"Example: 6,0,5,0\n"
            f"No explanation — just the four numbers separated by commas."
        )


def parse_move(text: str, legal_moves: list, fen: str | None = None,
               san_moves: list | None = None) -> str | None:
    """Extract a move from LLM response. Returns fromRow,fromCol,toRow,toCol string.

    For chess with SAN: parses SAN notation and converts to coordinates using python-chess.
    For xiangqi: parses coordinate format (digits,digits,digits,digits).
    Returns 'resign' if LLM wants to resign.
    """
    # Check for resignation
    if text and 'resign' in text.strip().lower():
        return 'resign'

    if fen and san_moves:
        # Chess SAN mode: parse SAN and convert to coordinates
        return _parse_chess_san(text, fen, san_moves)

    # Coordinate mode (xiangqi / chess fallback)
    match = re.search(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text)
    if not match:
        return None
    fr, fc, tr, tc = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    for m in legal_moves:
        if m["fromRow"] == fr and m["fromCol"] == fc and m["toRow"] == tr and m["toCol"] == tc:
            return f"{fr},{fc},{tr},{tc}"
    return None


def _parse_chess_san(text: str, fen: str, san_moves: list) -> str | None:
    """Parse SAN move from LLM response, convert to fromRow,fromCol,toRow,toCol."""
    import chess
    # Extract the first word that looks like a SAN move
    text = text.strip()
    # Try the first token (strip trailing punctuation)
    candidate = text.split()[0].rstrip(".!?:,") if text else ""
    board = chess.Board(fen)

    # Try the candidate directly
    for san in san_moves:
        if candidate == san:
            try:
                m = board.parse_san(san)
                return _uci_to_coords(m.uci())
            except Exception:
                pass

    # Scan response for any legal SAN move
    for san in san_moves:
        if san in text:
            try:
                m = board.parse_san(san)
                return _uci_to_coords(m.uci())
            except Exception:
                pass
    return None


def _uci_to_coords(uci: str) -> str:
    """Convert UCI string (e.g. 'g1f3') to fromRow,fromCol,toRow,toCol."""
    fc = ord(uci[0]) - ord('a')
    fr = 8 - int(uci[1])
    tc = ord(uci[2]) - ord('a')
    tr = 8 - int(uci[3])
    return f"{fr},{fc},{tr},{tc}"


def random_move(legal_moves: list) -> str:
    """Pick a random legal move as fallback."""
    m = random.choice(legal_moves)
    return f"{m['fromRow']},{m['fromCol']},{m['toRow']},{m['toCol']}"


# ── Engine implementations ────────────────────────────────────────────────────

def call_openclaw(system_prompt: str, user_prompt: str, model: str | None, timeout: int,
                   session_id: str | None = None, skip_system: bool = False) -> str | None:
    """Call openclaw gateway. Reuses session_id for context continuity when provided."""
    if not session_id:
        import uuid
        session_id = f"game-move-{uuid.uuid4().hex[:8]}"
    prompt = user_prompt if skip_system else f"{system_prompt}\n\n{user_prompt}"
    cmd = ["openclaw", "agent", "--session-id", session_id, "--message", prompt, "--json"]
    if model:
        cmd += ["--model", model]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(f"[ask_move] openclaw error: {result.stderr.strip()}", file=sys.stderr)
            return None
        data = json.loads(result.stdout)
        payloads = data.get("result", {}).get("payloads", [])
        if payloads:
            return payloads[0].get("text", "")
        return data.get("text", "")
    except subprocess.TimeoutExpired:
        print("[ask_move] openclaw timeout", file=sys.stderr)
        return None
    except (json.JSONDecodeError, Exception) as e:
        print(f"[ask_move] openclaw parse error: {e}", file=sys.stderr)
        return None


def call_anthropic(system_prompt: str, user_prompt: str, model: str | None, timeout: int) -> str | None:
    """Call Anthropic Messages API directly."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[ask_move] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return None
    model = model or DEFAULT_MODELS["anthropic"]
    body = json.dumps({
        "model": model,
        "max_tokens": 64,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0]["text"]
    except Exception as e:
        print(f"[ask_move] anthropic error: {e}", file=sys.stderr)
    return None


def _load_env_key(env_var: str, *secret_files) -> str | None:
    """Try env var first, then fall back to reading from .secrets/*.env files."""
    val = os.environ.get(env_var)
    if val:
        return val
    for path in secret_files:
        try:
            for line in open(path):
                line = line.strip()
                if line.startswith(f"{env_var}="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return None

_SECRETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".secrets")

def call_openrouter(system_prompt: str, user_prompt: str, model: str | None, timeout: int) -> str | None:
    """Call OpenRouter API (OpenAI-compatible)."""
    api_key = (_load_env_key("OPENROUTER_API_KEY",
                              os.path.join(_SECRETS_DIR, "minimax.env"),
                              os.path.expanduser("~/.openclaw/workspace/.secrets/minimax.env"))
               or _load_env_key("MINIMAX_API_KEY",
                                 os.path.join(_SECRETS_DIR, "minimax.env"),
                                 os.path.expanduser("~/.openclaw/workspace/.secrets/minimax.env")))
    if not api_key:
        print("[ask_move] OPENROUTER_API_KEY not set", file=sys.stderr)
        return None
    model = model or DEFAULT_MODELS["openrouter"]
    body = json.dumps({
        "model": model,
        "max_tokens": 64,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"[ask_move] openrouter error: {e}", file=sys.stderr)
    return None


def call_openai(system_prompt: str, user_prompt: str, model: str | None, timeout: int) -> str | None:
    """Call OpenAI Chat Completions API."""
    api_key = _load_env_key("OPENAI_API_KEY",
                             os.path.join(_SECRETS_DIR, "openai.env"),
                             os.path.expanduser("~/.openclaw/workspace/.secrets/openai.env"))
    if not api_key:
        print("[ask_move] OPENAI_API_KEY not set", file=sys.stderr)
        return None
    model = model or DEFAULT_MODELS["openai"]
    body = json.dumps({
        "model": model,
        "max_tokens": 64,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"[ask_move] openai error: {e}", file=sys.stderr)
    return None


def call_ollama(system_prompt: str, user_prompt: str, model: str | None, timeout: int) -> str | None:
    """Call local Ollama API."""
    model = model or DEFAULT_MODELS["ollama"]
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return data.get("message", {}).get("content", "")
    except Exception as e:
        print(f"[ask_move] ollama error: {e}", file=sys.stderr)
    return None


ENGINES = {
    "openclaw": call_openclaw,
    "anthropic": call_anthropic,
    "openai": call_openai,
    "openrouter": call_openrouter,
    "ollama": call_ollama,
}


def main():
    parser = argparse.ArgumentParser(description="Ask an LLM for the best board game move")
    parser.add_argument("--game", required=True, choices=["xiangqi", "chess", "gomoku"])
    parser.add_argument("--side", required=True)
    parser.add_argument("--board-json", required=True, help="JSON with board and legalMoves")
    parser.add_argument("--engine", default="openclaw", choices=list(ENGINES.keys()))
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--fen", default=None, help="FEN string for chess SAN resolution")
    parser.add_argument("--session-id", default=None, help="Reuse OpenClaw session for context")
    parser.add_argument("--skip-system", action="store_true", help="Skip system prompt (already sent)")
    args = parser.parse_args()

    data = json.loads(args.board_json)
    board = data.get("board", [])
    legal_moves = data.get("legalMoves", [])

    if not legal_moves and args.game != "gomoku":
        print('resign')
        sys.exit(0)

    # For chess with FEN: generate SAN legal moves using python-chess
    san_moves = None
    if args.game == "chess" and args.fen:
        try:
            import chess
            cb = chess.Board(args.fen)
            san_moves = [cb.san(m) for m in cb.legal_moves]
        except Exception as e:
            print(f"[ask_move] SAN generation failed: {e}", file=sys.stderr)

    system_prompt = load_system_prompt(args.game)
    user_prompt = build_user_prompt(args.game, board, args.side, legal_moves,
                                    fen=args.fen, san_moves=san_moves)

    engine_fn = ENGINES[args.engine]
    if args.engine == "openclaw" and (args.session_id or args.skip_system):
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                             session_id=args.session_id, skip_system=args.skip_system)
    else:
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout)

    if response:
        move = parse_move(response, legal_moves, fen=args.fen, san_moves=san_moves)
        if move:
            print(move)
            return

    # Fallback: random legal move
    print(f"[ask_move] Falling back to random move", file=sys.stderr)
    if args.game == "gomoku":
        # Gomoku: pick a random empty cell near center
        size = data.get("size", 15)
        center = size // 2
        empties = []
        for r in range(size):
            for c in range(size):
                if board[r][c] == 0:
                    empties.append((r, c, abs(r - center) + abs(c - center)))
        empties.sort(key=lambda x: x[2])
        pick = empties[random.randint(0, min(4, len(empties) - 1))] if empties else (center, center, 0)
        print(f"{pick[0]},{pick[1]}")
    else:
        print(random_move(legal_moves))


if __name__ == "__main__":
    main()
