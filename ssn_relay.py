"""
Local SSN Relay Server
Mimics the io.socialstream.ninja WebSocket relay protocol locally.

Protocol:
- Clients connect via WebSocket to ws://127.0.0.1:3000
- Join a room: {"join": "SESSION_ID", "out": X, "in": Y}
- Send chat:   {"action": "sendChat", "value": "text", "target": "twitch"}
- Receive chat on the channel they subscribed to via "in"

This removes the cloud dependency (io.socialstream.ninja) entirely.
"""

import asyncio
import json
import websockets
from collections import defaultdict

HOST = "127.0.0.1"
PORT = 3000

# room_id -> list of client connections
rooms = defaultdict(set)

# (room_id, websocket) -> {"in": int, "out": int}
client_channels = {}


async def handle_connection(websocket):
    """Handle a single WebSocket client connection"""
    peer = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    print(f"[+] Client connected: {peer}")

    room_id = None
    in_channel = 1
    out_channel = 1

    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            # Handle join message
            if "join" in message:
                room_id = message["join"]
                in_channel = message.get("in", 1)
                out_channel = message.get("out", 1)

                rooms[room_id].add(websocket)
                client_channels[(room_id, websocket)] = {
                    "in": in_channel,
                    "out": out_channel,
                }
                print(f"[join] {peer} -> room '{room_id}' (in={in_channel}, out={out_channel})")
                continue

            # Handle sendChat action
            if message.get("action") == "sendChat":
                if room_id is None:
                    continue

                value = message.get("value", "")
                target = message.get("target", "")

                # Build the chat message payload (mimics SSN format)
                chat_payload = {
                    "chatname": "Gem",
                    "chatmessage": value,
                    "type": target or "api",
                    "textonly": True,
                }

                # Broadcast to all clients in the room subscribed to this channel
                await broadcast_to_room(room_id, out_channel, chat_payload, exclude=websocket)
                print(f"[sendChat] {peer} -> room '{room_id}' ch{out_channel}: {value[:50]}")
                continue

            # Handle other actions (echo back a simple ack)
            if "action" in message:
                print(f"[action] {peer}: {message.get('action')}")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if room_id:
            rooms[room_id].discard(websocket)
            client_channels.pop((room_id, websocket), None)
            if not rooms[room_id]:
                del rooms[room_id]
        print(f"[-] Client disconnected: {peer}")


async def broadcast_to_room(room_id, out_channel, payload, exclude=None):
    """Send payload to all clients in a room subscribed to the given input channel"""
    if room_id not in rooms:
        return

    for client in list(rooms[room_id]):
        if client is exclude:
            continue
        info = client_channels.get((room_id, client))
        if info is None:
            continue
        # Deliver if the client's "in" channel matches the sender's "out" channel
        if info["in"] == out_channel:
            try:
                await client.send(json.dumps(payload))
            except Exception:
                pass


async def main():
    print("=" * 60)
    print("Local SSN Relay Server")
    print("=" * 60)
    print(f"Listening on ws://{HOST}:{PORT}")
    print("Point SSN at this via &localserver (or &localserverport=3000)")
    print("=" * 60)

    async with websockets.serve(handle_connection, HOST, PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
