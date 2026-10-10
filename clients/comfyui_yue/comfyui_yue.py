import json
import uuid
import requests
import websocket

COMFYUI_URL = "127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())
WORKFLOW_FILE = "yue2_full.json"
TEXT_NODE_ID = "22"  # Replace with your text node ID


def generate_music(prompt_text):
    # 1. Connect WebSocket
    ws = websocket.WebSocket()
    ws.connect(f"ws://{COMFYUI_URL}/ws?clientId={CLIENT_ID}")

    # 2. Load and edit prompt
    with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
        prompt_data = json.load(f)
    prompt_data[TEXT_NODE_ID]["inputs"]["style"] = prompt_text
    print("Text being sent:", prompt_data[TEXT_NODE_ID]["inputs"])
    # 3. Queue prompt
    payload = {"prompt": prompt_data, "client_id": CLIENT_ID}
    response = requests.post(f"http://{COMFYUI_URL}/prompt", json=payload)
    prompt_id = response.json()["prompt_id"]
    print(f"Generating music... (Prompt ID: {prompt_id})")

    # 4. Wait for it to finish
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message["type"] == "executing":
                data = message["data"]
                if data["node"] is None and data["prompt_id"] == prompt_id:
                    print("Generation complete!")
                    break

    # 5. Get file info from history
    history_res = requests.get(f"http://{COMFYUI_URL}/history/{prompt_id}")
    history = history_res.json()[prompt_id]

    # 6. Find and download the audio file
    for node_id, node_output in history.get("outputs", {}).items():
        # Check both "audio" and "images" (some audio nodes use the image key)
        file_list = node_output.get("audio", []) or node_output.get(
            "images", []
        )

        for file_info in file_list:
            filename = file_info["filename"]
            subfolder = file_info.get("subfolder", "")
            file_type = file_info.get("type", "output")

            # Check if it's an audio format
            if filename.endswith((".wav", ".mp3", ".flac", ".ogg")):
                # Download using the /view API endpoint
                url = f"http://{COMFYUI_URL}/view?filename={filename}&subfolder={subfolder}&type={file_type}"
                audio_data = requests.get(url).content

                # Save it to your local script directory
                with open(filename, "wb") as f:
                    f.write(audio_data)
                print(f"Audio downloaded successfully: {filename}")


# Run
generate_music("heavy metal guitar riff, 140 bpm, aggressive drums")