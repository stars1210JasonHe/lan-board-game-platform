export type Color = 'red' | 'black';

const INITIAL = [
  'RNBAKABNR',
  '         ',
  ' C     C ',
  'P P P P P',
  '         ',
  '         ',
  'p p p p p',
  ' c     c ',
  '         ',
  'rnbakabnr',
];

function color(p: string): Color { return p === p.toUpperCase() ? 'red' : 'black'; }
function opp(c: Color): Color { return c === 'red' ? 'black' : 'red'; }
function inBounds(r: number, c: number) { return r >= 0 && r <= 9 && c >= 0 && c <= 8; }

export class XiangqiGame {
  board: string[][];
  currentPlayer: Color = 'red';
  winner: Color | null = null;
  winnerReason: string | null = null;
  finished = false;
  moveHistory: any[] = [];

  constructor() { this.board = INITIAL.map(r => r.split('')); }

  get(r: number, c: number) { return this.board[r][c]; }
  set(r: number, c: number, v: string) { this.board[r][c] = v; }
  empty(r: number, c: number) { return this.board[r][c] === ' '; }

  legalMoves() {
    const moves: any[] = [];
    const col = this.currentPlayer;
    for (let r = 0; r <= 9; r++)
      for (let c = 0; c <= 8; c++) {
        const p = this.get(r, c);
        if (p === ' ' || color(p) !== col) continue;
        for (const [tr, tc] of this.pieceMoves(r, c, p, col))
          if (this.safeAfter(r, c, tr, tc, col))
            moves.push({ fromRow: r, fromCol: c, toRow: tr, toCol: tc });
      }
    return moves;
  }

  private pieceMoves(r: number, c: number, p: string, col: Color): [number, number][] {
    const t = p.toUpperCase();
    if (t === 'K') return this.kingMoves(r, c, col);
    if (t === 'A') return this.advisorMoves(r, c, col);
    if (t === 'B') return this.elephantMoves(r, c, col);
    if (t === 'N') return this.knightMoves(r, c, col);
    if (t === 'R') return this.rookMoves(r, c, col);
    if (t === 'C') return this.cannonMoves(r, c, col);
    if (t === 'P') return this.pawnMoves(r, c, col);
    return [];
  }

  private palaceRows(col: Color) { return col === 'red' ? [0,1,2] : [7,8,9]; }

  private canTarget(r: number, c: number, col: Color): boolean {
    const p = this.get(r, c);
    return p === ' ' || color(p) !== col;
  }

  private kingMoves(r: number, c: number, col: Color): [number,number][] {
    const pr = this.palaceRows(col);
    return [[r+1,c],[r-1,c],[r,c+1],[r,c-1]]
      .filter(([nr,nc]) => inBounds(nr,nc) && pr.includes(nr) && nc >= 3 && nc <= 5 && this.canTarget(nr,nc,col)) as [number,number][];
  }

  private advisorMoves(r: number, c: number, col: Color): [number,number][] {
    const pr = this.palaceRows(col);
    return [[r+1,c+1],[r+1,c-1],[r-1,c+1],[r-1,c-1]]
      .filter(([nr,nc]) => inBounds(nr,nc) && pr.includes(nr) && nc >= 3 && nc <= 5 && this.canTarget(nr,nc,col)) as [number,number][];
  }

  private elephantMoves(r: number, c: number, col: Color): [number,number][] {
    const homeRows = col === 'red' ? [0,1,2,3,4] : [5,6,7,8,9];
    return [[2,2],[2,-2],[-2,2],[-2,-2]]
      .map(([dr,dc]) => [r+dr, c+dc, r+dr/2, c+dc/2] as [number,number,number,number])
      .filter(([nr,nc,mr,mc]) => inBounds(nr,nc) && homeRows.includes(nr) && this.empty(mr,mc) && this.canTarget(nr,nc,col))
      .map(([nr,nc]) => [nr,nc] as [number,number]);
  }

  private knightMoves(r: number, c: number, col: Color): [number,number][] {
    const result: [number,number][] = [];
    for (const [dr, dc, br, bc] of [[-1,0,-2,1],[-1,0,-2,-1],[1,0,2,1],[1,0,2,-1],[0,-1,1,-2],[0,-1,-1,-2],[0,1,1,2],[0,1,-1,2]] as number[][]) {
      const stepR = r+dr, stepC = c+dc;
      if (!inBounds(stepR,stepC) || !this.empty(stepR,stepC)) continue;
      const nr = r+br, nc = c+bc;
      if (inBounds(nr,nc) && this.canTarget(nr,nc,col)) result.push([nr,nc]);
    }
    return result;
  }

  private rookMoves(r: number, c: number, col: Color): [number,number][] {
    const result: [number,number][] = [];
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      let nr = r+dr, nc = c+dc;
      while (inBounds(nr,nc)) {
        if (this.empty(nr,nc)) { result.push([nr,nc]); }
        else { if (color(this.get(nr,nc)) !== col) result.push([nr,nc]); break; }
        nr += dr; nc += dc;
      }
    }
    return result;
  }

  private cannonMoves(r: number, c: number, col: Color): [number,number][] {
    const result: [number,number][] = [];
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      let nr = r+dr, nc = c+dc, jumped = false;
      while (inBounds(nr,nc)) {
        if (!jumped) { if (this.empty(nr,nc)) result.push([nr,nc]); else jumped = true; }
        else { if (!this.empty(nr,nc)) { if (color(this.get(nr,nc)) !== col) result.push([nr,nc]); break; } }
        nr += dr; nc += dc;
      }
    }
    return result;
  }

  private pawnMoves(r: number, c: number, col: Color): [number,number][] {
    const fwd = col === 'red' ? 1 : -1;
    const crossed = col === 'red' ? r >= 5 : r <= 4;
    const result: [number,number][] = [];
    const nr = r+fwd, nc = c;
    if (inBounds(nr,nc) && this.canTarget(nr,nc,col)) result.push([nr,nc]);
    if (crossed) for (const dc of [-1,1]) if (inBounds(r,c+dc) && this.canTarget(r,c+dc,col)) result.push([r,c+dc]);
    return result;
  }

  private findKing(col: Color): [number,number] | null {
    const k = col === 'red' ? 'K' : 'k';
    for (let r = 0; r <= 9; r++) for (let c = 0; c <= 8; c++) if (this.board[r][c] === k) return [r,c];
    return null;
  }

  private inCheck(col: Color): boolean {
    const king = this.findKing(col);
    if (!king) return true;
    const [kr,kc] = king;
    const o = opp(col);
    for (let r = 0; r <= 9; r++) for (let c = 0; c <= 8; c++) {
      const p = this.get(r,c);
      if (p === ' ' || color(p) !== o) continue;
      if (this.pieceMoves(r,c,p,o).some(([tr,tc]) => tr === kr && tc === kc)) return true;
    }
    // flying kings
    const oppKing = this.findKing(o);
    if (oppKing && oppKing[1] === kc) {
      const [okr] = oppKing;
      const between = Array.from({length: Math.abs(okr-kr)-1}, (_,i) => Math.min(okr,kr)+1+i);
      if (between.every(br => this.empty(br,kc))) return true;
    }
    return false;
  }

  private safeAfter(r: number, c: number, nr: number, nc: number, col: Color): boolean {
    const saved = this.board[nr][nc];
    this.board[nr][nc] = this.board[r][c]; this.board[r][c] = ' ';
    const safe = !this.inCheck(col);
    this.board[r][c] = this.board[nr][nc]; this.board[nr][nc] = saved;
    return safe;
  }

  applyMove(move: any): any {
    if (this.finished) return { ok: false, reason: 'match ended' };
    const { fromRow: fr, fromCol: fc, toRow: tr, toCol: tc } = move;
    const legal = this.legalMoves();
    if (!legal.some(m => m.fromRow===fr && m.fromCol===fc && m.toRow===tr && m.toCol===tc))
      return { ok: false, reason: 'illegal move' };

    const col = this.currentPlayer;
    const captured = this.get(tr,tc);
    this.set(tr,tc,this.get(fr,fc)); this.set(fr,fc,' ');
    this.moveHistory.push({ side: col, fromRow:fr,fromCol:fc,toRow:tr,toCol:tc, captured: captured !== ' ' ? captured : null });

    this.currentPlayer = opp(col);
    const oppMoves = this.legalMoves();
    if (oppMoves.length === 0) {
      if (this.inCheck(this.currentPlayer)) {
        this.winner = col; this.winnerReason = 'checkmate'; this.finished = true;
        return { ok: true, winner: col, reason: 'checkmate' };
      }
      this.finished = true; return { ok: true, draw: true, reason: 'stalemate' };
    }
    return { ok: true };
  }

  resign(side: Color) {
    if (this.finished) return { ok: false };
    this.finished = true; this.winner = opp(side); this.winnerReason = 'resignation';
    return { ok: true, winner: this.winner, reason: 'resignation' };
  }

  stateDict() {
    return {
      gameType: 'xiangqi',
      board: this.board.map(r => r.join('')),
      currentPlayer: this.currentPlayer,
      currentPlayerName: this.currentPlayer,
      winner: this.winner,
      winnerReason: this.winnerReason,
      finished: this.finished,
      inCheck: !this.finished && this.inCheck(this.currentPlayer),
      moveCount: this.moveHistory.length,
    };
  }
}
