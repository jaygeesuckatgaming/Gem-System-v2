"""
Test client for the local SSN relay server.
Simulates two clients: a "chat source" (like SSN) and a "listener" (like MCP).
"""

import asyncio
import json
import websockets

RELAY_URL = "ws://127.0.0.1:3000"
SESSION_ID = "test-session"


async def listener():
    """Simulates the MCP listening for chat messages"""
    async with websockets.connect(RELAY_URL) as ws:
        # Join room, listen on channel 4 (where chat is broadcast)
        await ws.send(json.dumps({"join": SESSION_ID, "out": 1, "in": 4}))
        print("[listener] Joined room, listening on channel 4")

        # Wait for messages with a timeout
        try:
            async with asyncio.timeout(5):
                async for message in ws:
                    data = json.loads(message)
                    print(f"[listener] Received: {data}")
        except asyncio.TimeoutError:
            print("[listener] No more messages (timeout)")


async def chat_source():
    """Simulates SSN sending a chat message"""
    await asyncio.sleep(1)  # Wait for listener to connect
    async with websockets.connect(RELAY_URL) as ws:
        # Join room, send on channel 4
        await ws.send(json.dumps({"join": SESSION_ID, "out": 4, "in": 1}))
        print("[source] Joined room, sending on channel 4")

        # Send a chat message
        await ws.send(json.dumps({
            "action": "sendChat",
            "value": "Hello from test!",
            "target": "twitch"
        }))
        print("[source] Sent chat message")

        await asyncio.sleep(2)


async def main():
    print("Testing local SSN relay...")
    await asyncio.gather(
        listener(),
        chat_source(),
    )
    print("Test complete.")


if __name__ == "__main__":
    asyncio.run(main())
