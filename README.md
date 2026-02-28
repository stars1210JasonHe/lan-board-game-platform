# LAN Board Game Platform

A real-time multiplayer board game platform for LAN play, supporting Gomoku, Chess, and Xiangqi (Chinese Chess). Features an AI bot player powered by OpenClaw agent.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Browser Client                    │
│                 (static/index.html)                  │
│         Gomoku / Chess / Xiangqi rendering           │
└──────────────┬──────────────────────┬───────────────┘
               │ WebSocket            │ HTTP
               │ (game events)        │ (static files)
               ▼                      ▼
┌─────────────────────────────────────────────────────┐
│              Game Server (Node.js)                   │
│              apps/server/src/index.ts                │
│                                                      │
│  WebSocket: rooms, moves, chat, spectating           │
│  HTTP API:  /api/move  (AI move via OpenClaw)        │
│             /api/chat  (AI chat via OpenClaw)        │
│             /api/history (match history)              │
│                                                      │
│  Game engines: gomoku.ts, chess.ts, xiangqi.ts       │
│  Database: SQLite (matches.db)                       │
└──────────────┬──────────────────────────────────────┘
               │ WebSocket
               ▼
┌─────────────────────────────────────────────────────┐
│           AI Bot Client (Python)                     │
│         apps/agent-player/euler_play.py              │
│                                                      │
│  Connects as a player via WebSocket                  │
│  Moves: /api/move → OpenClaw agent → fallback algo   │
│  Chat:  /api/chat → OpenClaw agent → canned replies  │
└─────────────────────────────────────────────────────┘
```

## How to Run

### 1. Start the Game Server

```bash
cd apps/server
npm install
npm run build
npm start
# Server runs on http://0.0.0.0:8765
```

For development with auto-reload:

```bash
npm run dev
```

### 2. Open the Game in a Browser

Navigate to `http://<server-ip>:8765` on any device on your LAN.

### 3. Run the AI Bot (optional)

```bash
cd apps/agent-player
pip install websockets  # if not installed

# List open rooms
python3 euler_play.py --list --host <server-ip>

# Join a room
python3 euler_play.py <ROOM_ID> --host <server-ip>

# Join without AI chat (canned replies only)
python3 euler_play.py <ROOM_ID> --host <server-ip> --no-ai-chat
```

## API Endpoints

### `GET /api/history`

Returns the last 100 matches.

### `POST /api/move`

Request an AI-generated move (Gomoku only, uses OpenClaw agent).

**Request:**
```json
{
  "board": [[0,0,...], ...],
  "size": 15,
  "currentPlayer": 1,
  "currentPlayerName": "black",
  "moveCount": 5,
  "gameType": "gomoku",
  "side": "black"
}
```

**Response:**
```json
{ "row": 7, "col": 7 }
```

On failure (fallback to local algorithm):
```json
{ "error": "AI unavailable: ..." }
```

### `POST /api/chat`

Request an AI chat reply (uses OpenClaw agent).

**Request:**
```json
{
  "text": "Good move!",
  "gameContext": "game=gomoku, moves=12",
  "gameType": "gomoku"
}
```

**Response:**
```json
{ "reply": "Thanks! Your turn 😄" }
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Server port | `8765` | Set in `apps/server/src/index.ts` |
| `--host` | `localhost` | Bot: game server hostname |
| `--port` | `8765` | Bot: game server port |
| `--no-ai-chat` | off | Bot: disable AI chat, use canned replies |
| `--list` | — | Bot: list open rooms and exit |

## Supported Games

- **Gomoku** — 15x15 board, get 5 in a row to win
- **Chess** — Standard chess (via chess.js)
- **Xiangqi** — Chinese chess
