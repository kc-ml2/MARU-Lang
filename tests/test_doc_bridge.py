"""DocBridge round-trip: REPL ↔ browser relay (no real browser)."""
import asyncio
import json

import websockets

from maru_lang.commands.doc_bridge import DocBridge


async def test_bridge_relays_canvas_and_returns_resume():
    bridge = DocBridge()
    await bridge.start()
    assert bridge.port and bridge._html_path  # HTML written, port assigned
    try:
        async with websockets.connect(f"ws://127.0.0.1:{bridge.port}") as ws:
            await asyncio.sleep(0.05)  # let the server register the client

            # REPL → browser: canvas + interrupt are relayed
            await bridge.send_canvas({"title": "계약서", "sections": []})
            msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert msg["type"] == "canvas" and msg["canvas"]["title"] == "계약서"

            await bridge.send_interrupt({"type": "awaiting_edit", "canvas_id": "c1"})
            msg2 = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert msg2["type"] == "interrupt" and msg2["content"]["type"] == "awaiting_edit"

            # browser → REPL: an edit command comes back through await_resume
            await ws.send(json.dumps({"op": "finalize"}))
            resume = await asyncio.wait_for(bridge.await_resume(), 2)
            assert resume == {"op": "finalize"}
    finally:
        await bridge.stop()


async def test_bridge_sends_current_state_to_late_client():
    bridge = DocBridge()
    await bridge.start()
    try:
        await bridge.send_canvas({"title": "T", "sections": []})
        # a browser that connects afterwards should get the current canvas
        async with websockets.connect(f"ws://127.0.0.1:{bridge.port}") as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert msg["type"] == "canvas" and msg["canvas"]["title"] == "T"
    finally:
        await bridge.stop()
