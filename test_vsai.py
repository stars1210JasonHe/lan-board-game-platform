#!/usr/bin/env python3
"""Quick test for vsAI mode: creates a vsAI room, readies up, makes a move, checks if AI responds."""
import asyncio, json, sys
import websockets

async def test_vsai(game_type='gomoku', ai_type='euler'):
    uri = "ws://localhost:8765"
    print(f"Testing vsAI: {game_type} / {ai_type}")
    async with websockets.connect(uri) as ws:
        # Identify
        await ws.send(json.dumps({"type": "identify", "nick": "TestPlayer"}))
        msg = json.loads(await ws.recv())
        client_id = msg.get("clientId")
        print(f"  Identified: {client_id}")
        # Consume rooms_list
        msg = json.loads(await ws.recv())

        # Create vsAI room
        await ws.send(json.dumps({
            "type": "create_room", "gameType": game_type,
            "withAi": True, "aiType": ai_type, "difficulty": "easy"
        }))

        room_id = None
        match_started = False
        ai_moved = False
        my_side = None
        game_state = None
        ready_sent = False
        move_sent = False
        msgs_received = []

        async def recv_timeout(timeout=5):
            try:
                return json.loads(await asyncio.wait_for(ws.recv(), timeout))
            except asyncio.TimeoutError:
                return None

        # Process messages for up to 20 seconds
        deadline = asyncio.get_event_loop().time() + 20
        while asyncio.get_event_loop().time() < deadline:
            msg = await recv_timeout(3)
            if not msg:
                if not ready_sent:
                    print("  No message, sending ready...")
                    await ws.send(json.dumps({"type": "ready"}))
                    ready_sent = True
                    continue
                if match_started and not move_sent:
                    break
                if move_sent and not ai_moved:
                    break
                continue

            t = msg.get("type")
            msgs_received.append(t)

            if t == "room_joined":
                room_id = msg.get("roomId")
                print(f"  Joined room: {room_id}")

            elif t == "room_state":
                room = msg.get("room", {})
                players = room.get("players", {})
                game_state = room.get("gameState")
                print(f"  Room state: {room.get('state')}, players: {len(players)}")
                for pid, p in players.items():
                    print(f"    {p.get('nick')}: side={p.get('side')}, ready={p.get('ready')}, isAi={p.get('isAi')}")
                    if pid == client_id:
                        my_side = p.get("side")
                if not ready_sent and room.get("state") == "waiting":
                    await ws.send(json.dumps({"type": "ready"}))
                    ready_sent = True
                    print("  Sent ready")

            elif t == "match_start":
                match_started = True
                sides = msg.get("sides", {})
                my_side = sides.get(client_id)
                game_state = msg.get("gameState")
                print(f"  Match started! My side: {my_side}")

                # Make a move if it's our turn
                if game_state and not move_sent:
                    cur = game_state.get("currentPlayerName", game_state.get("currentPlayer"))
                    print(f"  Current turn: {cur}")
                    if cur == my_side or game_state.get("currentPlayer") == my_side:
                        if game_type == "gomoku":
                            move = {"row": 7, "col": 7}
                        elif game_type == "xiangqi":
                            move = {"fromRow": 3, "fromCol": 4, "toRow": 4, "toCol": 4}  # Red pawn forward
                        else:
                            move = {"uci": "e2e4"}
                        print(f"  Sending move: {move}")
                        await ws.send(json.dumps({"type": "move", "move": move}))
                        move_sent = True

            elif t == "move":
                side = msg.get("side")
                move = msg.get("move")
                game_state = msg.get("gameState")
                print(f"  Move by {side}: {move}")
                if side != my_side:
                    ai_moved = True
                    print(f"  ✅ AI responded with a move!")
                elif not move_sent:
                    # It's still our turn after match_start
                    pass
                # If our move was accepted and we haven't seen AI move yet, wait
                if side == my_side and not ai_moved and not game_state.get("finished"):
                    # Wait for AI response
                    continue

            elif t == "match_end":
                print(f"  Match ended: {msg.get('result')}")
                break

            elif t == "chat":
                cm = msg.get("message", {})
                print(f"  Chat [{cm.get('nick')}]: {cm.get('text', '')[:50]}")

            elif t == "error":
                print(f"  ❌ Error: {msg.get('msg')}")

        print(f"\n  Result: match_started={match_started}, move_sent={move_sent}, ai_moved={ai_moved}")
        print(f"  Messages received: {msgs_received}")
        if ai_moved:
            print(f"  ✅ PASS: AI played in vsAI mode")
        else:
            print(f"  ❌ FAIL: AI did NOT play in vsAI mode")
        return ai_moved

async def main():
    games = [
        ("gomoku", "euler"),
        ("gomoku", "engine"),
        ("chess", "euler"),
        ("chess", "engine"),
        ("xiangqi", "euler"),
        ("xiangqi", "engine"),
    ]
    results = {}
    for gt, ai in games:
        print(f"\n{'='*60}")
        ok = await test_vsai(gt, ai)
        results[f"{gt}/{ai}"] = ok
        await asyncio.sleep(1)

    print(f"\n{'='*60}")
    print("Summary:")
    all_pass = True
    for k, v in results.items():
        status = 'PASS' if v else 'FAIL'
        print(f"  {k}: {status}")
        if not v:
            all_pass = False
    print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILED'}")

asyncio.run(main())
