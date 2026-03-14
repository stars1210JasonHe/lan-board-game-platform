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
    """Load SKILL.md + references/*.md for the given game."""
    game_skill_map = {
        "chess": "chess-player",
        "xiangqi": "xiangqi-player",
        "gomoku": "gomoku-player",
    }
    skill_name = game_skill_map.get(game, f"{game}-player")
    skill_dir = os.path.join(SKILLS_DIR, skill_name)
    skill_path = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(skill_path, "r") as f:
            text = f.read()
        # Strip YAML frontmatter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                text = text[end + 3:].strip()
    except FileNotFoundError:
        return f"You are an expert {game} player."
    # Load references/*.md
    refs_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(refs_dir):
        for fname in sorted(os.listdir(refs_dir)):
            if fname.endswith(".md"):
                try:
                    with open(os.path.join(refs_dir, fname), "r") as f:
                        text += "\n\n" + f.read()
                except Exception:
                    pass
    return text


def render_board(game: str, board: list, side: str) -> str:
    """Render the board visually for the LLM prompt."""
    lines = [f"Game: {game} | You are playing as: {side}", ""]
    if game == "xiangqi":
        lines.append("     a b c d e f g h i")
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
    """Analyze which pieces are under attack for xiangqi (pure Python)."""
    from xiangqi_attack import fen_to_board, get_attacked_pieces_info
    board, side = fen_to_board(fen)
    return get_attacked_pieces_info(board, side)


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
                # After opponent captures, can we recapture?
                board.push(opp_move)
                can_recapture = any(
                    m.to_square == opp_move.to_square for m in board.legal_moves
                )
                board.pop()
                if not can_recapture:
                    piece_name = chess.piece_name(captured.piece_type).title()
                    san = chess.Board(fen).san(move)
                    return f"Your move {san} hangs your {piece_name}"
    return None


def check_blunder_xiangqi(fen: str, move_coords: str) -> str | None:
    """Check if a xiangqi move hangs a piece worth >= 3 (Horse=4, Cannon=4.5, Chariot=9).
    Returns description string if blunder found, None otherwise."""
    from xiangqi_attack import (fen_to_board, copy_board, apply_move,
                                get_attackers, is_defended, piece_side, RED, BLACK)
    PIECE_VALUES = {'r': 9, 'c': 4.5, 'n': 4, 'h': 4, 'b': 2, 'e': 2, 'a': 2, 'p': 1, 'k': 0}
    PIECE_NAMES = {'r': 'Chariot', 'c': 'Cannon', 'n': 'Horse', 'h': 'Horse',
                   'b': 'Elephant', 'e': 'Elephant', 'a': 'Advisor', 'p': 'Pawn', 'k': 'King'}

    board, side = fen_to_board(fen)
    opp = BLACK if side == RED else RED

    col_letters = "abcdefghi"
    mc = move_coords.split(',')
    fr, fc, tr, tc = int(mc[0]), int(mc[1]), int(mc[2]), int(mc[3])
    move_str = f"{col_letters[fc]}{fr}{col_letters[tc]}{tr}"
    board = copy_board(board)
    apply_move(board, fr, fc, tr, tc)

    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p == ' ' or piece_side(p) != side:
                continue
            val = PIECE_VALUES.get(p.lower(), 0)
            if val < 3:
                continue
            if get_attackers(board, r, c, opp) and not is_defended(board, r, c, side):
                name = PIECE_NAMES.get(p.lower(), 'piece')
                pos_str = f"{col_letters[c]}{r}"
                return f"Your move {move_str} hangs your {name} on {pos_str}"
    return None


def build_user_prompt(game: str, board: list, side: str, legal_moves: list,
                      fen: str | None = None, san_moves: list | None = None,
                      pgn: str | None = None) -> str:
    """Build the user prompt with board + legal moves + tactical info."""
    board_str = render_board(game, board, side)

    # Attacked pieces info
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

    if game == "chess" and san_moves:
        # Chess with SAN: show FEN and SAN legal moves
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
            f"Pick the BEST move. Reply with ONLY the SAN notation.\n"
            f"Example: Nf3\n"
            f"No explanation — just the move."
        )
    elif game == "xiangqi":
        # Xiangqi: letter+number coordinate format (col a-i, row 0-9)
        col_letters = "abcdefghi"
        moves_str = ", ".join(
            f"{col_letters[m['fromCol']]}{m['fromRow']}{col_letters[m['toCol']]}{m['toRow']}"
            for m in legal_moves
        )
        extra = ""
        if fen:
            extra += f"\nFEN: {fen}"
        if attack_info:
            extra += f"\n{attack_info}"
        return (
            f"{board_str}\n\n"
            f"Legal moves: [{moves_str}]"
            f"{extra}\n\n"
            f"Pick the BEST move. Reply with ONLY the coordinate like b0c2\n"
            f"Format: {{fromCol}}{{fromRow}}{{toCol}}{{toRow}} where columns are a-i and rows are 0-9\n"
            f"Example: b0c2\n"
            f"No explanation — just the move."
        )
    else:
        # Fallback: coordinate format
        moves_str = ", ".join(
            f"{m['fromRow']},{m['fromCol']},{m['toRow']},{m['toCol']}" for m in legal_moves
        )
        extra = ""
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
    # Check for resignation — only if LLM replies with just "resign"
    if text and text.strip().lower() in ('resign', 'i resign', 'resign.'):
        return 'resign'

    if fen and san_moves:
        # Chess SAN mode: parse SAN and convert to coordinates
        return _parse_chess_san(text, fen, san_moves)

    # Xiangqi coordinate mode: 4-char string like 'h2e2' (col_letter + row + col_letter + row)
    coord_match = re.search(r"\b([a-i])(\d)([a-i])(\d)\b", text)
    if coord_match:
        col_map = {c: i for i, c in enumerate("abcdefghi")}
        fc = col_map[coord_match.group(1)]
        fr = int(coord_match.group(2))
        tc = col_map[coord_match.group(3)]
        tr = int(coord_match.group(4))
        for m in legal_moves:
            if m["fromRow"] == fr and m["fromCol"] == fc and m["toRow"] == tr and m["toCol"] == tc:
                return f"{fr},{fc},{tr},{tc}"

    # Fallback: numeric coordinate mode (row,col,row,col)
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


def call_anthropic(system_prompt: str, user_prompt: str, model: str | None, timeout: int,
                   messages: list | None = None) -> str | None:
    """Call Anthropic Messages API directly."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[ask_move] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return None
    model = model or DEFAULT_MODELS["anthropic"]
    msgs = messages if messages else [{"role": "user", "content": user_prompt}]
    body = json.dumps({
        "model": model,
        "max_tokens": 64,
        "system": system_prompt,
        "messages": msgs,
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

def call_openrouter(system_prompt: str, user_prompt: str, model: str | None, timeout: int,
                    messages: list | None = None) -> str | None:
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
    msgs = messages if messages else [{"role": "user", "content": user_prompt}]
    body = json.dumps({
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "system", "content": system_prompt}] + msgs,
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


def call_openai(system_prompt: str, user_prompt: str, model: str | None, timeout: int,
                messages: list | None = None) -> str | None:
    """Call OpenAI Chat Completions API."""
    api_key = _load_env_key("OPENAI_API_KEY",
                             os.path.join(_SECRETS_DIR, "openai.env"),
                             os.path.expanduser("~/.openclaw/workspace/.secrets/openai.env"))
    if not api_key:
        print("[ask_move] OPENAI_API_KEY not set", file=sys.stderr)
        return None
    model = model or DEFAULT_MODELS["openai"]
    msgs = messages if messages else [{"role": "user", "content": user_prompt}]
    body = json.dumps({
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "system", "content": system_prompt}] + msgs,
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


def call_ollama(system_prompt: str, user_prompt: str, model: str | None, timeout: int,
                messages: list | None = None) -> str | None:
    """Call local Ollama API."""
    model = model or DEFAULT_MODELS["ollama"]
    msgs = messages if messages else [{"role": "user", "content": user_prompt}]
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "system", "content": system_prompt}] + msgs,
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


def call_openclaw_http(system_prompt: str, user_prompt: str, model: str | None, timeout: int,
                       messages: list | None = None) -> str | None:
    """Call OpenClaw gateway via HTTP API (stateless, no session accumulation)."""
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
    if not token:
        try:
            config_path = os.path.expanduser("~/.openclaw/openclaw.json")
            with open(config_path) as f:
                cfg = json.load(f)
            token = cfg.get("gateway", {}).get("auth", {}).get("token")
        except Exception:
            pass
    if not token:
        print("[ask_move] openclaw-http: no token found", file=sys.stderr)
        return None

    if messages is None:
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]

    body = json.dumps({
        "model": model or "openclaw:main",
        "messages": messages,
    }).encode()
    gateway_url = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    req = urllib.request.Request(
        f"{gateway_url}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"[ask_move] openclaw-http error: {e}", file=sys.stderr)
    return None


ENGINES = {
    "openclaw": call_openclaw,
    "openclaw-http": call_openclaw_http,
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
    parser.add_argument("--history-file", default=None, help="JSON file for conversation history reuse")
    parser.add_argument("--messages-file", default=None, help="Pre-built messages JSON file for openclaw-http")
    parser.add_argument("--pgn", default=None, help="PGN move history for chess")
    args = parser.parse_args()

    data = json.loads(args.board_json)
    board = data.get("board", [])
    legal_moves = data.get("legalMoves", [])

    if not legal_moves and args.game != "gomoku" and not (args.game == "chess" and args.fen):
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
                                    fen=args.fen, san_moves=san_moves,
                                    pgn=args.pgn)

    engine_fn = ENGINES[args.engine]

    # History file handling for non-openclaw engines
    use_history = args.history_file and args.engine not in ("openclaw", "openclaw-http")
    history_messages = None
    if use_history:
        history_messages = []
        if os.path.exists(args.history_file):
            try:
                with open(args.history_file) as f:
                    history_messages = json.load(f).get("messages", [])
            except Exception:
                history_messages = []
        history_messages.append({"role": "user", "content": user_prompt})
        # Trim to last 20 exchanges (40 messages)
        if len(history_messages) > 40:
            history_messages = history_messages[-40:]

    # openclaw-http with messages-file: build full messages array
    openclaw_http_messages = None
    if args.engine == "openclaw-http" and args.messages_file and os.path.exists(args.messages_file):
        try:
            with open(args.messages_file) as f:
                prior = json.load(f)
            openclaw_http_messages = [{"role": "system", "content": system_prompt}] + prior
            openclaw_http_messages.append({"role": "user", "content": user_prompt})
        except Exception as e:
            print(f"[ask_move] messages-file read error: {e}", file=sys.stderr)

    if args.engine == "openclaw-http" and openclaw_http_messages is not None:
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                             messages=openclaw_http_messages)
    elif args.engine == "openclaw-http":
        # No messages file — default system+user
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout)
    elif args.engine == "openclaw" and (args.session_id or args.skip_system):
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                             session_id=args.session_id, skip_system=args.skip_system)
    elif history_messages is not None:
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                             messages=history_messages)
    else:
        response = engine_fn(system_prompt, user_prompt, args.model, args.timeout)

    # Save history after successful response
    if response and use_history:
        history_messages.append({"role": "assistant", "content": response})
        try:
            with open(args.history_file, "w") as f:
                json.dump({"system": system_prompt, "messages": history_messages}, f)
        except Exception as e:
            print(f"[ask_move] history save error: {e}", file=sys.stderr)

    if response:
        move = parse_move(response, legal_moves, fen=args.fen, san_moves=san_moves)
        if move:
            # Anti-blunder verification (chess + xiangqi, max 2 retries)
            MAX_BLUNDER_RETRIES = 2
            blunder_retries = 0
            candidate_move = move
            candidate_response = response

            while candidate_move and candidate_move != 'resign' and blunder_retries < MAX_BLUNDER_RETRIES:
                blunder_msg = None
                try:
                    if args.game == "chess" and args.fen:
                        parts = candidate_move.split(",")
                        uci = (chr(ord('a') + int(parts[1])) + str(8 - int(parts[0])) +
                               chr(ord('a') + int(parts[3])) + str(8 - int(parts[2])))
                        blunder_msg = check_blunder_chess(args.fen, uci)
                    elif args.game == "xiangqi" and args.fen:
                        blunder_msg = check_blunder_xiangqi(args.fen, candidate_move)
                except Exception as e:
                    print(f"[ask_move] blunder check error: {e}", file=sys.stderr)
                    break

                if not blunder_msg:
                    break  # Move is safe

                blunder_retries += 1
                print(f"[ask_move] Blunder detected (retry {blunder_retries}): {blunder_msg}", file=sys.stderr)
                feedback = f"{blunder_msg}. Pick a different move."

                # Re-call engine with feedback
                response2 = None
                if args.engine == "openclaw":
                    response2 = call_openclaw(system_prompt, feedback, args.model, args.timeout,
                                              session_id=args.session_id, skip_system=True)
                elif args.engine == "openclaw-http":
                    retry_msgs = (openclaw_http_messages or [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]) + [
                        {"role": "assistant", "content": candidate_response},
                        {"role": "user", "content": feedback},
                    ]
                    response2 = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                                          messages=retry_msgs)
                else:
                    messages = [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": candidate_response},
                        {"role": "user", "content": feedback},
                    ]
                    response2 = engine_fn(system_prompt, user_prompt, args.model, args.timeout,
                                          messages=messages)
                if response2:
                    candidate_response = response2
                    candidate_move = parse_move(response2, legal_moves, fen=args.fen, san_moves=san_moves)
                else:
                    break  # Engine failed, accept current move

            if candidate_move:
                # Save openclaw-http messages file with the final (post-blunder-check) response
                if args.engine == "openclaw-http" and args.messages_file:
                    try:
                        prior = []
                        if os.path.exists(args.messages_file):
                            with open(args.messages_file) as f:
                                prior = json.load(f)
                        prior.append({"role": "user", "content": user_prompt})
                        prior.append({"role": "assistant", "content": candidate_response})
                        # Cap at 8 messages (last 4 exchanges)
                        if len(prior) > 8:
                            prior = prior[-8:]
                        with open(args.messages_file, "w") as f:
                            json.dump(prior, f)
                    except Exception as e:
                        print(f"[ask_move] messages-file save error: {e}", file=sys.stderr)
                print(candidate_move)
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
