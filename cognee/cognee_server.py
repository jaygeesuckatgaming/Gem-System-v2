"""
Cognee Memory API Server
Runs in the 'cognee' conda environment
Main app communicates via HTTP on port 8011
"""

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

# Load .env BEFORE importing cognee
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Remove OpenAI env vars to prevent fallback
for key in list(os.environ.keys()):
    if "OPENAI" in key:
        del os.environ[key]

import cognee
from quart import Quart, request, jsonify
from quart_cors import cors

app = Quart(__name__)
app = cors(app, allow_origin="*")

initialized = False
remember_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Off-peak self-improvement schedule.
# `remember()` below is called with self_improvement=False, so the graph is not
# rebuilt on every chat message. Instead, cognee.improve() runs as a controlled
# batch job only during the configured off-peak window.
# ---------------------------------------------------------------------------
IMPROVE_SCHEDULER_ENABLED = (
    os.environ.get("IMPROVE_SCHEDULER_ENABLED", "true").strip().lower() != "false"
)
IMPROVE_OFF_PEAK_START = int(os.environ.get("IMPROVE_OFF_PEAK_START", "3"))
IMPROVE_OFF_PEAK_END = int(os.environ.get("IMPROVE_OFF_PEAK_END", "6"))
IMPROVE_MIN_INTERVAL_HOURS = float(os.environ.get("IMPROVE_MIN_INTERVAL_HOURS", "24"))
_last_improve_at = 0.0

# Initialization is slow (loads the LLM + embedding model), so /health must not
# block on it. Health kicks off init in the background and reports the current
# state immediately; /remember and /recall still wait for init.
_initialize_lock = asyncio.Lock()
_init_task = None


async def initialize_cognee():
    """Initialize Cognee with local Ollama settings (idempotent, slow)."""
    global initialized
    if initialized:
        return
    async with _initialize_lock:
        if initialized:
            return
        await cognee.remember("Cognee memory server initialized", self_improvement=False)
        initialized = True
        print("✓ Cognee ready", flush=True)
        print(f"  LLM: {os.environ.get('LLM_MODEL')}", flush=True)
        print(f"  Embeddings: {os.environ.get('EMBEDDING_MODEL')}", flush=True)

        if IMPROVE_SCHEDULER_ENABLED:
            asyncio.create_task(improve_scheduler())


def start_initialization():
    """Kick off initialization without blocking the caller (used by /health)."""
    global _init_task
    if initialized:
        return
    if _init_task is None or _init_task.done():
        _init_task = asyncio.create_task(initialize_cognee())


def _in_off_peak_window(now: datetime) -> bool:
    hour = now.hour
    if IMPROVE_OFF_PEAK_START <= IMPROVE_OFF_PEAK_END:
        return IMPROVE_OFF_PEAK_START <= hour < IMPROVE_OFF_PEAK_END
    # Window wraps past midnight (e.g. start=22, end=4)
    return hour >= IMPROVE_OFF_PEAK_START or hour < IMPROVE_OFF_PEAK_END


async def run_improve():
    """Run a controlled batch self-improvement (serialized with remembers)."""
    global _last_improve_at
    print("🧠 Running scheduled Cognee self-improvement (off-peak batch)...", flush=True)
    async with remember_lock:
        await cognee.improve(dataset="main_dataset")
    _last_improve_at = time.time()
    print("✓ Cognee self-improvement complete", flush=True)


async def improve_scheduler():
    """Background loop that runs improve() once per interval during off-peak hours."""
    while True:
        try:
            await asyncio.sleep(60)
            if not _in_off_peak_window(datetime.now()):
                continue
            if time.time() - _last_improve_at < IMPROVE_MIN_INTERVAL_HOURS * 3600:
                continue
            await run_improve()
        except Exception as exc:
            print(f"[ImproveScheduler] error: {exc}", flush=True)
            await asyncio.sleep(300)


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

        # Serialize remember operations so they don't pile up.
        # self_improvement=False: don't rebuild the graph after every message;
        # the graph is improved in a scheduled batch instead (see improve_scheduler).
        async with remember_lock:
            if session_id:
                await cognee.remember(formatted, session_id=session_id, self_improvement=False)
            await cognee.remember(formatted, self_improvement=False)

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


@app.route('/improve', methods=['POST'])
async def improve_endpoint():
    """Manually run a batch self-improvement (same job as the off-peak scheduler)."""
    try:
        await initialize_cognee()
        await run_improve()
        return jsonify({"status": "ok", "message": "Self-improvement complete"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/health', methods=['GET'])
async def health():
    """Fast health check; initialization runs in the background."""
    start_initialization()
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
        'auto_feedback': os.environ.get('AUTO_FEEDBACK', ''),
        'improve_scheduler_enabled': IMPROVE_SCHEDULER_ENABLED,
        'improve_off_peak_start': IMPROVE_OFF_PEAK_START,
        'improve_off_peak_end': IMPROVE_OFF_PEAK_END,
        'improve_min_interval_hours': IMPROVE_MIN_INTERVAL_HOURS,
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
        'AUTO_FEEDBACK': data.get('auto_feedback'),
        'IMPROVE_SCHEDULER_ENABLED': data.get('improve_scheduler_enabled'),
        'IMPROVE_OFF_PEAK_START': data.get('improve_off_peak_start'),
        'IMPROVE_OFF_PEAK_END': data.get('improve_off_peak_end'),
        'IMPROVE_MIN_INTERVAL_HOURS': data.get('improve_min_interval_hours'),
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
