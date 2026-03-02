import { WebSocketServer, WebSocket } from 'ws';
import { createServer, IncomingMessage, ServerResponse } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { v4 as uuidv4 } from 'uuid';
import { execFile, spawn } from 'child_process';
import Database from 'better-sqlite3';
import { GomokuGame, BLACK as GB, WHITE as GW } from './games/gomoku.js';
import { ChessGame } from './games/chess.js';
import { XiangqiGame } from './games/xiangqi.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 8765;

// ── DB ────────────────────────────────────────────────────────────────────────
const db = new Database('matches.db');
db.exec(`CREATE TABLE IF NOT EXISTS matches (
  id TEXT PRIMARY KEY, game_type TEXT, room_id TEXT,
  started_at TEXT, ended_at TEXT,
  player1 TEXT, player2 TEXT,
  winner TEXT, winner_reason TEXT,
  moves TEXT, chat TEXT, result TEXT
)`);

function saveMatch(r: any) {
  db.prepare(`INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(r.id, r.gameType, r.roomId, r.startedAt, r.endedAt,
      r.player1, r.player2, r.winner ?? null, r.winnerReason ?? null,
      JSON.stringify(r.moves ?? []), JSON.stringify(r.chat ?? []), r.result ?? '');
}
function listMatches() {
  return db.prepare('SELECT id,game_type,room_id,started_at,ended_at,player1,player2,winner,result FROM matches ORDER BY started_at DESC LIMIT 100').all();
}

// ── State ─────────────────────────────────────────────────────────────────────
const rooms: Map<string, any> = new Map();
const clients: Map<string, WebSocket> = new Map();
const clientRoom: Map<string, string> = new Map();

function makeRoom(gameType: string, hostId: string, hostNick: string) {
  const id = Math.random().toString(36).slice(2,8).toUpperCase();
  return { id, gameType, hostId, players: {} as Record<string,any>, state: 'waiting', game: null as any, matchId: null as any, startedAt: null, chat: [] as any[], moves: [] as any[], spectators: [] as string[], aiType: 'euler' as string, difficulty: 'medium' as string };
}

function roomSummary(room: any) {
  return { id: room.id, gameType: room.gameType, playerCount: Object.keys(room.players).length, state: room.state, players: Object.values(room.players).map((p:any) => ({ nick: p.nick, isAi: p.isAi })), aiType: room.aiType, difficulty: room.difficulty };
}

function addChat(room: any, nick: string, text: string, system = false) {
  const msg = { nick, text, system, ts: new Date().toISOString() };
  room.chat.push(msg);
  if (room.chat.length > 500) room.chat = room.chat.slice(-200);
  return msg;
}

async function broadcast(room: any, msg: any, exclude?: string) {
  const str = JSON.stringify(msg);
  for (const [pid, p] of Object.entries<any>(room.players)) {
    if (pid === exclude || p.isAi) continue;
    const ws = clients.get(pid);
    if (ws?.readyState === WebSocket.OPEN) ws.send(str);
  }
  for (const sid of room.spectators ?? []) {
    const ws = clients.get(sid);
    if (ws?.readyState === WebSocket.OPEN) ws.send(str);
  }
}

async function sendClient(clientId: string, msg: any) {
  const ws = clients.get(clientId);
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

async function sendRoomState(room: any, to?: string) {
  const msg = {
    type: 'room_state',
    room: {
      id: room.id, gameType: room.gameType, state: room.state, aiType: room.aiType, difficulty: room.difficulty,
      players: room.players,
      chat: room.chat.slice(-50),
      gameState: room.game?.stateDict() ?? null,
      moves: room.moves.slice(-100),
    }
  };
  if (to) await sendClient(to, msg); else await broadcast(room, msg);
}

function assignSides(room: any) {
  const pids = Object.keys(room.players).filter(id => !id.startsWith('AI_'));
  const aiPids = Object.keys(room.players).filter(id => id.startsWith('AI_'));
  const all = [...pids, ...aiPids];
  const sides: Record<string,string[]> = {
    chess: ['white','black'], gomoku: ['black','white'], xiangqi: ['red','black']
  };
  const s = sides[room.gameType] ?? ['first','second'];
  all.forEach((pid, i) => { if (room.players[pid]) room.players[pid].side = s[i] ?? s[s.length-1]; });
}

async function startMatch(room: any) {
  if (room.gameType === 'chess') room.game = new ChessGame();
  else if (room.gameType === 'gomoku') room.game = new GomokuGame();
  else room.game = new XiangqiGame();

  room.state = 'playing';
  room.matchId = uuidv4();
  room.startedAt = new Date().toISOString();
  room.moves = [];

  assignSides(room);

  const sides = Object.fromEntries(Object.entries<any>(room.players).map(([id,p]) => [id, p.side]));
  const sysMsg = addChat(room, 'System', `Match started! ${Object.values<any>(room.players).map((p:any) => `${p.nick}=${p.side}`).join(', ')}`, true);

  await broadcast(room, { type: 'match_start', sides, gameState: room.game.stateDict() });
  await broadcast(room, { type: 'chat', message: sysMsg });
  await sendRoomState(room);
  await maybeAiMove(room);
}

let aiTimers: Map<string, NodeJS.Timeout> = new Map();

async function maybeAiMove(room: any) {
  if (room.state !== 'playing' || !room.game || room.game.finished) return;
  const gt = room.gameType;
  const gs = room.game.stateDict();
  const curSide = gs.currentPlayer;
  const curSideName = gs.currentPlayerName ?? curSide;

  const aiEntry = Object.entries<any>(room.players).find(([id, p]) => p.isAi && (p.side === curSide || p.side === curSideName));
  if (!aiEntry) return;
  const [aiId, aiPlayer] = aiEntry;

  const old = aiTimers.get(room.id);
  if (old) clearTimeout(old);

  const delay = 500 + Math.random() * 1500;
  const timer = setTimeout(async () => {
    if (!room.game || room.game.finished || room.state !== 'playing') return;
    try {
      const move = await fetchAiMove(gt, room.game, curSide, room);
      if (!move) return;
      const result = room.game.applyMove(move);
      if (!result.ok) return;
      room.moves.push({ side: curSide, move, ts: Date.now() });
      const gs2 = room.game.stateDict();
      await broadcast(room, { type: 'move', side: curSide, move, gameState: gs2 });
      if (room.game.finished) await handleMatchEnd(room, result);
      else await maybeAiMove(room);
    } catch (e) { console.error('AI error:', e); }
  }, delay);
  aiTimers.set(room.id, timer);
}

async function fetchAiMove(gameType: string, game: any, side: string, room?: any): Promise<any> {
  // Engine mode: use Stockfish/Fairy-Stockfish for chess/xiangqi
  if (room?.aiType === 'engine' && (gameType === 'chess' || gameType === 'xiangqi')) {
    try {
      const move = await fetchEngineMove(gameType, game, room.difficulty ?? 'medium');
      if (move) {
        // Validate engine move against game's legal moves before using it
        const legal = game.legalMoves();
        let isLegal = false;
        if (gameType === 'chess') {
          isLegal = legal.includes(move.uci);
        } else {
          isLegal = legal.some((m: any) =>
            m.fromRow === move.fromRow && m.fromCol === move.fromCol &&
            m.toRow === move.toRow && m.toCol === move.toCol);
        }
        if (isLegal) return move;
        console.warn('Engine move rejected by game rules, using fallback AI');
      }
    } catch (e) { console.error('Engine error, falling back:', e); }
  }
  // Simple built-in AI (fallback)
  if (gameType === 'gomoku') return bestGomokuMove(game);
  if (gameType === 'chess') return bestChessMove(game);
  if (gameType === 'xiangqi') return bestXiangqiMove(game);
  return null;
}

function bestGomokuMove(game: any): any {
  const moves = game.legalMoves();
  if (!moves.length) return null;
  const board = game.board;
  const size = game.size;
  const player = game.currentPlayer;
  const opp = player === GB ? GW : GB;

  // Check for wins / blocks
  for (const move of moves) {
    board[move.row][move.col] = player;
    const won = game['checkWin']?.(move.row, move.col, player) ?? false;
    board[move.row][move.col] = 0;
    if (won) return move;
  }
  for (const move of moves) {
    board[move.row][move.col] = opp;
    const blocked = game['checkWin']?.(move.row, move.col, opp) ?? false;
    board[move.row][move.col] = 0;
    if (blocked) return move;
  }
  // Prefer center
  const center = size >> 1;
  const sorted = moves.sort((a: any, b: any) => {
    const da = Math.abs(a.row-center)+Math.abs(a.col-center);
    const db2 = Math.abs(b.row-center)+Math.abs(b.col-center);
    return da - db2;
  });
  return sorted[0] ?? moves[0];
}

function bestChessMove(game: any): any {
  const moves = game.legalMoves();
  if (!moves.length) return null;
  // Prefer captures: check if destination square is occupied via verbose moves
  const verboseMoves = game['chess']?.moves({ verbose: true }) ?? [];
  const captureUcis = new Set(verboseMoves.filter((m: any) => m.captured).map((m: any) => m.from + m.to + (m.promotion || '')));
  const captures = moves.filter((m: string) => captureUcis.has(m));
  const pool = captures.length ? captures : moves;
  const uci = pool[Math.floor(Math.random() * pool.length)];
  return { uci };
}

function bestXiangqiMove(game: any): any {
  const moves = game.legalMoves();
  if (!moves.length) return null;
  const captures = moves.filter((m: any) => game.get(m.toRow, m.toCol) !== ' ');
  return captures.length ? captures[Math.floor(Math.random()*captures.length)] : moves[Math.floor(Math.random()*moves.length)];
}

// ── Engine AI (Stockfish / Fairy-Stockfish) ─────────────────────────────────

const DIFFICULTY_SKILL: Record<string, number> = { beginner: 2, easy: 6, medium: 12, hard: 16, max: 20 };
const DIFFICULTY_TIME: Record<string, number> = { beginner: 200, easy: 500, medium: 1000, hard: 2000, max: 3000 };

function xiangqiBoardToFen(game: any): string {
  const board = game.board;
  const rows: string[] = [];
  // Reverse row order: our board[0]=Red top, but FEN rank 9 (first)=Black top
  for (let r = 9; r >= 0; r--) {
    let row = '';
    let empty = 0;
    for (let c = 0; c < 9; c++) {
      const p = board[r][c];
      if (p === ' ') { empty++; }
      else { if (empty > 0) { row += empty; empty = 0; } row += p; }
    }
    if (empty > 0) row += empty;
    rows.push(row);
  }
  const color = game.currentPlayer === 'red' ? 'w' : 'b';
  return `${rows.join('/')} ${color} - - 0 1`;
}

async function fetchEngineMove(gameType: string, game: any, difficulty: string): Promise<any> {
  const enginePath = gameType === 'chess' ? '/usr/games/stockfish' : '/usr/games/fairy-stockfish';
  const skill = DIFFICULTY_SKILL[difficulty] ?? 12;
  const moveTime = DIFFICULTY_TIME[difficulty] ?? 1000;

  let fen: string;
  if (gameType === 'chess') {
    fen = game['chess'].fen();
  } else if (gameType === 'xiangqi') {
    fen = xiangqiBoardToFen(game);
  } else {
    return null;
  }

  return new Promise((resolve, reject) => {
    const proc = spawn(enginePath, [], { stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '';
    let resolved = false;

    const timer = setTimeout(() => {
      if (!resolved) { resolved = true; proc.kill(); reject(new Error('Engine timeout')); }
    }, 15000);

    proc.stderr.on('data', () => {}); // drain stderr to prevent pipe deadlock
    proc.stdout.on('data', (data: Buffer) => {
      output += data.toString();
      if (output.includes('bestmove') && !resolved) {
        const match = output.match(/bestmove\s+(\S+)/);
        if (match) {
          resolved = true;
          clearTimeout(timer);
          const uciMove = match[1];
          try { proc.stdin.write('quit\n'); } catch {}
          proc.kill();
          if (gameType === 'chess') {
            resolve({ uci: uciMove });
          } else {
            // Xiangqi: fairy-stockfish uses 1-indexed ranks (1-10), parse with regex
            const m = uciMove.match(/^([a-i])(\d+)([a-i])(\d+)$/);
            if (m) {
              const fromCol = m[1].charCodeAt(0) - 97;
              const fromRow = parseInt(m[2]) - 1; // 1-indexed to 0-indexed
              const toCol = m[3].charCodeAt(0) - 97;
              const toRow = parseInt(m[4]) - 1;
              resolve({ fromRow, fromCol, toRow, toCol });
            } else {
              reject(new Error(`Invalid xiangqi UCI move: ${uciMove}`));
            }
          }
        }
      }
    });

    proc.on('error', (err) => {
      if (!resolved) { resolved = true; clearTimeout(timer); reject(err); }
    });
    proc.on('exit', () => {
      if (!resolved) { resolved = true; clearTimeout(timer); reject(new Error('Engine exited without bestmove')); }
    });

    let cmds = 'uci\n';
    if (gameType === 'xiangqi') cmds += 'setoption name UCI_Variant value xiangqi\n';
    cmds += `setoption name Skill Level value ${skill}\n`;
    cmds += 'isready\n';
    cmds += `position fen ${fen}\n`;
    cmds += `go movetime ${moveTime}\n`;
    proc.stdin.write(cmds);
  });
}

async function handleMatchEnd(room: any, result: any) {
  room.state = 'finished';
  const game = room.game;
  const endedAt = new Date().toISOString();

  let winner = result.winner ?? game.winner ?? null;
  // Gomoku stores winner as 1/2 (number) — convert to side name
  if (winner === 1 || winner === 2) {
    const sides = Object.entries<any>(room.players).find(([,p]) => true)?.[1]?.side;
    // Find player with this number
    const winnerEntry = Object.values<any>(room.players).find((p:any) => {
      if (p.side === 'black' && winner === 1) return true;
      if (p.side === 'white' && winner === 2) return true;
      return false;
    });
    winner = winnerEntry?.side ?? (winner === 1 ? 'black' : 'white');
  }
  const draw = result.draw ?? false;
  const reason = result.reason ?? game.winnerReason ?? 'unknown';

  const allPlayers = Object.values<any>(room.players);
  const p1 = allPlayers[0];
  const p2 = allPlayers[1];
  const resultStr = draw ? `Draw (${reason})` : winner ? `${winner} wins (${reason})` : 'Unknown';

  saveMatch({
    id: room.matchId, gameType: room.gameType, roomId: room.id,
    startedAt: room.startedAt, endedAt,
    player1: p1?.nick ?? '?', player2: p2?.nick ?? '?',
    winner: winner?.toString() ?? null, winnerReason: reason,
    moves: room.moves, chat: room.chat, result: resultStr,
  });

  // AI end chat
  for (const p of Object.values<any>(room.players)) {
    if (p.isAi) {
      const won = p.side === String(winner);
      const msg2 = addChat(room, p.nick, won ? 'GG! Well played!' : 'Good game! Rematch?');
      await broadcast(room, { type: 'chat', message: msg2 });
    }
  }
  const sysMsg = addChat(room, 'System', `Match over: ${resultStr}`, true);
  await broadcast(room, { type: 'chat', message: sysMsg });
  await broadcast(room, { type: 'match_end', result: resultStr, winner: winner?.toString() ?? null, draw, reason, gameState: game.stateDict(), matchId: room.matchId });
}

async function handleLeave(clientId: string, nick: string) {
  const roomId = clientRoom.get(clientId);
  clientRoom.delete(clientId);
  if (!roomId) return;
  const room = rooms.get(roomId);
  if (!room) return;

  if (room.state === 'playing' && room.players[clientId]) {
    const side = room.players[clientId].side;
    const result = room.game?.resign?.(side) ?? { ok: true, winner: null, reason: 'disconnect' };
    await handleMatchEnd(room, { ...result, reason: 'disconnect' });
  }
  delete room.players[clientId];
  room.spectators = room.spectators?.filter((s: string) => s !== clientId) ?? [];

  const humans = Object.keys(room.players).filter(id => !id.startsWith('AI_'));
  if (humans.length === 0) {
    const t = aiTimers.get(roomId); if (t) clearTimeout(t); aiTimers.delete(roomId);
    // Grace period: keep room alive 60s in case player refreshes
    setTimeout(() => {
      const r2 = rooms.get(roomId);
      if (r2 && Object.keys(r2.players).filter(id => !id.startsWith('AI_')).length === 0) {
        rooms.delete(roomId);
        broadcastRoomsUpdate();
      }
    }, 60_000);
  } else {
    const msg = addChat(room, 'System', `${nick} left the room.`, true);
    await broadcast(room, { type: 'chat', message: msg });
    await broadcast(room, { type: 'player_left', nick });
  }
  broadcastRoomsUpdate();
}

function broadcastRoomsUpdate() {
  const list = Array.from(rooms.values()).map(roomSummary);
  const msg = JSON.stringify({ type: 'rooms_list', rooms: list });
  for (const [cid, ws] of clients) {
    if (!clientRoom.has(cid) && ws.readyState === WebSocket.OPEN) ws.send(msg);
  }
}

// ── API helpers ──────────────────────────────────────────────────────────────

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > 1_000_000) { reject(new Error('body too large')); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
    req.on('error', reject);
  });
}

function jsonResponse(res: ServerResponse, status: number, data: any) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' });
  res.end(JSON.stringify(data));
}

function callOpenclawAgent(sessionId: string, message: string, timeout: number): Promise<any> {
  return new Promise((resolve, reject) => {
    const args = ['agent', '--session-id', sessionId, '--message', message, '--json', '--timeout', String(timeout)];
    const child = execFile('openclaw', args, { timeout: (timeout + 5) * 1000 }, (err, stdout, stderr) => {
      if (err) { reject(new Error(stderr?.slice(0, 200) || err.message)); return; }
      try {
        const result = JSON.parse(stdout);
        const payloads = result?.result?.payloads ?? [];
        const text = payloads[0]?.text ?? '';
        resolve(text);
      } catch (e) {
        reject(new Error('Failed to parse openclaw response'));
      }
    });
  });
}

function boardToCompactGrid(board: number[][], size: number): string {
  const lines: string[] = ['   ' + Array.from({length: size}, (_, i) => String(i).padStart(2)).join(' ')];
  for (let r = 0; r < size; r++) {
    let row = String(r).padStart(2) + ' ';
    for (let c = 0; c < size; c++) {
      const cell = board[r][c];
      row += cell === 1 ? ' X ' : cell === 2 ? ' O ' : ' . ';
    }
    lines.push(row);
  }
  return lines.join('\n');
}

async function handleApiMove(req: IncomingMessage, res: ServerResponse) {
  try {
    const body = JSON.parse(await readBody(req));
    const { board, size, currentPlayer, currentPlayerName, moveCount, gameType, side } = body;

    if (!Array.isArray(board) || typeof size !== 'number' || size < 1 || size > 19 || gameType !== 'gomoku') {
      jsonResponse(res, 400, { error: 'Invalid request: gomoku board (array) and valid size required' });
      return;
    }

    const grid = boardToCompactGrid(board, size);
    const mySymbol = side === 'black' || currentPlayer === 1
      ? 'X (black, player 1)' : 'O (white, player 2)';

    const prompt = `You are playing Gomoku on a ${size}x${size} board. Get 5 in a row to win.
You are: ${mySymbol}. Move #${(moveCount ?? 0) + 1}.
Board (X=black, O=white, .=empty):
${grid}
Reply with ONLY your move as: row,col`;

    try {
      const reply = await callOpenclawAgent('euler-gomoku-moves', prompt, 30);
      const match = reply.match(/(\d+)\s*[,\s]\s*(\d+)/);
      if (match) {
        const row = parseInt(match[1]), col = parseInt(match[2]);
        if (row >= 0 && row < size && col >= 0 && col < size && board[row][col] === 0) {
          jsonResponse(res, 200, { row, col });
          return;
        }
      }
      jsonResponse(res, 200, { error: 'AI returned invalid move, use fallback', raw: reply });
    } catch (e: any) {
      jsonResponse(res, 200, { error: `AI unavailable: ${e.message}` });
    }
  } catch (e: any) {
    jsonResponse(res, 400, { error: `Bad request: ${e.message}` });
  }
}

const CHAT_SYSTEM_CONTEXT = 'You are Euler, playing a board game. Keep replies SHORT (1-2 sentences), playful, competitive. Use emojis sparingly.';

async function handleApiChat(req: IncomingMessage, res: ServerResponse) {
  try {
    const body = JSON.parse(await readBody(req));
    const { text, gameContext, gameType } = body;

    if (!text || typeof text !== 'string') {
      jsonResponse(res, 400, { error: 'text is required' });
      return;
    }
    const safeText = text.slice(0, 500);

    const message = gameContext
      ? `[Context: ${CHAT_SYSTEM_CONTEXT}] [Game: ${String(gameContext).slice(0, 200)}]\n${safeText}`
      : `[Context: ${CHAT_SYSTEM_CONTEXT}]\n${safeText}`;

    try {
      const reply = await callOpenclawAgent('euler-gomoku-game', message, 30);
      if (!reply || reply.trim() === '' || reply.trim() === 'NO_REPLY' || reply.trim() === 'HEARTBEAT_OK') {
        jsonResponse(res, 200, { reply: null });
        return;
      }
      const trimmed = reply.trim().slice(0, 200);
      jsonResponse(res, 200, { reply: trimmed });
    } catch {
      jsonResponse(res, 200, { reply: null });
    }
  } catch (e: any) {
    jsonResponse(res, 400, { error: `Bad request: ${e.message}` });
  }
}

// ── HTTP server (serve static files + API) ───────────────────────────────────
const staticDir = join(__dirname, '..', 'static');

const httpServer = createServer((req, res) => {
  // No-cache headers for all responses
  const noCacheHeaders = {
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0'
  };

  if (req.url === '/api/history') {
    res.writeHead(200, { 'Content-Type': 'application/json', ...noCacheHeaders });
    res.end(JSON.stringify(listMatches()));
    return;
  }
  if (req.method === 'POST' && req.url === '/api/move') {
    handleApiMove(req, res);
    return;
  }
  if (req.method === 'POST' && req.url === '/api/chat') {
    handleApiChat(req, res);
    return;
  }
  // Serve static — resolve and verify path stays within staticDir
  const rawPath = decodeURIComponent((req.url === '/' ? '/index.html' : (req.url ?? '/index.html')).split('?')[0]);
  const filePath = resolve(staticDir, rawPath.replace(/^\/+/, ''));
  if (!filePath.startsWith(staticDir)) { res.writeHead(403); res.end('Forbidden'); return; }
  try {
    const content = readFileSync(filePath);
    const ext = filePath.split('.').pop();
    const ct: Record<string,string> = { html: 'text/html', js: 'application/javascript', css: 'text/css', png: 'image/png', svg: 'image/svg+xml', ico: 'image/x-icon', json: 'application/json' };
    res.writeHead(200, { 'Content-Type': ct[ext ?? ''] ?? 'application/octet-stream', ...noCacheHeaders });
    res.end(content);
  } catch {
    const idx = join(staticDir, 'index.html');
    if (existsSync(idx)) { res.writeHead(200, { 'Content-Type': 'text/html', ...noCacheHeaders }); res.end(readFileSync(idx)); }
    else { res.writeHead(404); res.end('Not found'); }
  }
});

// ── WebSocket ─────────────────────────────────────────────────────────────────
const wss = new WebSocketServer({ server: httpServer });

wss.on('connection', (ws) => {
  const clientId = uuidv4();
  let nick = 'Anonymous';
  clients.set(clientId, ws);

  ws.on('message', async (data) => {
    let msg: any;
    try { msg = JSON.parse(data.toString()); } catch { return; }
    const type = msg.type;

    if (type === 'identify') {
      nick = String(msg.nick ?? 'Anonymous').replace(/[<>&"']/g, '').slice(0, 30).trim() || 'Anonymous';
      ws.send(JSON.stringify({ type: 'identified', clientId, nick }));
      ws.send(JSON.stringify({ type: 'rooms_list', rooms: Array.from(rooms.values()).map(roomSummary) }));
      return;
    }

    if (type === 'get_rooms') {
      ws.send(JSON.stringify({ type: 'rooms_list', rooms: Array.from(rooms.values()).map(roomSummary) }));
      return;
    }

    if (type === 'create_room') {
      const gt = msg.gameType ?? 'gomoku';
      if (!['chess','gomoku','xiangqi'].includes(gt)) { ws.send(JSON.stringify({ type: 'error', msg: 'invalid game type' })); return; }
      const room = makeRoom(gt, clientId, nick);
      if (msg.aiType && ['euler', 'engine'].includes(msg.aiType)) room.aiType = msg.aiType;
      if (msg.difficulty && ['beginner', 'easy', 'medium', 'hard', 'max'].includes(msg.difficulty)) room.difficulty = msg.difficulty;
      rooms.set(room.id, room);
      room.players[clientId] = { nick, ready: false, isAi: false, side: null };
      room.spectators = [];
      clientRoom.set(clientId, room.id);
      addChat(room, 'System', `${nick} created the room.`, true);
      ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id }));
      await sendRoomState(room, clientId);
      broadcastRoomsUpdate();
      if (msg.withAi) {
        const aiId = `AI_${room.id}`;
        const aiNick = room.aiType === 'engine' ? `Engine (${room.difficulty}) ⚙️` : ['Euler 🤖','AI-Chan 🤖','DeepMove 🤖'][Math.floor(Math.random()*3)];
        room.players[aiId] = { nick: aiNick, ready: true, isAi: true, side: null };
        room.players[clientId].ready = true;
        const aiMsg = addChat(room, 'System', `${aiNick} (AI) joined.`, true);
        const aiChat = addChat(room, aiNick, 'Let\'s play! Good luck 🎮');
        await broadcast(room, { type: 'chat', message: aiMsg });
        await broadcast(room, { type: 'chat', message: aiChat });
        await startMatch(room);
      }
      return;
    }

    if (type === 'join_room') {
      const room = rooms.get(msg.roomId);
      if (!room) { ws.send(JSON.stringify({ type: 'error', msg: 'room not found' })); return; }
      const humanCount = Object.values<any>(room.players).filter((p:any) => !p.isAi).length;
      if (humanCount >= 2 || room.state !== 'waiting') { ws.send(JSON.stringify({ type: 'error', msg: 'room full or in progress' })); return; }
      room.players[clientId] = { nick, ready: false, isAi: false, side: null };
      clientRoom.set(clientId, room.id);
      const joinMsg = addChat(room, 'System', `${nick} joined.`, true);
      ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id }));
      await broadcast(room, { type: 'chat', message: joinMsg });
      await sendRoomState(room);
      broadcastRoomsUpdate();
      return;
    }

    if (type === 'spectate_room') {
      const room = rooms.get(msg.roomId);
      if (!room) { ws.send(JSON.stringify({ type: 'error', msg: 'room not found' })); return; }
      room.spectators = room.spectators ?? [];
      if (!room.spectators.includes(clientId)) room.spectators.push(clientId);
      clientRoom.set(clientId, room.id);
      ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id, spectator: true }));
      await sendRoomState(room, clientId);
      return;
    }

    if (type === 'ready') {
      const roomId = clientRoom.get(clientId);
      const room = rooms.get(roomId ?? '');
      if (!room || !room.players[clientId] || room.state !== 'waiting') return;
      room.players[clientId].ready = !room.players[clientId].ready;
      const readyMsg = addChat(room, 'System', `${nick} is ${room.players[clientId].ready ? 'ready' : 'not ready'}.`, true);
      await broadcast(room, { type: 'chat', message: readyMsg });
      await broadcast(room, { type: 'player_ready', nick, ready: room.players[clientId].ready });
      // auto-start if all ready and 2 players
      const allPlayers = Object.values<any>(room.players);
      if (allPlayers.length === 2 && allPlayers.every((p:any) => p.ready)) await startMatch(room);
      else await sendRoomState(room);
      return;
    }

    if (type === 'move') {
      const roomId = clientRoom.get(clientId);
      const room = rooms.get(roomId ?? '');
      if (!room || room.state !== 'playing') { ws.send(JSON.stringify({ type: 'error', msg: 'not in active match' })); return; }
      const player = room.players[clientId];
      if (!player) return;
      const gs = room.game.stateDict();
      // Compare side: gomoku uses numbers (1=black,2=white), chess/xiangqi uses strings
      const curName = gs.currentPlayerName ?? gs.currentPlayer;
      if (player.side !== gs.currentPlayer && player.side !== curName) { ws.send(JSON.stringify({ type: 'error', msg: 'not your turn' })); return; }
      const result = room.game.applyMove(msg.move);
      if (!result.ok) { ws.send(JSON.stringify({ type: 'error', msg: result.reason })); return; }
      room.moves.push({ side: player.side, move: msg.move, ts: Date.now() });
      await broadcast(room, { type: 'move', side: player.side, move: msg.move, gameState: room.game.stateDict() });
      if (room.game.finished) await handleMatchEnd(room, result);
      else await maybeAiMove(room);
      return;
    }

    if (type === 'resign') {
      const roomId = clientRoom.get(clientId);
      const room = rooms.get(roomId ?? '');
      if (!room || room.state !== 'playing') return;
      const player = room.players[clientId];
      if (!player) return;
      const result = room.game.resign?.(player.side) ?? { ok: true, winner: null, reason: 'resignation' };
      if (result.ok) { room.moves.push({ side: player.side, move: 'resign', ts: Date.now() }); await handleMatchEnd(room, result); }
      return;
    }

    if (type === 'chat') {
      const roomId = clientRoom.get(clientId);
      const room = rooms.get(roomId ?? '');
      if (!room) return;
      const text = String(msg.text ?? '').slice(0, 300).trim();
      if (!text) return;
      const chatMsg = addChat(room, nick, text);
      await broadcast(room, { type: 'chat', message: chatMsg });
      return;
    }

    if (type === 'play_again') {
      const roomId = clientRoom.get(clientId);
      const room = rooms.get(roomId ?? '');
      if (!room) return;
      room.state = 'waiting'; room.game = null; room.matchId = null; room.startedAt = null; room.moves = [];
      for (const p of Object.values<any>(room.players)) { p.ready = p.isAi ? true : false; p.side = null; }
      const resetMsg = addChat(room, 'System', 'Room reset. Ready up for a new match!', true);
      await broadcast(room, { type: 'chat', message: resetMsg });
      await sendRoomState(room);
      broadcastRoomsUpdate();
      return;
    }

    if (type === 'leave_room') { await handleLeave(clientId, nick); return; }
    if (type === 'get_history') { ws.send(JSON.stringify({ type: 'history', matches: listMatches() })); return; }
  });

  ws.on('close', () => { clients.delete(clientId); handleLeave(clientId, nick); });
  ws.on('error', () => { clients.delete(clientId); handleLeave(clientId, nick); });
});

httpServer.listen(PORT, '0.0.0.0', () => {
  console.log(`🎮 LAN Board Game Platform running on http://0.0.0.0:${PORT}`);
});
