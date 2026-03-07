# LAN Board Game Platform

> **Play Gomoku, Chess, and Xiangqi against an AI — or a friend on your LAN — right from your browser.**

A self-hosted board game server built for the sheer joy of playing classic games against an intelligent opponent. Drop it on any machine on your local network, open a browser, and start playing in under a minute.

![screenshot](docs/screenshot.png)

---

## Features

### Three classic games

| Game | Board | Win condition |
|------|-------|---------------|
| **Gomoku** (五子棋) | 15×15 grid | First to place 5 stones in a row |
| **Chess** | 8×8 board | Checkmate the opponent's king |
| **Xiangqi** (中国象棋) | 10×9 board | Checkmate the opponent's general |

### AI opponents — two flavors

- **OpenClaw AI** — an LLM-powered agent that plays (and chats!) like a real opponent
- **Stockfish / Fairy-Stockfish engine** — classical engine for Chess and Xiangqi, with five difficulty levels (Beginner → Max)

### Multiplayer & lobby
- Real-time play over WebSocket — any device on the LAN can join
- Room list in the lobby — create, join, or spectate any open room
- **Spectator mode** — watch a match without interrupting the players
- **Game chat** — talk trash, celebrate, or just say "gg"

### Game flow
- **Side selection** — choose to play first, second, or let fate decide (random)
- **Auto-swap on rematch** — sides alternate automatically after each "Play Again"
- **Match history** — every completed game is stored in SQLite, accessible via the UI

### UI
- Dark theme, canvas-rendered boards
- No installation on the client side — just a URL

---

## Screenshots

![lobby](docs/screenshot-lobby.png)
![gomoku](docs/screenshot-gomoku.png)
![chess](docs/screenshot-chess.png)
![xiangqi](docs/screenshot-xiangqi.png)

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
|  Moves via OpenClaw API or local engine  |
|  Chat via OpenClaw API or canned replies |
+------------------------------------------+
```

**Key design choices:**
- The server is the single source of truth — all move validation happens server-side
- The AI bot (`euler_play.py`) joins a room exactly like a human player would, over WebSocket
- The frontend is a single `index.html` with no build step — edit and refresh

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

### 2. Open in your browser

On any device on the same network:

```
http://<server-ip>:8765
```

- Enter a nickname
- Create a room (pick your game, side preference, and difficulty)
- Both players click **Ready** → game starts automatically

### 3. Run the standalone AI bot (optional)

The server already includes a built-in AI mode — but you can also run `euler_play.py` as a separate bot client for testing or advanced use:

```bash
cd apps/agent-player
pip install websockets

# See open rooms
python3 euler_play.py --list --host <server-ip>

# Join a room as Euler AI
python3 euler_play.py <ROOM_ID> --host <server-ip>

# Join using Stockfish engine at medium difficulty
python3 euler_play.py <ROOM_ID> --host <server-ip> --mode engine --difficulty medium

# Quiet mode (no AI chat)
python3 euler_play.py <ROOM_ID> --host <server-ip> --no-ai-chat
```

---

## AI Modes

The platform offers two fundamentally different ways to play against the computer:

### OpenClaw AI (LLM-powered)

OpenClaw is an LLM-based AI agent. It reasons about the board state using a language model and generates moves accordingly. It also participates in the in-game chat — so it might taunt you after a good move or congratulate you when you win.

This mode is available for Gomoku and is what the "Euler" mode selects. It requires the OpenClaw agent service to be running; if it's unavailable, the server falls back to a local minimax algorithm.

**Best for:** Gomoku. Personality included.

### Stockfish / Fairy-Stockfish (classical engine)

For Chess and Xiangqi, the platform uses battle-tested open-source engines:
- **Stockfish** for Chess (`/usr/games/stockfish`)
- **Fairy-Stockfish** for Xiangqi (`/usr/games/fairy-stockfish`)

Five difficulty levels map to Stockfish skill levels and thinking time:

| Difficulty | Skill level | Think time |
|------------|-------------|------------|
| Beginner   | 2           | 200 ms     |
| Easy       | 6           | 500 ms     |
| Medium     | 12          | 1 s        |
| Hard       | 16          | 2 s        |
| Max        | 20          | 3 s        |

**Best for:** Chess and Xiangqi. Ruthlessly efficient at Max.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Server runtime | Node.js 20+ |
| Server language | TypeScript 5.3+ |
| WebSocket | `ws` 8.16 |
| Chess rules | `chess.js` 1.0 |
| Database | SQLite via `better-sqlite3` 9.4 |
| ID generation | `uuid` 9.0 |
| Frontend | Vanilla JS + HTML5 Canvas (no framework, no build) |
| AI bot | Python 3 + `websockets` |
| Chess engine | Stockfish |
| Xiangqi engine | Fairy-Stockfish |
| LLM AI | OpenClaw agent |

---

## Project Structure

```
lan-board-game-platform/
  apps/
    server/
      src/
        index.ts          # HTTP + WebSocket server (~840 lines)
        games/
          gomoku.ts        # 15×15 engine, 5-in-a-row detection
          chess.ts         # chess.js wrapper
          xiangqi.ts       # Full Xiangqi rules (palace, cannon, flying kings…)
      static/
        index.html         # Single-file browser client
    agent-player/
      euler_play.py        # Standalone AI bot (~1 067 lines)
  docs/
    RUNBOOK.md             # Operator quick-reference
  ISSUES.md                # Bug tracker
```

---

## Roadmap

Things that would be fun to build next:

- [ ] **LLM vs LLM mode** — pit two AI models against each other and watch the sparks fly
- [ ] **ELO rating system** — track skill over time across human and AI players
- [ ] **Game replay** — step through any match from history move by move
- [ ] **Multi-model arena** — round-robin tournament across different LLM providers
- [ ] **More games** — Reversi, Go (9×9 for starters), Checkers
- [ ] **Mobile-friendly layout** — the canvas works, the UI could be friendlier on small screens

---

## License

MIT
