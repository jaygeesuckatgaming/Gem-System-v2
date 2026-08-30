"""
Cognee Memory HTTP Client
Main app communicates with Cognee server on port 8011
"""

import httpx
import asyncio
from typing import List, Optional


class CogneeClient:
    def __init__(self, server_url: str = "http://127.0.0.1:8011"):
        self.server_url = server_url
        self.enabled = False

    async def check_connection(self) -> bool:
        """Check if Cognee server is running"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.server_url}/health")
                if response.status_code == 200:
                    self.enabled = True
                    print(f"✓ Cognee connected: {self.server_url}")
                    return True
        except Exception as e:
            print(f"✗ Cognee not available: {e}")
            self.enabled = False
        return False

    async def remember(self, speaker: str, text: str, source: str = "chat", session_id: Optional[str] = None):
        """Add message to Cognee memory (fire-and-forget, non-blocking)"""

        async def _do_remember():
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    payload = {
                        "speaker": speaker,
                        "text": text,
                        "source": source,
                        "session_id": session_id
                    }
                    response = await client.post(f"{self.server_url}/remember", json=payload)
                    if response.status_code == 200:
                        self.enabled = True
                        print(f"✓ Cognee remembered: {speaker}: {text[:50]}")
            except Exception as e:
                print(f"✗ Cognee remember failed: {e}")

        # Run in background so it doesn't block the chat
        asyncio.create_task(_do_remember())

    async def recall(self, query: str, session_id: Optional[str] = None, top_k: int = 10) -> List[str]:
        """Query Cognee memory (with short timeout to avoid blocking chat)"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "query": query,
                    "session_id": session_id,
                    "top_k": top_k
                }
                response = await client.post(f"{self.server_url}/recall", json=payload)
                if response.status_code == 200:
                    self.enabled = True
                    data = response.json()
                    results = data.get("results", [])
                    source = data.get("source", "unknown")
                    print(f"✓ Cognee recalled {len(results)} items from {source}")
                    return results
        except Exception as e:
            print(f"✗ Cognee recall failed: {e}")
        return []
