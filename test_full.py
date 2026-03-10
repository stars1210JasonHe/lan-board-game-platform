#!/usr/bin/env python3
"""Full game platform test suite — covers all major flows."""
import asyncio, json, sys, time
import websockets

WS_URI = "ws://localhost:8765"
TIMEOUT = 30  # seconds per test

results = []

async def recv_until(ws, msg_types, timeout=TIMEOUT):
    """Receive messages until we get one of the expected types or timeout."""
    collected = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - time.time()))
            msg = json.loads(raw)
            collected.append(msg)
            if msg.get("type") in msg_types:
                return msg, collected
        except asyncio.TimeoutError:
            break
    return None, collected

async def recv_all(ws, duration=3):
    """Collect all messages for a duration."""
    collected = []
    deadline = time.time() + duration
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
            collected.append(json.loads(raw))
        except asyncio.TimeoutError:
            break
    return collected

async def identify(ws, nick):
    await ws.send(json.dumps({"type": "identify", "nick": nick}))
    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    client_id = msg.get("clientId")
    # consume rooms_list
    await asyncio.wait_for(ws.recv(), timeout=5)
    return client_id

# ============================================================
# Test 1: vsAI Engine — basic flow
# ============================================================
async def test_vsai_engine():
    name = "vsAI Engine (gomoku)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws:
            cid = await identify(ws, "Test_Engine")
            await ws.send(json.dumps({
                "type": "create_room", "gameType": "gomoku",
                "withAi": True, "aiType": "engine", "difficulty": "easy"
            }))
            # Wait for match_start
            msg, _ = await recv_until(ws, ["match_start"], timeout=15)
            if not msg:
                print(f"  ❌ FAIL: match never started")
                results.append((name, False, "match never started"))
                return
            print(f"  Match started, side: {msg.get('yourSide')}")
            # Make a move
            await ws.send(json.dumps({"type": "move", "move": {"row": 7, "col": 7}}))
            # Wait for AI move
            msg, collected = await recv_until(ws, ["move"], timeout=15)
            ai_moved = any(m.get("type") == "move" and m.get("side") != msg.get("yourSide", "black") for m in collected) if msg else False
            if ai_moved or (msg and msg.get("type") == "move"):
                print(f"  ✅ PASS")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: AI didn't respond")
                results.append((name, False, "AI didn't respond"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 2: vsAI Euler — don't send extra ready
# ============================================================
async def test_vsai_euler():
    name = "vsAI Euler/OpenClaw (gomoku)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws:
            cid = await identify(ws, "Test_Euler")
            await ws.send(json.dumps({
                "type": "create_room", "gameType": "gomoku",
                "withAi": True, "aiType": "euler", "difficulty": "easy"
            }))
            # Do NOT send ready — server auto-readies in vsAI euler mode
            # Wait for match_start
            msg, collected = await recv_until(ws, ["match_start"], timeout=30)
            if not msg:
                # Check if AI even joined
                ai_joined = any("OpenClaw" in str(m) for m in collected)
                print(f"  ❌ FAIL: match never started (AI joined: {ai_joined})")
                results.append((name, False, f"match never started, AI joined={ai_joined}"))
                return
            my_side = msg.get("yourSide")
            print(f"  Match started, side: {my_side}")
            # If we're first, make a move
            if my_side == "black":
                await ws.send(json.dumps({"type": "move", "move": {"row": 7, "col": 7}}))
            # Wait for AI move
            msg2, collected2 = await recv_until(ws, ["move"], timeout=30)
            if msg2:
                print(f"  ✅ PASS: AI responded")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: AI didn't move")
                results.append((name, False, "AI didn't move after match start"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 3: Human vs Human — basic flow
# ============================================================
async def test_human_vs_human():
    name = "Human vs Human (chess)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws1, websockets.connect(WS_URI) as ws2:
            cid1 = await identify(ws1, "Player1")
            cid2 = await identify(ws2, "Player2")

            # P1 creates room
            await ws1.send(json.dumps({"type": "create_room", "gameType": "chess"}))
            msg, _ = await recv_until(ws1, ["room_joined"], timeout=5)
            room_id = msg.get("roomId") if msg else None
            if not room_id:
                print(f"  ❌ FAIL: room not created")
                results.append((name, False, "room not created"))
                return
            print(f"  Room: {room_id}")

            # P2 joins
            await ws2.send(json.dumps({"type": "join_room", "roomId": room_id}))
            await recv_until(ws2, ["room_joined"], timeout=5)

            # Both ready
            await ws1.send(json.dumps({"type": "ready"}))
            await asyncio.sleep(0.5)
            await ws2.send(json.dumps({"type": "ready"}))

            # Wait for match_start on both
            msg1, _ = await recv_until(ws1, ["match_start"], timeout=10)
            if msg1:
                print(f"  ✅ PASS: match started, P1 side={msg1.get('yourSide')}")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: match didn't start")
                results.append((name, False, "match didn't start after both ready"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 4: Chat functionality
# ============================================================
async def test_chat():
    name = "Chat (in room)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws1, websockets.connect(WS_URI) as ws2:
            cid1 = await identify(ws1, "ChatP1")
            cid2 = await identify(ws2, "ChatP2")

            await ws1.send(json.dumps({"type": "create_room", "gameType": "gomoku"}))
            msg, _ = await recv_until(ws1, ["room_joined"], timeout=5)
            room_id = msg["roomId"]

            await ws2.send(json.dumps({"type": "join_room", "roomId": room_id}))
            await recv_until(ws2, ["room_joined"], timeout=5)
            await asyncio.sleep(0.5)

            # P1 sends chat
            test_msg = "Hello from test! 你好测试"
            await ws1.send(json.dumps({"type": "chat", "text": test_msg}))

            # P2 should receive it
            msg, collected = await recv_until(ws2, ["chat"], timeout=5)
            if msg and test_msg in str(msg):
                print(f"  ✅ PASS: chat received")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: chat not received")
                results.append((name, False, "chat message not delivered"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 5: Reconnection (sessionStorage simulation)
# ============================================================
async def test_reconnection():
    name = "Reconnection (rejoin)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        # Connect, create room, then disconnect and reconnect
        async with websockets.connect(WS_URI) as ws1:
            cid1 = await identify(ws1, "ReconnP1")
            await ws1.send(json.dumps({"type": "create_room", "gameType": "gomoku"}))
            msg, _ = await recv_until(ws1, ["room_joined"], timeout=5)
            room_id = msg["roomId"]
            print(f"  Room: {room_id}, clientId: {cid1}")

        # Reconnect with same clientId
        await asyncio.sleep(1)
        async with websockets.connect(WS_URI) as ws_new:
            await ws_new.send(json.dumps({"type": "identify", "nick": "ReconnP1", "clientId": cid1}))
            msg = json.loads(await asyncio.wait_for(ws_new.recv(), timeout=5))
            new_cid = msg.get("clientId")
            # consume rooms_list
            await asyncio.wait_for(ws_new.recv(), timeout=5)

            # Try to rejoin
            await ws_new.send(json.dumps({"type": "join_room", "roomId": room_id}))
            msg, collected = await recv_until(ws_new, ["room_joined", "room_state"], timeout=5)
            if msg:
                print(f"  ✅ PASS: reconnected to room {room_id}")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: could not rejoin")
                results.append((name, False, "rejoin failed"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 6: vsAI Engine Chess
# ============================================================
async def test_vsai_engine_chess():
    name = "vsAI Engine (chess)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws:
            cid = await identify(ws, "Test_Chess")
            await ws.send(json.dumps({
                "type": "create_room", "gameType": "chess",
                "withAi": True, "aiType": "engine", "difficulty": "easy"
            }))
            msg, _ = await recv_until(ws, ["match_start"], timeout=15)
            if not msg:
                print(f"  ❌ FAIL: match never started")
                results.append((name, False, "match never started"))
                return
            my_side = msg.get("yourSide")
            print(f"  Match started, side: {my_side}")
            # If white, make e2e4
            if my_side == "white":
                await ws.send(json.dumps({"type": "move", "move": "e2e4"}))
            msg2, _ = await recv_until(ws, ["move"], timeout=15)
            if msg2:
                print(f"  ✅ PASS: move exchange working")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: no move response")
                results.append((name, False, "no move after match start"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 7: vsAI Engine Xiangqi
# ============================================================
async def test_vsai_engine_xiangqi():
    name = "vsAI Engine (xiangqi)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws:
            cid = await identify(ws, "Test_Xiangqi")
            await ws.send(json.dumps({
                "type": "create_room", "gameType": "xiangqi",
                "withAi": True, "aiType": "engine", "difficulty": "easy"
            }))
            msg, _ = await recv_until(ws, ["match_start"], timeout=15)
            if not msg:
                print(f"  ❌ FAIL: match never started")
                results.append((name, False, "match never started"))
                return
            my_side = msg.get("yourSide")
            print(f"  Match started, side: {my_side}")
            if my_side == "red":
                # Move cannon: row 2 col 1 → row 2 col 4 (common opening — red is at rows 0-4)
                await ws.send(json.dumps({"type": "move", "move": {"fromRow": 2, "fromCol": 1, "toRow": 2, "toCol": 4}}))
            msg2, _ = await recv_until(ws, ["move"], timeout=15)
            if msg2:
                print(f"  ✅ PASS: move exchange working")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: no move response")
                results.append((name, False, "no move after match start"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Test 8: OpenClaw naming check
# ============================================================
async def test_openclaw_naming():
    name = "OpenClaw naming (not Euler)"
    print(f"\n{'='*60}\nTest: {name}")
    try:
        async with websockets.connect(WS_URI) as ws:
            cid = await identify(ws, "Test_Name")
            await ws.send(json.dumps({
                "type": "create_room", "gameType": "gomoku",
                "withAi": True, "aiType": "euler", "difficulty": "easy"
            }))
            _, collected = await recv_until(ws, ["match_start"], timeout=20)
            all_text = json.dumps(collected)
            has_openclaw = "OpenClaw" in all_text
            has_euler_old = "Euler 🤖" in all_text and "OpenClaw" not in all_text
            if has_openclaw and not has_euler_old:
                print(f"  ✅ PASS: using 'OpenClaw' naming")
                results.append((name, True, ""))
            else:
                print(f"  ❌ FAIL: still using old Euler naming")
                results.append((name, False, "old Euler naming detected"))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append((name, False, str(e)))

# ============================================================
# Run all tests
# ============================================================
async def main():
    print("🎮 Game Platform Full Test Suite")
    print(f"Server: {WS_URI}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    await test_vsai_engine()
    await test_vsai_euler()
    await test_human_vs_human()
    await test_chat()
    await test_reconnection()
    await test_vsai_engine_chess()
    await test_vsai_engine_xiangqi()
    await test_openclaw_naming()

    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    for name, ok, err in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}" + (f" — {err}" if err else ""))
    print(f"\n  Total: {passed} passed, {failed} failed out of {len(results)}")

if __name__ == "__main__":
    asyncio.run(main())
