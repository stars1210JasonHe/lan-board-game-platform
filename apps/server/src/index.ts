import dotenv from 'dotenv';
dotenv.config();

import { WebSocketServer, WebSocket } from 'ws';
import { createServer, IncomingMessage, ServerResponse } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { v4 as uuidv4 } from 'uuid';
import { spawn } from 'child_process';
import { llmChat, getSkill } from './llm.js';
import Database from 'better-sqlite3';
import { GomokuGame, BLACK as GB, WHITE as GW } from './games/gomoku.js';
import { ChessGame } from './games/chess.js';
import { XiangqiGame } from './games/xiangqi.js';
import { Chess } from 'chess.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '8765', 10);

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
function listRoomMatches(roomId: string) {
  return db.prepare('SELECT id,game_type,started_at,ended_at,player1,player2,winner,result,moves FROM matches WHERE room_id=? ORDER BY started_at DESC LIMIT 20').all(roomId);
}

// ── Nick deduplication ────────────────────────────────────────────────────────
function getUniqueNick(room: any, proposedNick: string, excludeId?: string): string {
  const existing = new Set(
    Object.entries<any>(room.players)
      .filter(([id]) => id !== excludeId)
      .map(([, p]) => p.nick)
  );
  if (!existing.has(proposedNick)) return proposedNick;
  let i = 2;
  while (existing.has(`${proposedNick}_${i}`)) i++;
  return `${proposedNick}_${i}`;
}

// ── State ─────────────────────────────────────────────────────────────────────
const rooms: Map<string, any> = new Map();
const clients: Map<string, WebSocket> = new Map();
const clientRoom: Map<string, string> = new Map();

function makeRoom(gameType: string, hostId: string, hostNick: string) {
  const id = Math.random().toString(36).slice(2,8).toUpperCase();
  return { id, gameType, hostId, players: {} as Record<string,any>, state: 'waiting', game: null as any, matchId: null as any, startedAt: null, chat: [] as any[], moves: [] as any[], spectators: [] as string[], aiType: 'euler' as string, difficulty: 'medium' as string, preferredSide: 'random' as string, swapSides: false };
}

function roomSummary(room: any) {
  return { id: room.id, gameType: room.gameType, playerCount: Object.keys(room.players).length, state: room.state, players: Object.values(room.players).map((p:any) => ({ nick: p.nick, isAi: p.isAi })), aiType: room.aiType, difficulty: room.difficulty };
}

function addChat(room: any, nick: string, text: string, system = false) {
  const msg: any = { nick, text, system, ts: new Date().toISOString() };
  room.chat.push(msg);
  if (room.chat.length > 500) room.chat = room.chat.slice(-200);
  return msg;
}

async function broadcast(room: any, msg: any, exclude?: string) {
  const str = JSON.stringify(msg);
  for (const [pid, p] of Object.entries<any>(room.players)) {
    if (pid === exclude || p.isAi) continue;
    try {
      const ws = clients.get(pid);
      if (ws?.readyState === WebSocket.OPEN) ws.send(str);
    } catch (e) { console.error(`broadcast send error to ${pid}:`, e); }
  }
  for (const sid of room.spectators ?? []) {
    try {
      const ws = clients.get(sid);
      if (ws?.readyState === WebSocket.OPEN) ws.send(str);
    } catch (e) { console.error(`broadcast send error to spectator ${sid}:`, e); }
  }
}

async function sendClient(clientId: string, msg: any) {
  try {
    const ws = clients.get(clientId);
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  } catch (e) { console.error(`sendClient error to ${clientId}:`, e); }
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
      matchHistory: listRoomMatches(room.id),
    }
  };
  if (to) await sendClient(to, msg); else await broadcast(room, msg);
}

function assignSides(room: any) {
  let pids = Object.keys(room.players).filter(id => !id.startsWith('AI_'));
  const aiPids = Object.keys(room.players).filter(id => id.startsWith('AI_'));
  const sides: Record<string,string[]> = {
    chess: ['white','black'], gomoku: ['black','white'], xiangqi: ['red','black']
  };
  const s = sides[room.gameType] ?? ['first','second'];
  // Apply preferredSide: host (pids[0]) gets their preferred position
  if (room.preferredSide === 'second') {
    pids = [...pids].reverse();
  } else if (room.preferredSide === 'random') {
    for (let i = pids.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [pids[i], pids[j]] = [pids[j], pids[i]];
    }
  }
  let all: string[] = [...pids, ...aiPids];
  // swapSides toggles each rematch — reverse the full assignment
  if (room.swapSides) all = [...all].reverse();
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

  const gameState = room.game.stateDict();
  for (const [pid, p] of Object.entries<any>(room.players)) {
    if (p.isAi) continue;
    await sendClient(pid, { type: 'match_start', sides, yourSide: p.side, gameState });
  }
  for (const sid of room.spectators ?? []) {
    await sendClient(sid, { type: 'match_start', sides, gameState });
  }
  await broadcast(room, { type: 'chat', message: sysMsg });
  await sendRoomState(room);
  await startTurnTimer(room);
  await maybeAiMove(room);
}

let aiTimers: Map<string, NodeJS.Timeout> = new Map();
let turnTimers: Map<string, NodeJS.Timeout> = new Map();
let turnWarningTimers: Map<string, NodeJS.Timeout> = new Map();

// FEAT-5: Move timeout mechanism
const TIMEOUT_AI_MS = 60_000;       // AI: 60s → auto-resign
const TIMEOUT_HUMAN_WARN_MS = 180_000; // Human: 3min → warning
const TIMEOUT_HUMAN_FORFEIT_MS = 300_000; // Human: 5min → forfeit

function clearTurnTimer(roomId: string) {
  const t = turnTimers.get(roomId); if (t) clearTimeout(t); turnTimers.delete(roomId);
  const w = turnWarningTimers.get(roomId); if (w) clearTimeout(w); turnWarningTimers.delete(roomId);
}

async function startTurnTimer(room: any) {
  clearTurnTimer(room.id);
  if (room.state !== 'playing' || !room.game || room.game.finished) return;
  const gs = room.game.stateDict();
  const curSide = gs.currentPlayer;
  const curSideName = gs.currentPlayerName ?? curSide;
  const curEntry = Object.entries<any>(room.players).find(([, p]) => p.side === curSide || p.side === curSideName);
  if (!curEntry) return;
  const [curId, curPlayer] = curEntry;
  const isAi = curPlayer.isAi || curId.startsWith('AI_');

  if (isAi) {
    // AI gets 30s
    turnTimers.set(room.id, setTimeout(async () => {
      if (room.state !== 'playing' || room.game?.finished) return;
      const sysMsg = addChat(room, 'System', `${curPlayer.nick} timed out — auto-forfeit.`, true);
      await broadcast(room, { type: 'chat', message: sysMsg });
      const result = room.game.resign?.(curSide) ?? { ok: true, winner: null, reason: 'timeout' };
      await handleMatchEnd(room, { ...result, reason: 'timeout' });
    }, TIMEOUT_AI_MS));
  } else {
    // Human: warn at 3min, forfeit at 5min
    turnWarningTimers.set(room.id, setTimeout(async () => {
      if (room.state !== 'playing' || room.game?.finished) return;
      const sysMsg = addChat(room, 'System', `⏰ ${curPlayer.nick}, 2 minutes remaining to make a move!`, true);
      await broadcast(room, { type: 'chat', message: sysMsg });
      await sendClient(curId, { type: 'turn_warning', remaining: TIMEOUT_HUMAN_FORFEIT_MS - TIMEOUT_HUMAN_WARN_MS });
    }, TIMEOUT_HUMAN_WARN_MS));
    turnTimers.set(room.id, setTimeout(async () => {
      if (room.state !== 'playing' || room.game?.finished) return;
      const sysMsg = addChat(room, 'System', `${curPlayer.nick} timed out — auto-forfeit.`, true);
      await broadcast(room, { type: 'chat', message: sysMsg });
      const result = room.game.resign?.(curSide) ?? { ok: true, winner: null, reason: 'timeout' };
      await handleMatchEnd(room, { ...result, reason: 'timeout' });
    }, TIMEOUT_HUMAN_FORFEIT_MS));
  }
}

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
      const legal = room.game.legalMoves?.() ?? [];
      if (!legal.length) {
        const result = room.game.resign?.(curSide) ?? { ok: true, winner: null, reason: 'no_legal_moves' };
        if (room.game.finished) await handleMatchEnd(room, result);
        return;
      }
      const move = await fetchAiMove(gt, room.game, curSide, room);
      if (!move || !room.game || room.game.finished || room.state !== 'playing') return;
      const result = room.game.applyMove(move);
      if (!result.ok) return;
      room.moves.push({ side: curSide, move, ts: Date.now() });
      const gs2 = room.game.stateDict();
      await broadcast(room, { type: 'move', side: curSide, move, gameState: gs2 });
      if (room.game.finished) { clearTurnTimer(room.id); await handleMatchEnd(room, result); }
      else { await startTurnTimer(room); await maybeAiMove(room); }
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
  clearTurnTimer(room.id);
  room.state = 'finished';
  const game = room.game;
  const endedAt = new Date().toISOString();

  let winner = result.winner ?? game.winner ?? null;
  // Gomoku stores winner as 1/2 (number) — convert to side name
  if (winner === 1 || winner === 2) {
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
  const winnerNick = allPlayers.find((p:any) => p.side === String(winner))?.nick ?? winner?.toString() ?? '?';
  const resultStr = draw ? `Draw (${reason})` : winner ? `${winner} wins (${winnerNick})` : 'Unknown';

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

  // If game is in progress, give a grace period for reconnection (page refresh)
  if (room.state === 'playing' && room.players[clientId] && !room.players[clientId].isAi) {
    room.players[clientId]._disconnectedAt = Date.now();
    room.players[clientId]._disconnectedClientId = clientId;
    const disconnectNick = room.players[clientId].nick;
    const sysMsg = addChat(room, 'System', `${disconnectNick} disconnected. Waiting 15s for reconnect...`, true);
    await broadcast(room, { type: 'chat', message: sysMsg });
    // Grace period: wait 15s before forfeiting
    setTimeout(async () => {
      const r = rooms.get(roomId);
      if (!r || !r.players[clientId]) return; // already rejoined with new id or room gone
      if (r.players[clientId]._disconnectedAt) {
        // Still disconnected after grace period — forfeit
        const side = r.players[clientId].side;
        delete r.players[clientId];
        r.spectators = r.spectators?.filter((s: string) => s !== clientId) ?? [];
        if (r.state === 'playing' && r.game && !r.game.finished) {
          const result = r.game.resign?.(side) ?? { ok: true, winner: null, reason: 'disconnect' };
          await handleMatchEnd(r, { ...result, reason: 'disconnect' });
        }
        const msg2 = addChat(r, 'System', `${disconnectNick} did not reconnect — forfeited.`, true);
        await broadcast(r, { type: 'chat', message: msg2 });
        await broadcast(r, { type: 'player_left', nick: disconnectNick });
        broadcastRoomsUpdate();
      }
    }, 15_000);
    return; // Don't delete player yet — wait for reconnect
  }
  if (room.players[clientId]?.isAi || !room.players[clientId]) {
    // AI or already gone
  } else {
    delete room.players[clientId];
  }
  room.spectators = room.spectators?.filter((s: string) => s !== clientId) ?? [];

  const humans = Object.keys(room.players).filter(id => !id.startsWith('AI_'));
  if (humans.length === 0) {
    const t = aiTimers.get(roomId); if (t) clearTimeout(t); aiTimers.delete(roomId);
    clearTurnTimer(roomId);
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

// LLM provider loaded from llm.ts (supports OpenClaw CLI + direct API)

// DEPRECATED: handleApiMove is no longer called by euler_play.py (which now uses
// ask_move.py directly). Kept for potential external consumers (curl, other bots).
// Safe to remove once confirmed no external callers exist.
async function handleApiMove(req: IncomingMessage, res: ServerResponse) {
  try {
    const body = JSON.parse(await readBody(req));
    const gameType: string = body.gameType || 'gomoku';
    const side: string = body.side || '';
    const moveCount: number = body.moveCount ?? 0;
    const MAX_RETRIES = 3;

    if (gameType === 'chess') {
      const fen: string = body.fen || '';
      const pgn: string = body.pgn || body.history || '';
      const legalMovesSAN: string[] = body.legalMovesSAN || [];
      const inCheck: boolean = body.inCheck || false;

      if (!fen || !legalMovesSAN.length) {
        jsonResponse(res, 400, { error: 'chess: fen and legalMovesSAN required' });
        return;
      }

      const checkStr = inCheck ? ' IN CHECK.' : '';
      const chessSkill = getSkill('chess');
      const baseUserMsg = `Move ${moveCount + 1}. You: ${side}.${checkStr}
FEN: ${fen}
History: ${pgn}
Legal moves: ${legalMovesSAN.join(', ')}
Reply with ONLY one SAN move (e.g. Nf3):`;

      const parseChessMove = (reply: string): { uci: string } | null => {
        const san = reply.trim().split(/[\s\n]+/)[0].replace(/[.!?]+$/, '');
        if (!legalMovesSAN.includes(san)) return null;
        try {
          const tempChess = new Chess(fen);
          const m = tempChess.move(san);
          if (!m) return null;
          return { uci: m.from + m.to + (m.promotion || '') };
        } catch { return null; }
      };

      const randomChessMove = (): { uci: string } => {
        const san = legalMovesSAN[Math.floor(Math.random() * legalMovesSAN.length)];
        const tempChess = new Chess(fen);
        const m = tempChess.move(san);
        return { uci: m!.from + m!.to + (m!.promotion || '') };
      };

      let userMsg = baseUserMsg;
      try {
        for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
          const reply = await llmChat('euler-chess-moves', chessSkill, userMsg, 60);
          const move = parseChessMove(reply);
          if (move) { jsonResponse(res, 200, move); return; }
          userMsg = `"${reply.trim().split(/\s/)[0]}" is not a legal move. Legal moves: ${legalMovesSAN.join(', ')}. Reply with just one SAN move:`;
        }
      } catch (e: any) {
        console.error('Chess AI error:', e.message);
      }
      jsonResponse(res, 200, randomChessMove());
      return;
    }

    if (gameType === 'xiangqi') {
      const fen: string = body.fen || '';
      const history: string = body.history || '';
      const legalMovesCoord: string[] = body.legalMovesCoord || [];
      const inCheck: boolean = body.inCheck || false;

      if (!legalMovesCoord.length) {
        jsonResponse(res, 400, { error: 'xiangqi: legalMovesCoord required' });
        return;
      }

      const coordSet = new Set(legalMovesCoord);
      const checkStr = inCheck ? ' IN CHECK.' : '';
      const xiangqiSkill = getSkill('xiangqi');
      const baseUserMsg = `Move ${moveCount + 1}. You: ${side}.${checkStr}
FEN: ${fen}
History: ${history}
Legal moves: ${legalMovesCoord.join(', ')}
Reply with ONLY the coordinate (e.g. b0c2):`;

      const parseXiangqiMove = (reply: string): { fromRow: number; fromCol: number; toRow: number; toCol: number } | null => {
        const m = reply.trim().match(/\b([a-i])(\d)([a-i])(\d)\b/);
        if (!m) return null;
        const coord = m[1] + m[2] + m[3] + m[4];
        if (!coordSet.has(coord)) return null;
        return {
          fromCol: m[1].charCodeAt(0) - 97, fromRow: parseInt(m[2]),
          toCol: m[3].charCodeAt(0) - 97, toRow: parseInt(m[4]),
        };
      };

      const randomXiangqiMove = () => {
        const coord = legalMovesCoord[Math.floor(Math.random() * legalMovesCoord.length)];
        return {
          fromCol: coord.charCodeAt(0) - 97, fromRow: parseInt(coord[1]),
          toCol: coord.charCodeAt(2) - 97, toRow: parseInt(coord[3]),
        };
      };

      let userMsg = baseUserMsg;
      try {
        for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
          const reply = await llmChat('euler-xiangqi-moves', xiangqiSkill, userMsg, 60);
          const move = parseXiangqiMove(reply);
          if (move) { jsonResponse(res, 200, move); return; }
          userMsg = `"${reply.trim().split(/\s/)[0]}" is not a legal move. Legal moves: ${legalMovesCoord.join(', ')}. Reply with just one coordinate (e.g. b0c2):`;
        }
      } catch (e: any) {
        console.error('Xiangqi AI error:', e.message);
      }
      jsonResponse(res, 200, randomXiangqiMove());
      return;
    }

    // Gomoku
    const { board, size, currentPlayer } = body;
    if (!Array.isArray(board) || typeof size !== 'number' || size < 1 || size > 19) {
      jsonResponse(res, 400, { error: 'gomoku: board array and valid size required' });
      return;
    }

    const history: string = body.history || '';
    const legalMovesCount: number = body.legalMovesCount ?? (size * size - (body.moveCount ?? 0));
    const basePrompt = `Gomoku. You: ${side}. Move ${moveCount + 1}.
Stones: ${history || 'none'}
Board size: ${size}x${size}
Pick coordinates (row,col 0-indexed):`;

    const parseGomokuMove = (reply: string, bd: number[][]): { row: number; col: number } | null => {
      const match = reply.match(/(\d+)\s*[,\s]\s*(\d+)/);
      if (!match) return null;
      const row = parseInt(match[1]), col = parseInt(match[2]);
      if (row >= 0 && row < size && col >= 0 && col < size && bd[row][col] === 0)
        return { row, col };
      return null;
    };

    let userMsg = basePrompt;
    try {
      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        const reply = await llmChat('euler-gomoku-moves', '', userMsg, 60);
        const move = parseGomokuMove(reply, board);
        if (move) { jsonResponse(res, 200, move); return; }
        userMsg = `"${reply.trim()}" is not a valid empty cell. Reply with row,col (0-indexed, must be empty):`;
      }
    } catch (e: any) {
      console.error('Gomoku AI error:', e.message);
    }
    // Fallback: first empty cell near center
    const center = size >> 1;
    const empties: { row: number; col: number; dist: number }[] = [];
    for (let r = 0; r < size; r++)
      for (let c = 0; c < size; c++)
        if (board[r][c] === 0)
          empties.push({ row: r, col: c, dist: Math.abs(r - center) + Math.abs(c - center) });
    empties.sort((a, b) => a.dist - b.dist);
    const fallback = empties[Math.floor(Math.random() * Math.min(5, empties.length))];
    jsonResponse(res, 200, fallback ? { row: fallback.row, col: fallback.col } : { error: 'no moves' });
  } catch (e: any) {
    jsonResponse(res, 400, { error: `Bad request: ${e.message}` });
  }
}

const CHAT_SYSTEM_CONTEXT = 'You are OpenClaw (Euler), an AI assistant playing a board game with the user. ' +
  'For casual banter and game reactions, keep replies SHORT (1-2 sentences), playful and competitive. ' +
  'If the user asks a factual question (weather, news, weekly plans, GitHub, YouTube, or anything requiring a lookup), ' +
  'use your tools (weather skill, web_search, memory_search, etc.) to find the answer and reply accurately. ' +
  'Do not make up facts — use tools when you need real information.';

async function handleApiChat(req: IncomingMessage, res: ServerResponse) {
  try {
    const body = JSON.parse(await readBody(req));
    const { text, gameContext, gameType } = body;

    if (!text || typeof text !== 'string') {
      jsonResponse(res, 400, { error: 'text is required' });
      return;
    }
    const safeText = text.slice(0, 500);

    const systemMsg = gameContext
      ? `${CHAT_SYSTEM_CONTEXT}\nGame state: ${String(gameContext).slice(0, 200)}`
      : CHAT_SYSTEM_CONTEXT;

    try {
      const reply = await llmChat('euler-game-chat', systemMsg, safeText, 60);
      if (!reply || reply.trim() === '' || reply.trim() === 'NO_REPLY' || reply.trim() === 'HEARTBEAT_OK') {
        jsonResponse(res, 200, { reply: null });
        return;
      }
      const trimmed = reply.trim().slice(0, 1000);
      jsonResponse(res, 200, { reply: trimmed });
    } catch {
      jsonResponse(res, 200, { reply: null });
    }
  } catch (e: any) {
    jsonResponse(res, 400, { error: `Bad request: ${e.message}` });
  }
}

// ── Spawn Euler agent ─────────────────────────────────────────────────────
function spawnEulerAgent(roomId: string, difficulty: string) {
  const agentPath = join(__dirname, '..', '..', 'agent-player', 'euler_play.py');
  console.log(`[euler] Spawning agent for room ${roomId} (difficulty=${difficulty})`);

  // Default: openclaw (unchanged). Self-hosters can override via .env
  const aiEngine = process.env.AI_ENGINE || 'openclaw';
  const aiModel  = process.env.AI_MODEL;

  const args = [agentPath, roomId, '--mode', 'ai',
                '--ai-engine', aiEngine, '--difficulty', difficulty,
                '--port', String(PORT)];
  if (aiModel) args.push('--ai-model', aiModel);

  // Pass API key into subprocess env
  const childEnv = { ...process.env };
  childEnv.PYTHONUTF8 = childEnv.PYTHONUTF8 || '1';
  childEnv.PYTHONIOENCODING = childEnv.PYTHONIOENCODING || 'utf-8';
  if (process.env.AI_API_KEY) {
    childEnv.OPENROUTER_API_KEY = process.env.AI_API_KEY;
    childEnv.ANTHROPIC_API_KEY  = process.env.AI_API_KEY;
    childEnv.OPENAI_API_KEY     = process.env.AI_API_KEY;
  }

  const launcher = process.platform === 'win32' ? 'uv' : 'python3';
  const launcherArgs = process.platform === 'win32'
    ? ['run', '--with', 'websockets', '--with', 'chess', 'python', ...args]
    : args;
  const proc = spawn(launcher, launcherArgs, {
    stdio: ['ignore', 'pipe', 'pipe'],
    cwd: join(__dirname, '..', '..', 'agent-player'),
    env: childEnv,
  });
  proc.stdout?.on('data', (d: Buffer) => {
    for (const line of d.toString().split('\n').filter(Boolean))
      console.log(`[euler@${roomId}] ${line}`);
  });
  proc.stderr?.on('data', (d: Buffer) => {
    for (const line of d.toString().split('\n').filter(Boolean))
      console.error(`[euler@${roomId}] ${line}`);
  });
  proc.on('exit', (code) => console.log(`[euler@${roomId}] exited (code=${code})`));
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
    handleApiMove(req, res); // DEPRECATED — see comment above handleApiMove
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

// Ping/pong keepalive — detect dead connections every 30s
const aliveMap = new Map<WebSocket, boolean>();
const pingInterval = setInterval(() => {
  for (const ws of wss.clients) {
    if (aliveMap.get(ws) === false) { ws.terminate(); continue; }
    aliveMap.set(ws, false);
    try { ws.ping(); } catch {}
  }
}, 30_000);
wss.on('close', () => clearInterval(pingInterval));

wss.on('connection', (ws) => {
  const clientId = uuidv4();
  let nick = 'Anonymous';
  clients.set(clientId, ws);
  aliveMap.set(ws, true);
  ws.on('pong', () => aliveMap.set(ws, true));

  ws.on('message', async (data) => {
    try {
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
      if (msg.preferredSide && ['first', 'second', 'random'].includes(msg.preferredSide)) room.preferredSide = msg.preferredSide;
      rooms.set(room.id, room);
      room.players[clientId] = { nick, ready: false, isAi: false, side: null };
      room.spectators = [];
      clientRoom.set(clientId, room.id);
      addChat(room, 'System', `${nick} created the room.`, true);
      ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id }));
      await sendRoomState(room, clientId);
      broadcastRoomsUpdate();
      if (msg.withAi) {
        if (room.aiType === 'euler') {
          // Spawn euler_play.py as external agent (joins as real player)
          room.players[clientId].ready = true;
          const sysMsg = addChat(room, 'System', 'Spawning OpenClaw AI agent...', true);
          await broadcast(room, { type: 'chat', message: sysMsg });
          await sendRoomState(room, clientId);
          spawnEulerAgent(room.id, room.difficulty);
        } else {
          // Built-in AI (engine mode) — handled server-side
          const aiId = `AI_${room.id}`;
          const aiNick = `Engine (${room.difficulty}) ⚙️`;
          room.players[aiId] = { nick: aiNick, ready: true, isAi: true, side: null };
          room.players[clientId].ready = true;
          const aiMsg = addChat(room, 'System', `${aiNick} (AI) joined.`, true);
          const aiChat = addChat(room, aiNick, 'Let\'s play! Good luck 🎮');
          await broadcast(room, { type: 'chat', message: aiMsg });
          await broadcast(room, { type: 'chat', message: aiChat });
          await startMatch(room);
        }
      }
      return;
    }

    if (type === 'join_room') {
      const room = rooms.get(msg.roomId);
      if (!room) { ws.send(JSON.stringify({ type: 'error', msg: 'room not found' })); return; }
      const humanCount = Object.values<any>(room.players).filter((p:any) => !p.isAi).length;
      if (humanCount >= 2 || room.state !== 'waiting') { ws.send(JSON.stringify({ type: 'error', msg: 'room full or in progress' })); return; }
      const joinNick = getUniqueNick(room, nick);
      if (joinNick !== nick) nick = joinNick; // update local nick for this session
      room.players[clientId] = { nick: joinNick, ready: false, isAi: false, side: null };
      clientRoom.set(clientId, room.id);
      const joinMsg = addChat(room, 'System', `${joinNick} joined.`, true);
      ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id }));
      await broadcast(room, { type: 'chat', message: joinMsg }, clientId);
      await sendRoomState(room);
      broadcastRoomsUpdate();
      return;
    }

    // BUG-5: Reconnection after page refresh
    if (type === 'rejoin_room') {
      const room = rooms.get(msg.roomId);
      const oldId = msg.oldClientId;
      if (!room) { ws.send(JSON.stringify({ type: 'error', msg: 'room not found' })); return; }
      // Check if the old player entry still exists
      if (oldId && room.players[oldId]) {
        // Transfer player entry from old clientId to new clientId
        const playerData = room.players[oldId];
        delete playerData._disconnectedAt; // Clear disconnect flag
        delete playerData._disconnectedClientId;
        delete room.players[oldId];
        room.players[clientId] = playerData;
        // Update mappings
        clientRoom.delete(oldId);
        clients.delete(oldId);
        clientRoom.set(clientId, room.id);
        nick = playerData.nick;
        ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id, rejoin: true }));
        const sysMsg = addChat(room, 'System', `${nick} reconnected.`, true);
        await broadcast(room, { type: 'chat', message: sysMsg });
        await sendRoomState(room, clientId);
      } else {
        // Old player gone — try joining as new player if room allows
        const humanCount = Object.values<any>(room.players).filter((p:any) => !p.isAi).length;
        if (humanCount < 2 && room.state === 'waiting') {
          const joinNick = getUniqueNick(room, nick);
          if (joinNick !== nick) nick = joinNick;
          room.players[clientId] = { nick: joinNick, ready: false, isAi: false, side: null };
          clientRoom.set(clientId, room.id);
          ws.send(JSON.stringify({ type: 'room_joined', roomId: room.id }));
          await sendRoomState(room, clientId);
        } else {
          ws.send(JSON.stringify({ type: 'rejoin_failed', reason: 'session expired' }));
        }
      }
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
      if (!msg.move) { ws.send(JSON.stringify({ type: 'error', msg: 'move field required' })); return; }
      // Normalize chess moves: accept string UCI (e.g. "e2e4") as well as { uci: "e2e4" }
      let move = msg.move;
      if (room.gameType === 'chess' && typeof move === 'string') move = { uci: move };
      const result = room.game.applyMove(move);
      if (!result.ok) {
        // FEAT-2: add context-specific hints for invalid moves
        let hint = result.reason || 'illegal move';
        if (room.gameType === 'chess') {
          const gs2 = room.game.stateDict();
          if (gs2.inCheck) hint += ' — your king is in check, you must resolve it';
        } else if (room.gameType === 'xiangqi') {
          const gs2 = room.game.stateDict();
          if (gs2.inCheck) hint += ' — your general is in check, you must resolve it';
        }
        ws.send(JSON.stringify({ type: 'move_error', msg: hint }));
        return;
      }
      room.moves.push({ side: player.side, move: msg.move, ts: Date.now() });
      await broadcast(room, { type: 'move', side: player.side, move: msg.move, gameState: room.game.stateDict() });
      // FEAT-4: repetition warning for chess
      if (room.gameType === 'chess' && !room.game.finished && room.game.repetitionCount() >= 2) {
        const warnMsg = addChat(room, 'System', 'Position repeated — one more repetition will be a draw (threefold repetition).', true);
        await broadcast(room, { type: 'chat', message: warnMsg });
        await broadcast(room, { type: 'repetition_warning', count: room.game.repetitionCount() });
      }
      if (room.game.finished) { clearTurnTimer(room.id); await handleMatchEnd(room, result); }
      else { await startTurnTimer(room); await maybeAiMove(room); }
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
      const isSpectator = room.spectators?.includes(clientId) ?? false;
      const displayNick = isSpectator ? `[Spectator] ${nick}` : nick;
      const chatMsg = addChat(room, displayNick, text);
      if (isSpectator) chatMsg.spectator = true;
      await broadcast(room, { type: 'chat', message: chatMsg });
      return;
    }

    if (type === 'play_again') {
      const roomId = clientRoom.get(clientId);
      const room = rooms.get(roomId ?? '');
      if (!room) return;
      // Only a non-AI human player can trigger a full room reset (prevents Euler auto-reset)
      const requestingPlayer = room.players[clientId];
      const isHumanRequest = requestingPlayer && !requestingPlayer.isAi;
      if (!isHumanRequest) return; // Ignore play_again from AI bots
      // If room is already in waiting state (e.g. Euler already reset it), just confirm to requester
      if (room.state === 'waiting') { await sendRoomState(room, clientId); return; }
      if (room.state === 'playing') return; // can't play_again during active match
      // Full reset (state must be 'finished')
      room.swapSides = !room.swapSides; // auto-swap sides each rematch
      room.state = 'waiting'; room.game = null; room.matchId = null; room.startedAt = null; room.moves = [];
      for (const p of Object.values<any>(room.players)) { p.ready = p.isAi ? true : false; p.side = null; }
      const resetMsg = addChat(room, 'System', 'Room reset. Ready up for a new match!', true);
      await broadcast(room, { type: 'chat', message: resetMsg });
      // Engine mode (built-in AI player): auto-start without requiring human to click Ready again
      const hasBuiltinAi = Object.values<any>(room.players).some((p:any) => p.isAi);
      if (hasBuiltinAi) {
        for (const p of Object.values<any>(room.players)) { p.ready = true; }
        await startMatch(room);
      } else {
        await sendRoomState(room);
      }
      broadcastRoomsUpdate();
      return;
    }

    if (type === 'leave_room') { await handleLeave(clientId, nick); return; }
    if (type === 'get_history') { ws.send(JSON.stringify({ type: 'history', matches: listMatches() })); return; }
    } catch (e) { console.error(`Unhandled WS message error [${clientId}]:`, e); }
  });

  ws.on('close', () => { aliveMap.delete(ws); clients.delete(clientId); handleLeave(clientId, nick); });
  ws.on('error', () => { aliveMap.delete(ws); clients.delete(clientId); handleLeave(clientId, nick); });
});

httpServer.listen(PORT, '0.0.0.0', () => {
  console.log(`🎮 LAN Board Game Platform running on http://0.0.0.0:${PORT}`);
});
