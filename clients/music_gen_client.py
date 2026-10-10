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
import uuid
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
            workflow[self.text_node_id]["inputs"]["style"] = prompt

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
            filepath = self._download_output(prompt_id)

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

    def _download_output(self, prompt_id: str):
        """Find and download the generated audio file into output_folder."""
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

                    dest = os.path.join(self.output_folder, filename)
                    with open(dest, "wb") as f:
                        f.write(audio_data)
                    print(f"[MUSICGEN] Saved: {dest}")
                    return dest
        except Exception as e:
            print(f"[MUSICGEN] Failed to download output: {e}")
        return None
