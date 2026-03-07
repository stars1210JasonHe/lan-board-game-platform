export const EMPTY = 0, BLACK = 1, WHITE = 2;
export type Cell = 0 | 1 | 2;

export class GomokuGame {
  board: Cell[][];
  size = 15;
  currentPlayer: 1 | 2 = BLACK;
  winner: Cell = EMPTY;
  finished = false;
  moveHistory: { player: Cell; row: number; col: number }[] = [];

  constructor() {
    this.board = Array.from({ length: 15 }, () => Array(15).fill(EMPTY));
  }

  legalMoves() {
    if (this.finished) return [];
    return this.board.flatMap((row, r) =>
      row.flatMap((cell, c) => (cell === EMPTY ? [{ row: r, col: c }] : []))
    );
  }

  applyMove(move: { row: number; col: number }): { ok: boolean; reason?: string; winner?: Cell; draw?: boolean } {
    const { row, col } = move;
    if (this.finished) return { ok: false, reason: 'match ended' };
    if (row < 0 || row >= 15 || col < 0 || col >= 15) return { ok: false, reason: 'out of bounds' };
    if (this.board[row][col] !== EMPTY) return { ok: false, reason: 'occupied' };

    const p = this.currentPlayer;
    this.board[row][col] = p;
    this.moveHistory.push({ player: p, row, col });

    if (this.checkWin(row, col, p)) {
      this.winner = p; this.finished = true;
      return { ok: true, winner: p };
    }
    if (this.moveHistory.length === 225) {
      this.finished = true; return { ok: true, draw: true };
    }
    this.currentPlayer = p === BLACK ? WHITE : BLACK;
    return { ok: true };
  }

  private checkWin(r: number, c: number, p: Cell): boolean {
    const dirs = [[0,1],[1,0],[1,1],[1,-1]];
    for (const [dr, dc] of dirs) {
      let count = 1;
      for (const s of [1, -1]) {
        let nr = r + s*dr, nc = c + s*dc;
        while (nr >= 0 && nr < 15 && nc >= 0 && nc < 15 && this.board[nr][nc] === p) {
          count++; nr += s*dr; nc += s*dc;
        }
      }
      if (count >= 5) return true;
    }
    return false;
  }

  resign(side: string) {
    if (this.finished) return { ok: false };
    this.finished = true;
    // side is 'black' or 'white'; map to player number
    const resigned = side === 'black' ? BLACK : WHITE;
    this.winner = resigned === BLACK ? WHITE : BLACK;
    return { ok: true, winner: this.winner === BLACK ? 'black' : 'white', reason: 'resignation' };
  }

  stateDict() {
    const lastM = this.moveHistory.length > 0 ? this.moveHistory[this.moveHistory.length - 1] : null;
    return {
      gameType: 'gomoku',
      board: this.board,
      currentPlayer: this.currentPlayer,
      currentPlayerName: this.currentPlayer === BLACK ? 'black' : 'white',
      winner: this.winner,
      finished: this.finished,
      moveCount: this.moveHistory.length,
      size: this.size,
      history: this.moveHistory.map(m => `${m.player === BLACK ? 'B' : 'W'}:${m.row},${m.col}`).join(';'),
      legalMovesCount: this.finished ? 0 : (this.size * this.size - this.moveHistory.length),
      lastMove: lastM ? `${lastM.row},${lastM.col}` : null,
    };
  }
}
