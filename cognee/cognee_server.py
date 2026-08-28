"""
Cognee Memory API Server
Runs in the 'cognee' conda environment
Main app communicates via HTTP on port 8011
"""

import os
from pathlib import Path

# Load .env BEFORE importing cognee
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Remove OpenAI env vars to prevent fallback
for key in list(os.environ.keys()):
    if "OPENAI" in key:
        del os.environ[key]

import asyncio
import cognee
from quart import Quart, request, jsonify
from quart_cors import cors

app = Quart(__name__)
app = cors(app, allow_origin="*")

initialized = False
remember_lock = asyncio.Lock()


async def initialize_cognee():
    """Initialize Cognee with local Ollama settings"""
    global initialized
    if initialized:
        return

    await cognee.remember("Cognee memory server initialized")
    initialized = True
    print("✓ Cognee ready")
    print(f"  LLM: {os.environ.get('LLM_MODEL')}")
    print(f"  Embeddings: {os.environ.get('EMBEDDING_MODEL')}")


def serialize_results(results):
    """Convert Cognee response objects to JSON-serializable strings"""
    serialized = []
    for r in results:
        if hasattr(r, 'content'):
            serialized.append(str(r.content))
        elif hasattr(r, 'text'):
            serialized.append(str(r.text))
        else:
            serialized.append(str(r))
    return serialized


@app.route('/remember', methods=['POST'])
async def remember():
    """Add message to memory (serialized to avoid overwhelming the graph)"""
    try:
        await initialize_cognee()
        data = await request.get_json()

        speaker = data.get('speaker', 'Unknown')
        text = data.get('text', '')
        source = data.get('source', 'chat')
        session_id = data.get('session_id', None)

        formatted = f"[{source}] {speaker}: {text}"

        # Serialize remember operations so they don't pile up
        async with remember_lock:
            if session_id:
                await cognee.remember(formatted, session_id=session_id)
            await cognee.remember(formatted)

        return jsonify({"status": "ok", "message": "Remembered"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/recall', methods=['POST'])
async def recall():
    """Query memory"""
    try:
        await initialize_cognee()
        data = await request.get_json()

        query = data.get('query', 'recent conversation')
        session_id = data.get('session_id', None)
        top_k = data.get('top_k', 10)

        if session_id:
            results = await cognee.recall(query, session_id=session_id)
            if results:
                return jsonify({
                    "status": "ok",
                    "results": serialize_results(results),
                    "source": "session"
                })

        results = await cognee.recall(query)
        return jsonify({
            "status": "ok",
            "results": serialize_results(results)[:top_k],
            "source": "graph"
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/health', methods=['GET'])
async def health():
    """Health check with auto-initialization"""
    global initialized
    if not initialized:
        try:
            await initialize_cognee()
        except Exception as e:
            return jsonify({"status": "error", "initialized": False, "error": str(e)}), 500
    return jsonify({"status": "ok", "initialized": initialized})


@app.route('/settings', methods=['GET'])
async def get_settings():
    """Get current Cognee settings"""
    return jsonify({
        'llm_provider': os.environ.get('LLM_PROVIDER', ''),
        'llm_model': os.environ.get('LLM_MODEL', ''),
        'llm_endpoint': os.environ.get('LLM_ENDPOINT', ''),
        'embedding_provider': os.environ.get('EMBEDDING_PROVIDER', ''),
        'embedding_model': os.environ.get('EMBEDDING_MODEL', ''),
        'embedding_endpoint': os.environ.get('EMBEDDING_ENDPOINT', ''),
        'embedding_dimensions': os.environ.get('EMBEDDING_DIMENSIONS', ''),
        'data_root_directory': os.environ.get('DATA_ROOT_DIRECTORY', ''),
        'system_root_directory': os.environ.get('SYSTEM_ROOT_DIRECTORY', ''),
        'caching': os.environ.get('CACHING', ''),
        'auto_feedback': os.environ.get('AUTO_FEEDBACK', '')
    })


@app.route('/settings', methods=['POST'])
async def update_settings():
    """Update Cognee settings (writes to .env)"""
    data = await request.get_json()
    
    env_path = Path(__file__).parent / ".env"
    
    # Read current .env
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    
    # Map of settings to update
    updates = {
        'LLM_MODEL': data.get('llm_model'),
        'LLM_ENDPOINT': data.get('llm_endpoint'),
        'EMBEDDING_MODEL': data.get('embedding_model'),
        'EMBEDDING_ENDPOINT': data.get('embedding_endpoint'),
        'EMBEDDING_DIMENSIONS': data.get('embedding_dimensions'),
        'CACHING': data.get('caching'),
        'AUTO_FEEDBACK': data.get('auto_feedback')
    }
    
    # Update existing lines or add new ones
    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            key = stripped.split('=')[0].strip()
            if key in updates and updates[key] is not None:
                new_lines.append(f'{key}="{updates[key]}"')
                updated_keys.add(key)
                continue
        new_lines.append(line)
    
    # Add any new keys not in file
    for key, value in updates.items():
        if value is not None and key not in updated_keys:
            new_lines.append(f'{key}="{value}"')
    
    env_path.write_text('\n'.join(new_lines) + '\n')
    
    return jsonify({'status': 'ok', 'message': 'Settings saved. Restart Cognee server to apply.'})


if __name__ == '__main__':
    print("=" * 60)
    print("Cognee Memory API Server")
    print("=" * 60)
    print(f"URL: http://127.0.0.1:8011")
    print("=" * 60)

    app.run(host='127.0.0.1', port=8011)
