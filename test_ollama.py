#!/usr/bin/env python
"""Test Ollama LLM connection"""

import ollama

MODEL = "gemma4:31b-cloud"

def test_connection():
    """Test basic chat completion"""
    try:
        print(f"Testing Ollama connection with {MODEL}...")
        response = ollama.chat(
            model=MODEL,
            messages=[{'role': 'user', 'content': 'Say hello in one short sentence.'}]
        )
        print(f"✓ Connected!")
        print(f"  Model: {MODEL}")
        print(f"  Response: {response['message']['content']}")
        return True
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

if __name__ == "__main__":
    test_connection()
