"""
Vision Service Client
Communicates with the vision service (vision.py) on port 5001
Provides camera image capture and scene description
"""

import httpx
from typing import Optional


class VisionClient:
    def __init__(self, scan_url: str = "http://127.0.0.1:5001/scan",
                 get_image_url: str = "http://127.0.0.1:5001/get_image"):
        self.scan_url = scan_url
        self.get_image_url = get_image_url
        self.enabled = False

    async def check_connection(self) -> bool:
        """Check if vision service is running"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.get_image_url)
                self.enabled = True
                print(f"✓ Vision service connected: {self.get_image_url}")
                return True
        except Exception as e:
            print(f"✗ Vision service not available: {e}")
            self.enabled = False
        return False

    async def get_scene_description(self) -> Optional[str]:
        """Get a text description of the current scene (requires local VLM)"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.scan_url)
                if response.status_code == 200:
                    return response.json().get("vision_context")
        except Exception as e:
            print(f"✗ Vision scan failed: {e}")
        return None

    async def get_image_base64(self) -> Optional[str]:
        """Get a base64-encoded image of the current scene"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.get_image_url)
                if response.status_code == 200:
                    return response.json().get("image_base64")
        except Exception as e:
            print(f"✗ Vision image fetch failed: {e}")
        return None
