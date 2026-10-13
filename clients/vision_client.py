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

    # --- Face recognition API (vision.py /faces/* endpoints) ---

    async def get_visible_faces(self) -> list:
        """People visible on the stream right now: [{'name', 'known', 'confidence'}]"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self._base_url()}/faces/current")
                if response.status_code == 200:
                    return response.json().get("people", [])
        except Exception:
            pass
        return []

    async def scan_faces_once(self, threshold=None) -> list:
        """One-shot recognition pass (debug): [{'name', 'known', 'confidence',
        'detection', 'width'}]. Optional threshold temporarily overrides the
        detection cutoff for this scan only."""
        try:
            url = f"{self._base_url()}/faces/scan"
            if threshold is not None:
                url += f"?threshold={threshold}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url)
                if response.status_code == 200:
                    return response.json().get("faces", [])
        except Exception as e:
            print(f"✗ Face scan failed: {e}")
        return []

    async def list_enrolled_faces(self) -> list:
        """Names of enrolled people (empty if recognition is off/unavailable)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url()}/faces/list")
                if response.status_code == 200:
                    return response.json().get("people", [])
        except Exception:
            pass
        return []

    async def enroll_face(self, name: str, region=None) -> Optional[str]:
        """Enroll a person from the current frame. Optional region
        [x0, y0, x1, y1] (fractions 0-1 of the frame, from the GUI's
        drag-selection) restricts enrollment to faces inside that box.
        Returns the enrolled name on success, an error message on failure."""
        try:
            payload = {"name": name}
            if region is not None:
                payload["region"] = region
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._base_url()}/faces/enroll", json=payload
                )
                if response.status_code == 200:
                    return response.json().get("name")
                return response.json().get("error", "Enrollment failed")
        except Exception as e:
            return f"Vision service not available: {e}"

    async def refresh_enrollments(self) -> dict:
        """Re-scan the photos/ drop folder: {'enrolled': [...], 'skipped': [...]}"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self._base_url()}/faces/refresh")
                if response.status_code == 200:
                    return response.json()
        except Exception:
            pass
        return {"enrolled": [], "skipped": []}

    async def delete_enrolled_face(self, name: str) -> bool:
        """Delete an enrolled person by name."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.delete(f"{self._base_url()}/faces/{name}")
                return response.status_code == 200 and response.json().get("status") == "ok"
        except Exception:
            pass
        return False

    def _base_url(self) -> str:
        """Derive the vision service base URL from the configured scan URL."""
        # e.g. 'http://127.0.0.1:5001/scan' -> 'http://127.0.0.1:5001'
        from urllib.parse import urlsplit
        parts = urlsplit(self.scan_url)
        return f"{parts.scheme}://{parts.netloc}"

    async def list_ndi_sources(self) -> Optional[list]:
        """NDI source names currently visible on the network (None = service down;
        [] = no sources found)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self._base_url()}/ndi/sources")
                if response.status_code == 200:
                    return response.json().get("sources", [])
        except Exception:
            pass
        return None
