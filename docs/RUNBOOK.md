# LAN Board Game Platform — Runbook

## Quick Start

```bash
cd apps/server
npm install
npm run build
node dist/index.js
```

Server runs on port **8765**.

## LAN Setup

1. Run the server on one machine (Linux/Mac/Windows)
2. Find the host IP: `ip addr` (Linux) or `ipconfig` (Windows)
3. Other players open: `http://<host-ip>:8765` in their browser
4. Set nickname → Create or Join a room → Ready up → Play!

## Game Types

- **Gomoku** — 15×15 board, 5-in-a-row wins
- **Chess** — Standard international chess
- **Xiangqi** — Chinese chess

## AI Opponent

- Click "vs AI" when creating a room
- AI auto-readies and moves with human-like delay (0.5–2s)

## Match History

- Stored in `matches.db` (SQLite)
- API: `GET http://localhost:8765/api/history`

## Ports

| Service | Port |
|---|---|
| Game server + web UI | 8765 |
