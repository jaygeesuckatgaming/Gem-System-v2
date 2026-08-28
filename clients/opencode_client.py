"""
OpenCode API Client
Communicates with OpenCode's HTTP API to execute coding tasks
"""

import httpx
import re
import json
from datetime import datetime
from typing import Optional


class OpenCodeClient:
    def __init__(self, api_url: str = "http://localhost:4096", workspace: str = None):
        self.api_url = api_url.rstrip("/")
        self.workspace = workspace or "."
        self.enabled = False
        self.active_sessions = {}

    async def check_connection(self) -> bool:
        """Check if OpenCode API is running"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.api_url}/session")
                self.enabled = True
                print(f"✓ OpenCode connected: {self.api_url}")
                return True
        except Exception as e:
            print(f"✗ OpenCode not available: {e}")
            self.enabled = False
        return False

    async def create_session(self) -> str:
        """Create a new OpenCode session"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_url}/session",
                json={"title": f"Gem-System Task: {datetime.now().strftime('%H:%M')}"}
            )
            resp.raise_for_status()
            data = resp.json()
            session_id = data.get("id")
            print(f"OPENCODE: Created session {session_id}")
            return session_id

    async def send_prompt(self, session_id: str, prompt: str) -> str:
        """Send prompt as a message and wait for response"""
        print(f"OPENCODE: Sending message to session {session_id}...")

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.api_url}/session/{session_id}/message",
                json={"parts": [{"type": "text", "text": prompt}]},
                timeout=300
            )
            resp.raise_for_status()
            data = resp.json()

            # Extract output from ALL parts
            parts = data.get("parts", [])
            output_parts = []
            for part in parts:
                part_type = part.get("type", "")
                text = part.get("text", "")
                if not text:
                    text = part.get("content", "")
                if not text:
                    text = part.get("value", "")
                if not text:
                    text = json.dumps(part.get("args", part.get("result", "")))
                if text:
                    output_parts.append(str(text))

            full_output = ' '.join(output_parts).strip()

            # Clean up ANSI codes
            full_output = re.sub(r'\x1b\[[0-9;]*m', '', full_output)
            full_output = re.sub(r'\[0m', '', full_output)

            return full_output if full_output else "Task completed"

    async def execute_task(self, prompt: str) -> str:
        """Execute a task using OpenCode API"""
        session_id = await self.create_session()
        self.active_sessions[session_id] = {
            "created": datetime.now(),
            "prompt": prompt
        }

        try:
            # For file listing, modify prompt to get raw output
            if "list" in prompt.lower() and ("file" in prompt.lower() or "dir" in prompt.lower()):
                enhanced_prompt = f"{prompt}\n\nShow the RAW output only. Do not summarize. List each file on a separate line."
            else:
                enhanced_prompt = prompt

            output = await self.send_prompt(session_id, enhanced_prompt)
            return output
        except Exception as e:
            return f"Error: {str(e)}"
        finally:
            # Clean up old sessions (keep last 10)
            if len(self.active_sessions) > 10:
                oldest = sorted(self.active_sessions.keys())[0]
                del self.active_sessions[oldest]


def format_opencode_response(text: str) -> str:
    """Format OpenCode response for better readability in chat"""
    if not text:
        return text

    formatted = text.strip()
    if formatted.startswith('OpenCode:'):
        formatted = formatted[9:].strip()
    formatted = formatted.strip('"')

    # Fix word splitting (remove newlines between words)
    lines = formatted.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line:
            cleaned_lines.append(line)

    formatted = ' '.join(cleaned_lines)

    # Fix spacing around punctuation
    formatted = formatted.replace('  ', ' ')
    formatted = formatted.replace('. ', '.')
    formatted = formatted.replace('.  ', '. ')
    formatted = formatted.replace('? ', '?')
    formatted = formatted.replace('! ', '!')

    # Capitalize first letter
    if formatted:
        formatted = formatted[0].upper() + formatted[1:]

    return formatted
