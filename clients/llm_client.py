"""
Ollama LLM Client
Handles chat completions with local Ollama server
"""

import ollama
from typing import Optional, List, Dict


class LLMClient:
    def __init__(self, model: str = "gemma4:31b-cloud", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.client = ollama.Client(host=base_url)
        self.enabled = False
    
    async def check_connection(self) -> bool:
        """Test connection to Ollama"""
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': 'Hi'}]
            )
            self.enabled = True
            print(f"✓ LLM connected: {self.model}")
            return True
        except Exception as e:
            print(f"✗ LLM connection failed: {e}")
            self.enabled = False
            return False
    
    async def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
        """Send message and get response"""
        if not self.enabled:
            return "LLM not connected"
        
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': message})
            
            response = self.client.chat(model=self.model, messages=messages)
            return response['message']['content']
        except Exception as e:
            return f"Error: {e}"
