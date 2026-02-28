# LAN Board Game Platform

A real-time multiplayer board game platform for local network play. Supports **Gomoku**, **Chess**, and **Xiangqi** (Chinese Chess) with an optional AI opponent powered by OpenClaw.

## Architecture

```
 Browser (any device on LAN)
 +-----------------------------------------+
 |  Single-page app (Canvas + WebSocket)   |
 |  Gomoku / Chess / Xiangqi rendering     |
 +-------------------+---------------------+
                     | WS + HTTP
                     v
 Game Server (Node.js / TypeScript)
 +-----------------------------------------+
 |  WebSocket: rooms, moves, chat, spectate|
 |  HTTP API:  /api/move, /api/chat,       |
 |             /api/history                 |
 |  Engines:   gomoku.ts chess.ts xiangqi.ts|
 |  Database:  SQLite (matches.db)         |
 +-------------------+---------------------+
                     | WS
                     v
 AI Bot Client (Python, optional)
 +-----------------------------------------+
 |  euler_play.py                          |
 |  Moves via /api/move or local algorithm |
 |  Chat via /api/chat or canned replies   |
 +-----------------------------------------+
```

## Project Structure

```
lan-board-game-platform/
  apps/
    server/
      src/
        index.ts              # Main server (HTTP + WebSocket)
        games/
          gomoku.ts           # Gomoku engine (15x15, 5-in-a-row)
          chess.ts            # Chess engine (chess.js wrapper)
          xiangqi.ts          # Xiangqi engine (full rules)
      static/
        index.html            # Browser client (SPA)
      package.json
      tsconfig.json
    agent-player/
      euler_play.py           # AI bot client
  docs/
    RUNBOOK.md                # Quick-start guide
  README.md
```

## Quick Start

### 1. Start the Server

```bash
cd apps/server
npm install
npm run build
npm start
# Server: http://0.0.0.0:8765
```

Development mode (auto-reload):

```bash
npm run dev
```

### 2. Play in Browser

Open `http://<server-ip>:8765` on any device on the same network.

- Enter a nickname
- Pick a game type (Gomoku, Chess, or Xiangqi)
- Click **Create Room** for PvP, or **vs AI** for single-player
- Both players click **Ready** to start

### 3. Run the AI Bot (Optional)

```bash
cd apps/agent-player
pip install websockets

# List open rooms
python3 euler_play.py --list --host <server-ip>

# Join a specific room
python3 euler_play.py <ROOM_ID> --host <server-ip>

# Disable AI chat (use canned replies)
python3 euler_play.py <ROOM_ID> --host <server-ip> --no-ai-chat
```

## Supported Games

| Game | Board | Win Condition | Engine |
|------|-------|---------------|--------|
| **Gomoku** | 15x15 grid | Get 5 stones in a row | Custom TypeScript |
| **Chess** | 8x8 board | Checkmate opponent's king | chess.js library |
| **Xiangqi** | 10x9 board | Checkmate opponent's general | Custom TypeScript |

## API Endpoints

### `GET /api/history`

Returns the last 100 completed matches.

**Response:** `200 OK`
```json
[
  {
    "id": "uuid",
    "game_type": "gomoku",
    "room_id": "ABC123",
    "started_at": "2026-02-28T10:00:00.000Z",
    "ended_at": "2026-02-28T10:15:00.000Z",
    "player1": "Alice",
    "player2": "ChessBot",
    "winner": "black",
    "result": "black wins (5-in-a-row)"
  }
]
```

### `POST /api/move`

Request an AI-generated move (Gomoku only). Uses OpenClaw agent with local algorithm fallback.

**Request:**
```json
{
  "board": [[0,0,0,...], ...],
  "size": 15,
  "currentPlayer": 1,
  "currentPlayerName": "black",
  "moveCount": 5,
  "gameType": "gomoku",
  "side": "black"
}
```

**Response (success):** `200 OK`
```json
{ "row": 7, "col": 7 }
```

**Response (AI unavailable):** `200 OK`
```json
{ "error": "AI unavailable: timeout" }
```

### `POST /api/chat`

Request an AI chat reply. Uses OpenClaw agent with null fallback.

**Request:**
```json
{
  "text": "Good move!",
  "gameContext": "game=gomoku, moves=12",
  "gameType": "gomoku"
}
```

**Response:** `200 OK`
```json
{ "reply": "Thanks! Your turn" }
```

Returns `{ "reply": null }` when AI is unavailable.

## WebSocket Protocol

The browser and bot clients communicate with the server over WebSocket (`ws://<host>:8765`).

### Client Messages

| Type | Fields | Description |
|------|--------|-------------|
| `identify` | `nick` | Set player nickname |
| `create_room` | `gameType`, `withAi?` | Create a new room |
| `join_room` | `roomId` | Join an existing room |
| `spectate_room` | `roomId` | Watch a room (read-only) |
| `ready` | — | Toggle ready status |
| `move` | `move` | Submit a move (format varies by game) |
| `resign` | — | Resign current match |
| `chat` | `text` | Send a chat message (max 300 chars) |
| `play_again` | — | Reset room for new match |
| `leave_room` | — | Leave current room |
| `get_rooms` | — | Request room list |
| `get_history` | — | Request match history |

### Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `identified` | `clientId`, `nick` | Identity confirmed |
| `rooms_list` | `rooms[]` | List of available rooms |
| `room_joined` | `roomId` | Room join confirmed |
| `room_state` | `room` | Full room state update |
| `match_start` | `sides`, `gameState` | Match started with side assignments |
| `move` | `side`, `move`, `gameState` | A move was made |
| `match_end` | `winner`, `draw`, `reason`, `result` | Match finished |
| `chat` | `message` | Chat message |
| `player_ready` | `nick`, `ready` | Player readiness changed |
| `player_left` | `nick` | Player disconnected |
| `error` | `msg` | Error message |

### Move Formats

- **Gomoku:** `{ row: number, col: number }`
- **Chess:** `{ uci: string }` (e.g., `"e2e4"`, `"e7e8q"` for promotion)
- **Xiangqi:** `{ fromRow, fromCol, toRow, toCol }`

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Server port | `8765` | Set in `apps/server/src/index.ts` |
| `--host` | `localhost` | Bot: game server hostname |
| `--port` | `8765` | Bot: game server port |
| `--no-ai-chat` | off | Bot: use canned replies instead of AI |
| `--list` | — | Bot: list open rooms and exit |

## Tech Stack

- **Server:** Node.js + TypeScript, WebSocket (`ws`), SQLite (`better-sqlite3`)
- **Frontend:** Vanilla JS, HTML5 Canvas (no build step)
- **Chess rules:** chess.js
- **AI bot:** Python 3 + `websockets`
- **AI integration:** OpenClaw agent (optional, with local fallbacks)

## Security

- Nicknames are sanitized server-side (HTML-special characters stripped, 30-char limit)
- All user-generated content is HTML-escaped on the client before rendering
- Static file serving uses `path.resolve()` containment to prevent path traversal
- Request body size limited to 1 MB
- Chat messages truncated to 300 characters (WebSocket) / 500 characters (API)
- Game type validated against whitelist (`gomoku`, `chess`, `xiangqi`)
- Move validation is server-authoritative (clients cannot cheat)
- OpenClaw subprocess calls use `execFile` (not `exec`) with timeouts

## Development

```bash
cd apps/server
npm install
npm run dev    # TypeScript watch mode with tsx
```

The frontend is a single HTML file (`apps/server/static/index.html`) with embedded CSS and JS. No build step required - just edit and refresh.

## License

Private / Internal use.
