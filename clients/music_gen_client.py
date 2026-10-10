"""
Music Generation Client
Wraps a ComfyUI + YuE2 workflow to generate music from a style prompt.

The heavy work (WebSocket + HTTP polling + download) is fully blocking, so it
runs in a background thread, mirroring how download_song() works in the music
client. On completion it saves the audio to music/generated/ and fires a
callback so main.py can record it to memory.
"""

import os
import json
import re
import uuid
import random
import subprocess
import threading
import requests
import websocket
from typing import Optional, Callable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MusicGenClient:
    def __init__(self, comfyui_url: str = "127.0.0.1:8188",
                 workflow_file: str = "",
                 text_node_id: str = "22",
                 output_folder: str = ""):
        self.comfyui_url = comfyui_url.rstrip("/")
        self.workflow_file = workflow_file
        self.text_node_id = text_node_id

        if output_folder:
            self.output_folder = output_folder
        else:
            self.output_folder = os.path.join(PROJECT_ROOT, "music", "generated")
        os.makedirs(self.output_folder, exist_ok=True)

        self.current_generation = None
        self.on_complete: Optional[Callable] = None  # callback(prompt, filepath)

    def check_connection(self) -> bool:
        """Probe that ComfyUI is reachable."""
        try:
            resp = requests.get(f"http://{self.comfyui_url}/system_stats", timeout=3)
            if resp.status_code == 200:
                print(f"[OK] ComfyUI connected: {self.comfyui_url}")
                return True
        except Exception as e:
            print(f"[X] ComfyUI not available: {e}")
        return False

    def generate(self, prompt: str) -> bool:
        """Start music generation in a background thread. Returns False if one
        is already in progress."""
        if self.current_generation:
            print(f"[MUSICGEN] Generation already in progress: {self.current_generation}")
            return False

        self.current_generation = prompt
        thread = threading.Thread(target=self._generate_worker, args=(prompt,), daemon=True)
        thread.start()
        return True

    def _generate_worker(self, prompt: str):
        """Run the full ComfyUI workflow (blocking) in a background thread."""
        client_id = str(uuid.uuid4())
        try:
            print(f"[MUSICGEN] Generating: '{prompt}'")

            # 1. Connect WebSocket
            ws = websocket.WebSocket()
            ws.connect(f"ws://{self.comfyui_url}/ws?clientId={client_id}")

            # 2. Load and edit the workflow
            with open(self.workflow_file, "r", encoding="utf-8") as f:
                workflow = json.load(f)

            # Inject the style prompt into every node that has a "style" input.
            # In the YuE2 workflow the prompt drives both the ABC node (musical
            # structure) and the music node (audio render), so all must match.
            for node_id, node in workflow.items():
                if isinstance(node, dict) and "inputs" in node:
                    if "style" in node["inputs"]:
                        node["inputs"]["style"] = prompt
                    # Randomize every seed so each generation actually differs.
                    # The workflow otherwise hardcodes a fixed seed, making all
                    # songs sound nearly identical regardless of the prompt.
                    if "seed" in node["inputs"]:
                        node["inputs"]["seed"] = random.randint(0, 2**31 - 1)

            # 3. Queue the prompt
            payload = {"prompt": workflow, "client_id": client_id}
            response = requests.post(f"http://{self.comfyui_url}/prompt", json=payload)
            prompt_id = response.json()["prompt_id"]
            print(f"[MUSICGEN] Queued (prompt id: {prompt_id})")

            # 4. Wait for completion
            while True:
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    if message.get("type") == "executing":
                        data = message.get("data", {})
                        if data.get("node") is None and data.get("prompt_id") == prompt_id:
                            break
            ws.close()
            print("[MUSICGEN] Generation complete")

            # 5. Download the audio output
            filepath = self._download_output(prompt_id, prompt)

            # 6. Notify via callback
            if filepath and self.on_complete:
                try:
                    self.on_complete(prompt, filepath)
                except Exception as e:
                    print(f"[MUSICGEN] on_complete callback failed: {e}")
        except Exception as e:
            print(f"[MUSICGEN] Generation failed: {e}")
        finally:
            self.current_generation = None

    def _download_output(self, prompt_id: str, prompt: str = ""):
        """Find and download the generated audio, convert to MP3, and save it."""
        try:
            history_res = requests.get(f"http://{self.comfyui_url}/history/{prompt_id}")
            history = history_res.json()[prompt_id]

            for node_id, node_output in history.get("outputs", {}).items():
                file_list = node_output.get("audio", []) or node_output.get("images", [])
                for file_info in file_list:
                    filename = file_info["filename"]
                    if not filename.endswith((".wav", ".mp3", ".flac", ".ogg")):
                        continue
                    subfolder = file_info.get("subfolder", "")
                    file_type = file_info.get("type", "output")
                    url = (f"http://{self.comfyui_url}/view?filename={filename}"
                           f"&subfolder={subfolder}&type={file_type}")
                    audio_data = requests.get(url).content

                    # Save the raw audio, then convert to MP3 so generated songs
                    # match the rest of the music pipeline (which is all .mp3).
                    raw_path = os.path.join(self.output_folder, filename)
                    with open(raw_path, "wb") as f:
                        f.write(audio_data)

                    dest = self._convert_to_mp3(raw_path, prompt)
                    return dest
        except Exception as e:
            print(f"[MUSICGEN] Failed to download output: {e}")
        return None

    def _convert_to_mp3(self, raw_path: str, prompt: str) -> str:
        """Ensure the generated audio is a prompt-named MP3. If it's already MP3
        (the workflow now outputs MP3 directly), just rename it; otherwise convert
        via ffmpeg."""
        stem = os.path.splitext(os.path.basename(raw_path))[0]
        if prompt:
            safe = "".join(c for c in prompt if c.isalnum() or c in " -_").strip()
            safe = re.sub(r"[_\s]+", "_", safe)[:60] or stem
        else:
            safe = stem

        mp3_path = os.path.join(self.output_folder, f"{safe}.mp3")

        # Already MP3 -> just rename, no re-encode.
        if raw_path.lower().endswith(".mp3"):
            if os.path.abspath(raw_path) != os.path.abspath(mp3_path):
                try:
                    os.rename(raw_path, mp3_path)
                except Exception:
                    import shutil
                    shutil.move(raw_path, mp3_path)
            print(f"[MUSICGEN] Saved MP3: {mp3_path}")
            return mp3_path

        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path, "-vn", "-codec:a", "libmp3lame",
                 "-q:a", "2", mp3_path],
                check=True, capture_output=True,
            )
            print(f"[MUSICGEN] Saved MP3: {mp3_path}")
            # Remove the raw file now that the MP3 exists
            try:
                os.remove(raw_path)
            except Exception:
                pass
            return mp3_path
        except Exception as e:
            print(f"[MUSICGEN] ffmpeg conversion failed: {e}")
            return raw_path
