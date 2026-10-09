"""
Ollama LLM Client
Handles chat completions with local Ollama server
"""

import os
import json
import ollama
from typing import Optional, List, Dict


class LLMClient:
    def __init__(self, model: str = "gemma4:31b-cloud", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.client = ollama.Client(host=base_url)
        self.enabled = False

        # Token usage tracking (cumulative + last request)
        self.prompt_tokens_total = 0
        self.eval_tokens_total = 0
        self.last_prompt_tokens = 0
        self.last_eval_tokens = 0
        self.token_state_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "token_usage_state.json",
        )

    def _record_token_usage(self, response):
        """Accumulate token counts from an Ollama response and persist to disk."""
        prompt_tokens = getattr(response, 'prompt_eval_count', None) or 0
        eval_tokens = getattr(response, 'eval_count', None) or 0

        self.last_prompt_tokens = prompt_tokens
        self.last_eval_tokens = eval_tokens
        self.prompt_tokens_total += prompt_tokens
        self.eval_tokens_total += eval_tokens

        state = {
            'last_prompt_tokens': self.last_prompt_tokens,
            'last_eval_tokens': self.last_eval_tokens,
            'total_prompt_tokens': self.prompt_tokens_total,
            'total_eval_tokens': self.eval_tokens_total,
            'model': self.model,
        }
        try:
            with open(self.token_state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[LLM] Failed to write token state: {e}")
    
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
        """Send message and get response (auto-reconnects if not connected)"""
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': message})
            
            response = self.client.chat(model=self.model, messages=messages)
            self.enabled = True
            self._record_token_usage(response)
            return response['message']['content']
        except Exception as e:
            return f"Error: {e}"

    async def chat_with_tools(self, message: str, system_prompt: Optional[str] = None,
                              tools: Optional[List[Dict]] = None):
        """Send a message with tool definitions and return (content, tool_calls).

        Returns a tuple of (text_content, tool_calls). tool_calls is a list of
        raw tool-call dicts (each with a 'function' containing 'name'/'arguments').
        """
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': message})

            kwargs = {'model': self.model, 'messages': messages}
            if tools:
                kwargs['tools'] = tools

            response = self.client.chat(**kwargs)
            self.enabled = True
            self._record_token_usage(response)
            content = response['message'].get('content', '') or ''
            tool_calls = response['message'].get('tool_calls', []) or []
            return content, tool_calls
        except Exception as e:
            return f"Error: {e}", []

    async def chat_with_image(self, message: str, image_base64: str,
                              system_prompt: Optional[str] = None) -> str:
        """Send a message with an attached image (base64) to a multimodal model."""
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({
                'role': 'user',
                'content': message,
                'images': [image_base64],
            })
            response = self.client.chat(model=self.model, messages=messages)
            self.enabled = True
            self._record_token_usage(response)
            return response['message']['content']
        except Exception as e:
            return f"Error: {e}"

    def chat_sync(self, message: str, system_prompt: Optional[str] = None) -> str:
        """Synchronous version of chat (for use in non-async contexts)."""
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': message})
            
            response = self.client.chat(model=self.model, messages=messages)
            self.enabled = True
            self._record_token_usage(response)
            return response['message']['content']
        except Exception as e:
            return ""
