# ===========================================================================
#              DUAL-MODE Vision Service & Client for MCP
# ===========================================================================
# This script can operate in two modes based on the 'enable_local_vlm' setting:
#
# 1. VLM Mode (enable_local_vlm = true):
#    - Loads a local VLM (e.g., SmolVLM) to generate text descriptions of scenes.
#    - Provides the `/scan` endpoint for the pipelined MCP modes.
#
# 2. Camera Service Mode (enable_local_vlm = false):
#    - Does NOT load the VLM, saving significant memory/GPU resources.
#    - Provides the `/get_image` endpoint, which returns a RESIZED and
#      Base64-encoded image for the unified multimodal MCP mode.
# ===========================================================================

import requests
import configparser
import sys
import os
import threading
import time
from PIL import Image
import cv2
from flask import Flask, jsonify
import base64
import io

# VLM imports are optional (only needed when enable_local_vlm = true)
try:
    import torch
    from transformers import AutoModelForVision2Seq, AutoProcessor
    VLM_AVAILABLE = True
except ImportError:
    VLM_AVAILABLE = False
    torch = None
    AutoModelForVision2Seq = None
    AutoProcessor = None

# NDI import is optional (only needed when image_source = ndi)
try:
    import NDIlib as ndi
    NDI_AVAILABLE = True
except ImportError:
    NDI_AVAILABLE = False
    ndi = None

# --- 1. CONFIGURATION & GLOBAL VARIABLES ---
# ------------------------------------------------------------------------------
config = {}
# SMOL_VLM_MODEL_ID has been removed from here and will be loaded from config.
if VLM_AVAILABLE:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.bfloat16 if device == "cuda" else torch.float32
else:
    device = "cpu"
    torch_dtype = None

# VLM components are now optional and loaded conditionally
processor = None
smol_vlm_model = None

camera_stream = None
vision_app = Flask("VisionService")
# ------------------------------------------------------------------------------


# --- 2. CORE FUNCTIONS ---
# ------------------------------------------------------------------------------
def load_config():
    """Loads all settings from mcp_settings.ini."""
    global config
    parser = configparser.ConfigParser()
    # Use absolute path relative to this script's location
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_settings.ini')
    if not os.path.exists(config_file):
        sys.exit(f"FATAL: Config '{config_file}' not found.")
    
    parser.read(config_file)
    settings = {}
    try:
        # --- Read from [VisionService] section ---
        settings['enable_local_vlm'] = parser.getboolean('VisionService', 'enable_local_vlm', fallback=False)
        settings['camera_index'] = parser.getint('VisionService', 'camera_index', fallback=0)
        settings['image_source'] = parser.get('VisionService', 'image_source', fallback='cam').lower()
        settings['ndi_source_name'] = parser.get('VisionService', 'ndi_source_name', fallback='')
        raw_triggers = parser.get('VisionService', 'vision_trigger_words', fallback='')
        settings['vision_trigger_words'] = [word.strip().lower() for word in raw_triggers.split(',') if word.strip()]
        
        # Load the VLM Model ID only if local VLM is enabled
        if settings['enable_local_vlm']:
            settings['smol_vlm_model_id'] = parser.get('VisionService', 'smol_vlm_model_id')

        # --- Read from [MCP] section and build the URL ---
        mcp_host = parser.get('MCP', 'host')
        mcp_port = parser.get('MCP', 'port')
        settings['mcp_url'] = f"http://{mcp_host}:{mcp_port}/"
        
    except (configparser.NoSectionError, configparser.NoOptionError, Exception) as e:
        sys.exit(f"FATAL: Setting missing or invalid in '{config_file}'. Please check your sections and keys. Details: {e}")
    
    config = settings

def initialize_models():
    """Loads the VLM. This function is only called if enable_local_vlm is true."""
    global processor, smol_vlm_model
    
    if not VLM_AVAILABLE:
        sys.exit("FATAL: transformers/torch not installed. Cannot load local VLM. Set enable_local_vlm = false to run in camera-only mode.")
    
    # Get model ID from the config dictionary
    model_id = config.get('smol_vlm_model_id')
    if not model_id:
        sys.exit("FATAL: 'smol_vlm_model_id' is not defined in mcp_settings.ini under [VisionService].")

    print(f"VISION INFO: Loading VLM: {model_id} on '{device}'. (This may take a moment)...")
    try:
        # Use the 'model_id' variable loaded from the config
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        smol_vlm_model = AutoModelForVision2Seq.from_pretrained(model_id, torch_dtype=torch_dtype, trust_remote_code=True, low_cpu_mem_usage=True).to(device)
        print("VISION INFO: VLM loaded successfully.")
    except Exception as e: sys.exit(f"FATAL: Could not load VLM. Details: {e}")

class CameraStream:
    """A dedicated thread to continuously read frames from the camera to prevent stale frames."""
    def __init__(self, camera_index=0, image_source='cam'):
        # Match old working implementation: plain VideoCapture (no backend)
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            raise IOError(f"Cannot open camera at index {camera_index} (source: {image_source})")
        self.frame = None
        self.lock = threading.Lock()
        self.stopped = False
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

    def update(self):
        while not self.stopped:
            ret, frame = self.cap.read()
            if ret:
                with self.lock: self.frame = frame

    def get_current_frame(self) -> Image.Image:
        with self.lock:
            if self.frame is None: return None
            return Image.fromarray(cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB))

    def release(self):
        self.stopped = True
        if self.thread.is_alive(): self.thread.join()
        self.cap.release()


class NDIStream:
    """Receives frames directly from an NDI source (no virtual camera needed)."""
    def __init__(self, source_name=None):
        if not NDI_AVAILABLE:
            raise IOError("NDIlib not installed. Run: pip install ndi-python")
        
        if not ndi.initialize():
            raise IOError("Cannot initialize NDI runtime")
        
        self.ndi_find = ndi.find_create_v2()
        if self.ndi_find is None:
            raise IOError("Cannot create NDI finder")
        
        # Wait for sources to appear
        sources = []
        for _ in range(10):
            ndi.find_wait_for_sources(self.ndi_find, 1000)
            sources = ndi.find_get_current_sources(self.ndi_find)
            if sources:
                break
        
        if not sources:
            raise IOError("No NDI sources found on the network")
        
        # Select source (by name if provided, else first)
        selected = None
        if source_name:
            for s in sources:
                if source_name.lower() in s.ndi_name.lower():
                    selected = s
                    break
        if selected is None:
            selected = sources[0]
        
        print(f"NDI INFO: Connecting to source '{selected.ndi_name}'")
        
        # Create receiver settings and receiver
        recv_settings = ndi.RecvCreateV3()
        recv_settings.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
        recv_settings.source_to_connect_to = selected
        self.ndi_recv = ndi.recv_create_v3(recv_settings)
        
        self.frame = None
        self.lock = threading.Lock()
        self.stopped = False
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()
    
    def update(self):
        while not self.stopped:
            t, v, a, _ = ndi.recv_capture_v2(self.ndi_recv, 1000)
            if t == ndi.FRAME_TYPE_VIDEO:
                # Convert BGRX to BGR
                frame = cv2.cvtColor(v.data, cv2.COLOR_BGRA2BGR)
                with self.lock:
                    self.frame = frame
                ndi.recv_free_video_v2(self.ndi_recv, v)
            elif t == ndi.FRAME_TYPE_NONE:
                time.sleep(0.01)
    
    def get_current_frame(self) -> Image.Image:
        with self.lock:
            if self.frame is None:
                return None
            return Image.fromarray(cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB))
    
    def release(self):
        self.stopped = True
        if self.thread.is_alive():
            self.thread.join()
        ndi.recv_destroy(self.ndi_recv)
        ndi.find_destroy(self.ndi_find)
        ndi.destroy()

def encode_image_to_base64(image: Image.Image) -> str:
    """Encodes a PIL Image into a Base64 string for JSON transport."""
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def ask_smol_vlm(image: Image.Image, prompt_text: str) -> str:
    """Runs inference on the local SmolVLM model."""
    if not all([processor, smol_vlm_model]): return "Error: Local VLM not initialized."
    if image is None: return "Error: No image provided."
    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt_text}]}]
    prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
    inputs = processor(text=prompt, images=[image], return_tensors="pt").to(device, torch_dtype)
    try:
        output = smol_vlm_model.generate(**inputs, max_new_tokens=200, do_sample=False)
        generated_text = processor.batch_decode(output, skip_special_tokens=True)[0]
        separator = "Assistant:"
        if separator in generated_text:
            return generated_text.split(separator)[-1].strip()
        return generated_text.strip()
    except Exception as e: return f"Error: VLM inference failed. Details: {e}"

def send_to_mcp(user_text: str, vision_description: str) -> str:
    """Sends a request to the MCP's legacy /vision endpoint."""
    payload = {"source": "vision", "text": user_text, "vision_context": vision_description}
    try:
        response = requests.post(config['mcp_url'], json=payload)
        response.raise_for_status()
        return response.json().get('response', 'Error: Invalid response from MCP.')
    except requests.exceptions.RequestException as e: return f"MCP CONNECTION ERROR: {e}"
# ------------------------------------------------------------------------------


# --- 3. VISION SERVICE API ---
# ------------------------------------------------------------------------------
@vision_app.route('/scan', methods=['GET'])
def trigger_scan():
    """[LEGACY] Endpoint for pipelined mode. Returns a text description of the scene."""
    if not config.get('enable_local_vlm', False):
        return jsonify({"error": "Local VLM is not enabled in mcp_settings.ini"}), 503
    
    global camera_stream
    if camera_stream is None: return jsonify({"error": "Camera stream not initialized"}), 500
    current_frame = camera_stream.get_current_frame()
    if current_frame:
        prompt = "Describe the main subject of the image in one short sentence."
        description = ask_smol_vlm(current_frame, prompt)
        return jsonify({"vision_context": description})
    else:
        return jsonify({"error": "Could not capture frame"}), 500

@vision_app.route('/get_image', methods=['GET'])
def get_image():
    """Endpoint for unified multimodal mode. Returns a RESIZED, Base64-encoded image."""
    global camera_stream
    if camera_stream is None: return jsonify({"error": "Camera stream not initialized"}), 500
    
    current_frame = camera_stream.get_current_frame()
    
    if current_frame:
        # --- [OPTIMIZATION] ---
        # Resize the image to a much smaller resolution before encoding.
        # This significantly speeds up encoding, network transfer, and model inference.
        resized_frame = current_frame.resize((640, 480), Image.Resampling.LANCZOS)
        # --- [END OPTIMIZATION] ---
        
        base64_image = encode_image_to_base64(resized_frame)
        return jsonify({"image_base64": base64_image})
    else:
        return jsonify({"error": "Could not capture frame"}), 500

def run_vision_server():
    host = "127.0.0.1"; port = 5001
    print(f"--- Vision Service API listening on http://{host}:{port} ---")
    vision_app.run(host=host, port=port, debug=False)
# ------------------------------------------------------------------------------


# --- 4. USER INPUT LOOP (LEGACY) ---
# ------------------------------------------------------------------------------
def user_input_loop():
    """Handles interactive commands. Only fully functional if local VLM is enabled."""
    if not config.get('enable_local_vlm', False):
        print("\n--- Interactive Client Disabled ---")
        print("Set 'enable_local_vlm = true' in mcp_settings.ini to use this feature.")
        return

    global camera_stream
    print("\n--- Vision Client is Running (Pipelined Mode) ---")
    print("Type 'quit' or press Ctrl+C to exit.\n")
    while True:
        try:
            user_input = input("Enter command > ").strip()
            if not user_input: continue
            if user_input.lower() == "quit": break
            
            print("\n>>> Analyzing New Frame <<<")
            current_frame = camera_stream.get_current_frame()
            if current_frame:
                prompt = "Describe the main subject of the image in one short sentence."
                description = ask_smol_vlm(current_frame, prompt)
                print(f"Smol-VLM Context Being Sent: '{description}'")
                final_response = send_to_mcp(user_input, description)
                print(f"\n>>> MCP Response: {final_response}\n")
            else:
                print("Error: Could not capture a frame from the camera.")

        except KeyboardInterrupt: break
        except Exception as e:
            print(f"\nAn error occurred in the input loop: {e}")
            break
# ------------------------------------------------------------------------------


# --- 5. MAIN EXECUTION BLOCK ---
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    load_config()

    if config['enable_local_vlm']:
        initialize_models()
    else:
        print("VISION INFO: Local VLM is disabled. Running in Camera Service mode.")

    image_source = config.get('image_source', 'cam')
    try:
        if image_source == 'ndi':
            camera_stream = NDIStream(source_name=config.get('ndi_source_name'))
            print(f"VISION INFO: NDI stream started.")
        else:
            camera_stream = CameraStream(camera_index=config['camera_index'], image_source=image_source)
            print(f"VISION INFO: Camera stream started on index {config['camera_index']} (source: {image_source}).")
    except IOError as e:
        sys.exit(f"VISION FATAL ERROR: {e}. Exiting.")

    time.sleep(2) # Give camera time to initialize

    server_thread = threading.Thread(target=run_vision_server, daemon=True)
    server_thread.start()

    if config.get('enable_local_vlm', False):
        user_input_loop()
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nVISION INFO: Ctrl+C detected. Shutting down...")
    
    if camera_stream:
        camera_stream.release()
    print("VISION INFO: Script has shut down.")
    os._exit(0)
# ------------------------------------------------------------------------------