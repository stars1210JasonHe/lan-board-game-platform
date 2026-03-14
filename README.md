# LAN Board Game Platform

> **Play Gomoku, Chess, and Xiangqi against an LLM — or a friend on your LAN — right from your browser.**

A self-hosted board game server where you can play classic board games against an AI powered by any LLM (ChatGPT, Claude, local models) — or challenge friends on your local network. Drop it on any machine, open a browser, and start playing in under a minute.

![screenshot](docs/screenshot.png)

---

## Features

### Three classic games

| Game | Board | Win condition |
|------|-------|---------------|
| **Gomoku** (五子棋) | 15×15 grid | First to place 5 stones in a row |
| **Chess** | 8×8 board | Checkmate the opponent's king |
| **Xiangqi** (中国象棋) | 10×9 board | Checkmate the opponent's general |

### AI opponents — three flavors

- **LLM AI** — powered by any large language model (OpenAI, Anthropic, OpenClaw, or custom). Reads game-specific skill files for strategy. Chats with you during the game.
- **Stockfish / Fairy-Stockfish engine** — classical engine for Chess and Xiangqi, with five difficulty levels (Beginner → Max)
- **Local minimax** — fast, free, offline algorithm for Gomoku (depth 5, iterative deepening, no API needed)

### Multiplayer & lobby
- Real-time play over WebSocket — any device on the LAN can join
- Room list in the lobby — create, join, or spectate any open room
- **Spectator mode** — watch a match without interrupting the players
- **Game chat** — talk trash, celebrate, or just say "gg" — the AI chats back

### Game flow
- **Side selection** — choose to play first, second, or let fate decide (random)
- **Auto-swap on rematch** — sides alternate automatically after each "Play Again"
- **Match history** — every completed game is stored in SQLite, accessible via the UI

### UI
- Dark theme, canvas-rendered boards
- Sound effects for moves and captures
- Invalid move hints with context-specific explanations
- No installation on the client side — just a URL

---

## Quick Start

### 1. Start the server

```bash
cd apps/server
npm install
npm run build
npm start
# → http://0.0.0.0:8765
```

For development with auto-reload:

```bash
npm run dev
```

### 2. Configure LLM (choose one)

Set environment variables before starting, or put them in `apps/server/.env`.

#### Option A: OpenClaw HTTP API (recommended if you have OpenClaw)

```bash
AI_ENGINE=openclaw-http
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789   # your OpenClaw gateway URL
OPENCLAW_GATEWAY_TOKEN=your_token_here         # from ~/.openclaw/openclaw.json
AI_MODEL=anthropic/claude-sonnet-4-6           # any model your gateway supports
```

Or just run without any config — if `~/.openclaw/openclaw.json` exists on the server machine, the token is read automatically.

#### Option B: OpenAI API

```bash
AI_ENGINE=openai
AI_API_KEY=sk-xxx
AI_MODEL=gpt-4o
```

#### Option C: Anthropic API

```bash
AI_ENGINE=anthropic
AI_API_KEY=sk-ant-xxx
AI_MODEL=claude-3-5-haiku-20241022
```

#### Option D: OpenRouter (access 100+ models with one key)

```bash
AI_ENGINE=openrouter
AI_API_KEY=sk-or-v1-xxx
AI_MODEL=openai/gpt-4o-mini
```

#### Option E: Ollama (local, no API key)

```bash
AI_ENGINE=ollama
AI_MODEL=llama3.1
```

### 3. Open in your browser

On any device on the same network:

```
http://<server-ip>:8765
```

- Enter a nickname
- Create a room (pick your game, side preference, and difficulty)
- Both players click **Ready** → game starts automatically

---

## AI Modes

### LLM AI (Chess & Xiangqi)

The LLM receives rich context for every move decision — not just the board, but tactical analysis to help it play stronger:

| Context given to LLM | Chess | Xiangqi |
|-----------------------|-------|---------|
| Board visualization (ASCII) | ✅ | ✅ |
| FEN position string | ✅ | ✅ |
| Legal moves list (SAN / coordinate) | ✅ | ✅ |
| Pieces under attack (with attackers) | ✅ | ✅ |
| Capturable opponent pieces (defended/undefended) | ✅ | ✅ |
| Move history (last 10 moves) | ✅ | ✅ |
| Game-specific strategy (SKILL.md) | ✅ | ✅ |
| Pre-move safety checklist | ✅ | ✅ |

How it works:
1. Per-game skill files teach strategy, openings, and tactics (`skills/chess-player/`, `skills/xiangqi-player/`)
2. Each move request sends: skill (system prompt) + board + FEN + legal moves + tactical analysis + history
3. Attack detection uses `python-chess` (chess) and `cchess` (xiangqi) to identify threats
4. LLM picks a move from the legal list — no illegal moves possible
5. 3 retries with error feedback if LLM picks an invalid format
6. Final fallback: random legal move

### Local Minimax (Gomoku)

Gomoku uses a local algorithm — no LLM, no API, no cost:
- Minimax with alpha-beta pruning
- Iterative deepening: depth 3 → 4 → 5
- 3-second time limit per move
- Candidate filtering: only searches near existing stones

### Stockfish / Fairy-Stockfish (Chess & Xiangqi)

Classical engines with five difficulty levels:

| Difficulty | Skill level | Think time |
|------------|-------------|------------|
| Beginner   | 2           | 200 ms     |
| Easy       | 6           | 500 ms     |
| Medium     | 12          | 1 s        |
| Hard       | 16          | 2 s        |
| Max        | 20          | 3 s        |

Requires `stockfish` and/or `fairy-stockfish` installed on the system.

---

## Skills System

The LLM's game knowledge comes from skill files — markdown documents that teach it rules, strategy, and openings:

```
skills/
├── chess-player/
│   ├── SKILL.md              # Piece values, strategy, output format
│   └── references/
│       └── openings.md       # 13 common openings (Italian, Sicilian, etc.)
├── xiangqi-player/
│   ├── SKILL.md              # Coordinate system, pieces, strategy
│   └── references/
│       └── openings.md       # 6 Red openings + 5 Black responses
└── gomoku-player/
    └── SKILL.md              # Documents the minimax algorithm (no LLM)
```

Skills are loaded once at server startup and cached in memory. Edit them to change the AI's playing style.

---

## Architecture

```
Browser (any LAN device)
+------------------------------------------+
|  Single-page app (Canvas + WebSocket)    |
|  Gomoku / Chess / Xiangqi rendering      |
+--------------------+---------------------+
                     | WS + HTTP
                     v
Game Server  (Node.js / TypeScript)
+------------------------------------------+
|  WebSocket:  rooms, moves, chat, spectate|
|  HTTP API:   /api/move  /api/chat        |
|              /api/history                |
|  LLM layer:  llm.ts (OpenClaw / OpenAI  |
|              / Anthropic / custom)        |
|  Skills:     loaded at startup from      |
|              skills/ directory            |
|  Engines:    gomoku.ts  chess.ts         |
|              xiangqi.ts                  |
|  Database:   SQLite  (matches.db)        |
+--------------------+---------------------+
                     | WebSocket (optional)
                     v
AI Bot Client  (Python)
+------------------------------------------+
|  euler_play.py                           |
|  Connects as a regular player            |
|  Moves via server API or local algorithm |
|  Chat via server API                     |
+------------------------------------------+
```

**Key design choices:**
- The server is the single source of truth — all move validation happens server-side
- The AI bot (`euler_play.py`) joins a room exactly like a human player would, over WebSocket
- LLM provider is abstracted — swap between OpenAI, Anthropic, or OpenClaw with one env var
- The frontend is a single `index.html` with no build step — edit and refresh
- Skills are plain markdown — easy to read, edit, and version control

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Server runtime | Node.js 20+ |
| Server language | TypeScript 5.3+ |
| WebSocket | `ws` 8.16 |
| Chess rules | `chess.js` 1.0 |
| Database | SQLite via `better-sqlite3` 9.4 |
| Frontend | Vanilla JS + HTML5 Canvas (no framework, no build) |
| AI bot | Python 3 + `websockets` |
| Chess engine | Stockfish (optional) |
| Xiangqi engine | Fairy-Stockfish (optional) |
| LLM | Any OpenAI/Anthropic-compatible API or OpenClaw |

---

## Project Structure

```
lan-board-game-platform/
  apps/
    server/
      src/
        index.ts           # HTTP + WebSocket server
        llm.ts             # LLM provider abstraction
        games/
          gomoku.ts         # 15×15 engine + 5-in-a-row detection
          chess.ts          # chess.js wrapper
          xiangqi.ts        # Full Xiangqi rules
      static/
        index.html          # Single-file browser client
    agent-player/
      euler_play.py         # Standalone AI bot client
  skills/
    chess-player/           # Chess strategy + openings
    xiangqi-player/         # Xiangqi strategy + openings
    gomoku-player/          # Minimax documentation
  docs/
    RUNBOOK.md              # Operator quick-reference
```

---

### AI Engine Configuration

The AI opponent is configured via environment variables in `apps/server/.env`.

**Supported engines:**

| `AI_ENGINE` | `AI_MODEL` example | Key required |
|---|---|---|
| `openclaw-http` | `anthropic/claude-sonnet-4-6` | `OPENCLAW_GATEWAY_TOKEN` (auto-read from `~/.openclaw/openclaw.json` if present) |
| `openclaw` | _(uses OpenClaw CLI)_ | No extra config if OpenClaw is installed |
| `openai` | `gpt-4o`, `gpt-4o-mini` | `AI_API_KEY` from [platform.openai.com](https://platform.openai.com) |
| `anthropic` | `claude-3-5-haiku-20241022` | `AI_API_KEY` from [console.anthropic.com](https://console.anthropic.com) |
| `openrouter` | `openai/gpt-4o-mini`, `anthropic/claude-3-haiku` | `AI_API_KEY` from [openrouter.ai](https://openrouter.ai) |
| `ollama` | `llama3.1`, `mistral` | No key (local) |

**OpenClaw users:** set `OPENCLAW_GATEWAY_URL` if your gateway is not on `127.0.0.1:18789`:
```
OPENCLAW_GATEWAY_URL=http://192.168.1.x:18789
```

---

## Roadmap

- [ ] **LLM vs LLM mode** — pit two AI models against each other and watch
- [ ] **ELO rating system** — track skill over time across human and AI players
- [ ] **Game replay** — step through any match from history move by move
- [ ] **Multi-model arena** — round-robin tournament across different LLM providers
- [ ] **More games** — Reversi, Go (9×9), Checkers
- [ ] **Mobile-optimized layout** — friendlier on small screens

---

## License

MIT
