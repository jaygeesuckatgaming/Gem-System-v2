"""
StyleTTS2 Client
Communicates with StyleTTS2 server on port 13300
"""

import httpx
import re
from typing import Optional


class TTSClient:
    def __init__(self, tts_url: str = "http://127.0.0.1:13300/tts"):
        self.tts_url = tts_url
        self.enabled = False

    async def check_connection(self) -> bool:
        """Check if StyleTTS2 server is running"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.tts_url.replace('/tts', '/'))
                self.enabled = True
                print(f"✓ TTS connected: {self.tts_url}")
                return True
        except Exception as e:
            print(f"✗ TTS not available: {e}")
            self.enabled = False
        return False

    async def speak(self, text: str) -> bool:
        """Send text to StyleTTS2 for synthesis"""
        if not self.enabled:
            return False

        # Clean text (remove special chars, normalize whitespace)
        clean_text = re.sub(r"[^a-zA-Z0-9\s.,?!'\"():-]", "", text)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        if not clean_text:
            return False

        try:
            payload = {"chatmessage": clean_text}
            print(f"TTS: Synthesizing '{clean_text[:60]}...'")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.tts_url, json=payload)
                if response.status_code == 200:
                    print(f"✓ TTS complete")
                    return True
                else:
                    print(f"✗ TTS failed: {response.status_code}")
                    return False
        except Exception as e:
            print(f"✗ TTS error: {e}")
            return False
