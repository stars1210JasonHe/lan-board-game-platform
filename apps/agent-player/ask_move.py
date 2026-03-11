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


def build_user_prompt(game: str, board: list, side: str, legal_moves: list) -> str:
    """Build the user prompt with board + legal moves."""
    board_str = render_board(game, board, side)
    moves_str = ", ".join(
        f"{m['fromRow']},{m['fromCol']},{m['toRow']},{m['toCol']}" for m in legal_moves
    )
    return (
        f"{board_str}\n\n"
        f"Legal moves: [{moves_str}]\n\n"
        f"Pick the BEST move. Reply with ONLY one line: fromRow,fromCol,toRow,toCol\n"
        f"Example: 6,0,5,0\n"
        f"No explanation — just the four numbers separated by commas."
    )


def parse_move(text: str, legal_moves: list) -> str | None:
    """Extract fromRow,fromCol,toRow,toCol from LLM response text."""
    # Try to find a pattern like digits,digits,digits,digits
    match = re.search(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text)
    if not match:
        return None
    move_str = f"{match.group(1)},{match.group(2)},{match.group(3)},{match.group(4)}"
    # Validate against legal moves
    fr, fc, tr, tc = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    for m in legal_moves:
        if m["fromRow"] == fr and m["fromCol"] == fc and m["toRow"] == tr and m["toCol"] == tc:
            return move_str
    return None


def random_move(legal_moves: list) -> str:
    """Pick a random legal move as fallback."""
    m = random.choice(legal_moves)
    return f"{m['fromRow']},{m['fromCol']},{m['toRow']},{m['toCol']}"


# ── Engine implementations ────────────────────────────────────────────────────

def call_openclaw(system_prompt: str, user_prompt: str, model: str | None, timeout: int) -> str | None:
    """Call openclaw gateway with a unique ephemeral session-id (avoids main session lock)."""
    import uuid
    session_id = f"game-move-{uuid.uuid4().hex[:8]}"
    prompt = f"{system_prompt}\n\n{user_prompt}"
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
    parser.add_argument("--game", required=True, choices=["xiangqi", "chess"])
    parser.add_argument("--side", required=True)
    parser.add_argument("--board-json", required=True, help="JSON with board and legalMoves")
    parser.add_argument("--engine", default="openclaw", choices=list(ENGINES.keys()))
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    data = json.loads(args.board_json)
    board = data.get("board", [])
    legal_moves = data.get("legalMoves", [])

    if not legal_moves:
        print('resign')
        sys.exit(0)

    system_prompt = load_system_prompt(args.game)
    user_prompt = build_user_prompt(args.game, board, args.side, legal_moves)

    engine_fn = ENGINES[args.engine]
    response = engine_fn(system_prompt, user_prompt, args.model, args.timeout)

    if response:
        move = parse_move(response, legal_moves)
        if move:
            print(move)
            return

    # Fallback: random legal move
    print(f"[ask_move] Falling back to random move", file=sys.stderr)
    print(random_move(legal_moves))


if __name__ == "__main__":
    main()
