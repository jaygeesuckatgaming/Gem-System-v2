"""
Social Stream Ninja Client
Handles HTTP and WebSocket communication with SSN server
"""

import httpx
import websockets
import json
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
    
    async def send_message(self, text: str, targets: Optional[List[str]] = None) -> bool:
        """Send message to social platforms via HTTP POST"""
        if not self.enabled:
            return False
        
        if not targets:
            targets = ['discord', 'twitch', 'youtube']
        
        success = False
        async with httpx.AsyncClient(timeout=10) as client:
            for target in targets:
                try:
                    payload = {
                        "action": "sendChat",
                        "value": text,
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
    
    async def start_websocket_listener(self):
        """Start WebSocket listener for incoming chat messages"""
        if not self.enabled:
            return
        
        join_payload = {"join": self.session_id, "out": 0, "in": 1}
        
        try:
            async with websockets.connect(self.ws_url) as ws:
                await ws.send(json.dumps(join_payload))
                print(f"✓ SSN WebSocket connected")
                
                async for message in ws:
                    try:
                        data = json.loads(message)
                        if self.on_message:
                            await self.on_message(data)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"✗ SSN WebSocket error: {e}")
