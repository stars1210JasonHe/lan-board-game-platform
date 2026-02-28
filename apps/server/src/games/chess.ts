import { Chess } from 'chess.js';

export class ChessGame {
  private chess: Chess;
  winner: string | null = null;
  winnerReason: string | null = null;
  finished = false;
  moveHistory: { side: string; uci: string; san: string }[] = [];
  resignedBy: string | null = null;

  constructor() { this.chess = new Chess(); }

  currentSide() { return this.chess.turn() === 'w' ? 'white' : 'black'; }

  legalMoves() { return this.chess.moves({ verbose: true }).map(m => m.from + m.to + (m.promotion || '')); }

  applyMove(move: { uci?: string }): { ok: boolean; reason?: string; winner?: string; draw?: boolean } {
    if (this.finished) return { ok: false, reason: 'match ended' };
    const uci = move.uci;
    if (!uci) return { ok: false, reason: 'missing uci' };
    try {
      const from = uci.slice(0, 2), to = uci.slice(2, 4), promotion = uci[4];
      const side = this.currentSide();
      const m = this.chess.move({ from, to, promotion });
      if (!m) return { ok: false, reason: 'illegal move' };
      this.moveHistory.push({ side, uci, san: m.san });
      return this.checkEnd();
    } catch { return { ok: false, reason: 'invalid move' }; }
  }

  resign(side: string) {
    if (this.finished) return { ok: false, reason: 'already ended' };
    this.finished = true; this.resignedBy = side;
    this.winner = side === 'white' ? 'black' : 'white';
    this.winnerReason = 'resignation';
    return { ok: true, winner: this.winner, reason: 'resignation' };
  }

  private checkEnd(): { ok: boolean; winner?: string; draw?: boolean; reason?: string } {
    if (this.chess.isCheckmate()) {
      const loser = this.chess.turn() === 'w' ? 'white' : 'black';
      this.winner = loser === 'white' ? 'black' : 'white';
      this.winnerReason = 'checkmate'; this.finished = true;
      return { ok: true, winner: this.winner, reason: 'checkmate' };
    }
    if (this.chess.isDraw()) {
      this.finished = true;
      const reason = this.chess.isStalemate() ? 'stalemate' :
        this.chess.isInsufficientMaterial() ? 'insufficient_material' : 'draw';
      return { ok: true, draw: true, reason };
    }
    return { ok: true };
  }

  stateDict() {
    return {
      gameType: 'chess',
      fen: this.chess.fen(),
      currentPlayer: this.currentSide(),
      currentPlayerName: this.currentSide(),
      legalMoves: this.finished ? [] : this.legalMoves(),
      winner: this.winner,
      winnerReason: this.winnerReason,
      finished: this.finished,
      inCheck: this.chess.inCheck(),
      moveCount: this.moveHistory.length,
    };
  }
}
