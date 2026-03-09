#!/usr/bin/env python3
"""Game platform integration test — plays moves and verifies AI responds."""
import asyncio, json, websockets

SERVER = 'ws://localhost:8765'

# Side that goes first per game type
FIRST_SIDE = {'gomoku': 'black', 'chess': 'white', 'xiangqi': 'red'}
SECOND_SIDE = {'gomoku': 'white', 'chess': 'black', 'xiangqi': 'black'}

async def play_game(game_type, my_moves, preferred_side='first'):
    print(f'\n{"="*50}')
    print(f'Testing: {game_type.upper()} (preferred={preferred_side})')
    print(f'{"="*50}')
    
    my_side = FIRST_SIDE[game_type] if preferred_side == 'first' else SECOND_SIDE[game_type]
    ai_side = SECOND_SIDE[game_type] if preferred_side == 'first' else FIRST_SIDE[game_type]
    
    async with websockets.connect(SERVER) as ws:
        await ws.send(json.dumps({'type': 'identify', 'nick': f'Test-{game_type}'}))
        await ws.recv(); await ws.recv()
        
        await ws.send(json.dumps({
            'type': 'create_room', 'gameType': game_type,
            'withAi': True, 'aiType': 'euler', 'difficulty': 'medium',
            'preferredSide': preferred_side
        }))
        
        # Wait for match_start + initial chat
        game_started = False
        for _ in range(25):
            try:
                resp = json.loads(await asyncio.wait_for(ws.recv(), 30))
                t = resp.get('type', '')
                if t == 'match_start':
                    game_started = True
                elif t == 'chat':
                    txt = resp.get('message', {}).get('text', '')
                    if 'Match started' in txt:
                        print(f'  📋 {txt}')
                        break
            except asyncio.TimeoutError:
                break
        
        if not game_started:
            print('  ❌ Game did not start')
            return False
        
        print(f'  ✅ Started! Me={my_side}, AI={ai_side}')
        
        moves_played = 0
        
        for move in my_moves:
            # Send my move
            await ws.send(json.dumps({'type': 'move', 'move': move}))
            print(f'\n  👤 My move ({my_side}): {move}')
            
            # Wait for both: my echo + AI response
            got_my_echo = False
            got_ai_move = False
            
            for _ in range(20):
                try:
                    resp = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    t = resp.get('type', '')
                    
                    if t == 'move':
                        side = resp.get('side', '?')
                        m = resp.get('move', {})
                        gs = resp.get('gameState', {})
                        
                        if str(side) == str(my_side) or (game_type == 'gomoku' and not got_my_echo):
                            got_my_echo = True
                            print(f'  ✅ Confirmed (side={side})')
                            continue
                        
                        # AI's move
                        fen = gs.get('fen', gs.get('history', '?'))
                        legal_san = gs.get('legalMovesSAN', [])
                        legal_coord = gs.get('legalMovesCoord', [])
                        legal_count = len(legal_san) if legal_san else len(legal_coord)
                        last = gs.get('lastMove', '?')
                        check = gs.get('inCheck', False)
                        pgn = gs.get('pgn', '')
                        
                        print(f'  🤖 AI move (side={side}): {m}')
                        print(f'     FEN: {str(fen)[:70]}')
                        print(f'     lastMove: {last} | inCheck: {check} | legalMoves: {legal_count}')
                        if pgn:
                            lines = [l for l in pgn.strip().split('\n') if not l.startswith('[')]
                            if lines:
                                print(f'     PGN: {lines[-1].strip()[:70]}')
                        
                        got_ai_move = True
                        moves_played += 1
                        break
                    
                    elif t == 'match_end':
                        print(f'  🏁 Match ended: winner={resp.get("winner")} reason={resp.get("reason")}')
                        return moves_played > 0
                    
                    elif t == 'error':
                        print(f'  ❌ Error: {resp.get("msg")}')
                        return moves_played > 0
                    
                except asyncio.TimeoutError:
                    print(f'  ⏱ timeout')
                    break
            
            if not got_ai_move:
                print(f'  ⚠️ AI did not respond')
                break
        
        print(f'\n  📊 Result: {moves_played}/{len(my_moves)} moves exchanged')
        await ws.send(json.dumps({'type': 'leave_room'}))
        await asyncio.sleep(0.5)
        return moves_played > 0


async def main():
    results = {}
    
    # Gomoku: I'm black (first), moves are {row, col}
    results['gomoku'] = await play_game('gomoku', [
        {'row': 7, 'col': 7},
        {'row': 6, 'col': 6},
        {'row': 5, 'col': 5},
    ], preferred_side='first')
    
    # Chess: I'm white (first), moves are {uci}
    results['chess'] = await play_game('chess', [
        {'uci': 'e2e4'},
        {'uci': 'd2d4'},
        {'uci': 'g1f3'},
    ], preferred_side='first')
    
    # Xiangqi: I'm red (first). Red is Row 0-4, Cannon at Row 2
    # Move: Cannon from (2,1) to (2,4) — 炮二平五
    results['xiangqi'] = await play_game('xiangqi', [
        {'fromRow': 2, 'fromCol': 1, 'toRow': 2, 'toCol': 4},
        {'fromRow': 0, 'fromCol': 1, 'toRow': 2, 'toCol': 2},
    ], preferred_side='first')
    
    print(f'\n{"="*50}')
    print('SUMMARY')
    print(f'{"="*50}')
    for game, ok in results.items():
        status = '✅ PASS' if ok else '❌ FAIL'
        print(f'  {game}: {status}')

asyncio.run(main())
