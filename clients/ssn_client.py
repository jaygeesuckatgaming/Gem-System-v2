"""
Social Stream Ninja Client
Handles HTTP and WebSocket communication with SSN server
"""

import httpx
import websockets
import json
import asyncio
from typing import List, Optional, Callable


class SSNClient:
    def __init__(self, api_url: str, session_id: str):
        self.api_url = api_url.rstrip('/')
        self.session_id = session_id
        self.ws_url = "wss://io.socialstream.ninja:443"
        self.enabled = False
        self.on_message: Optional[Callable] = None  # Callback for incoming messages
    
    async def check_connection(self) -> bool:
        """Verify SSN is configured (no GET endpoint available)"""
        if not self.session_id:
            print(f"✗ SSN not configured: session_id is empty")
            self.enabled = False
            return False
        
        self.enabled = True
        print(f"✓ SSN configured: {self.api_url} (session: {self.session_id})")
        return True
    
    async def send_message(self, text: str, targets: Optional[List[str]] = None, max_length: int = 200) -> bool:
        """Send message to social platforms via HTTP POST.
        Splits long messages into multiple posts (default 200 chars each)."""
        if not self.enabled:
            return False
        
        if not targets:
            targets = ['discord', 'twitch', 'youtube']
        
        # Split text into chunks of max_length characters (on word boundaries)
        chunks = self._split_text(text, max_length)
        
        success = False
        async with httpx.AsyncClient(timeout=10) as client:
            for target in targets:
                for chunk in chunks:
                    try:
                        payload = {
                            "action": "sendChat",
                            "value": chunk,
                            "target": target
                        }
                        response = await client.post(
                            f"{self.api_url}/{self.session_id}",
                            json=payload
                        )
                        print(f"  → SSN sent to {target}. Status: {response.status_code}, Reply: {response.text[:200]}")
                        if response.status_code == 200:
                            success = True
                    except Exception as e:
                        print(f"  ✗ SSN failed for {target}: {e}")
        
        return success
    
    @staticmethod
    def _split_text(text: str, max_length: int) -> List[str]:
        """Split text into chunks of at most max_length characters, breaking on word boundaries."""
        text = text.strip()
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        words = text.split()
        current = ""
        
        for word in words:
            # If a single word is longer than max_length, hard-split it
            if len(word) > max_length:
                if current:
                    chunks.append(current.strip())
                    current = ""
                for i in range(0, len(word), max_length):
                    chunks.append(word[i:i+max_length])
                continue
            
            # Try adding the word to the current chunk
            test = f"{current} {word}".strip()
            if len(test) <= max_length:
                current = test
            else:
                if current:
                    chunks.append(current.strip())
                current = word
        
        if current:
            chunks.append(current.strip())
        
        return chunks
    
    async def start_websocket_listener(self):
        """Start WebSocket listener for incoming chat messages (with reconnect)"""
        if not self.enabled:
            return
        
        # Chat messages are broadcast on channel 4 (per SSN API docs)
        join_payload = {"join": self.session_id, "out": 1, "in": 4}
        
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await ws.send(json.dumps(join_payload))
                    print(f"✓ SSN WebSocket connected (listening on channel 4)")
                    
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if self.on_message:
                                await self.on_message(data)
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                print(f"✗ SSN WebSocket error: {e}. Reconnecting in 5s...")
            
            # Reconnect after a delay
            await asyncio.sleep(5)
