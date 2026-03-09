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

#### Option A: OpenClaw (recommended if you have it)

No extra config needed. The server calls `openclaw agent` automatically.

```bash
npm start  # Just works
```

#### Option B: OpenAI API

```bash
LLM_PROVIDER=openai LLM_API_KEY=sk-xxx LLM_MODEL=gpt-4o npm start
```

#### Option C: Anthropic API

```bash
LLM_PROVIDER=anthropic LLM_API_KEY=sk-ant-xxx LLM_MODEL=claude-sonnet-4-20250514 npm start
```

#### Option D: Any OpenAI-compatible API

```bash
LLM_PROVIDER=openai LLM_API_KEY=xxx LLM_MODEL=your-model LLM_BASE_URL=https://your-endpoint.com npm start
```

#### Option E: Config file

Create `config.json` in the project root:

```json
{
  "llm": {
    "provider": "openai",
    "apiKey": "sk-xxx",
    "model": "gpt-4o",
    "baseUrl": ""
  }
}
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

The LLM receives the board position, legal moves list, and game-specific strategy from skill files. It picks the best move and can chat about the game.

How it works:
1. Server loads skill files at startup (`skills/chess-player/`, `skills/xiangqi-player/`)
2. Each move request sends: skill (system prompt) + board state + legal moves
3. LLM picks a move from the legal list — no illegal moves possible
4. 3 retries with error feedback if LLM picks an invalid format
5. Final fallback: random legal move

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
