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
import json
import glob
import re
import numpy as np
from PIL import Image
import cv2
from flask import Flask, jsonify, request
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
    """Loads all settings from config.py (single source of truth)."""
    global config
    # Import config.py from the project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)
    import config as cfg

    settings = {}
    settings['enable_local_vlm'] = False
    settings['camera_index'] = getattr(cfg, 'VISION_CAMERA_INDEX', 0)
    settings['image_source'] = getattr(cfg, 'VISION_IMAGE_SOURCE', 'cam').lower()
    settings['ndi_source_name'] = getattr(cfg, 'VISION_NDI_SOURCE_NAME', '')
    settings['frame_max_edge'] = int(getattr(cfg, 'VISION_FRAME_MAX_EDGE', 1280))
    settings['vision_trigger_words'] = getattr(cfg, 'VISION_TRIGGER_WORDS', [])
    settings['mcp_url'] = f"http://{getattr(cfg, 'SERVER_HOST', '127.0.0.1')}:{getattr(cfg, 'SERVER_PORT', 5000)}/"

    # Face recognition (OpenCV YuNet + SFace)
    settings['face_recognition_enabled'] = getattr(cfg, 'VISION_FACE_RECOGNITION_ENABLED', False)
    settings['face_scan_interval_s'] = float(getattr(cfg, 'VISION_FACE_SCAN_INTERVAL_S', 5.0))
    settings['face_match_threshold'] = float(getattr(cfg, 'VISION_FACE_MATCH_THRESHOLD', 0.363))
    settings['face_absence_reset_s'] = float(getattr(cfg, 'VISION_FACE_ABSENCE_RESET_S', 120.0))
    settings['face_report_unknown'] = getattr(cfg, 'VISION_FACE_REPORT_UNKNOWN', True)
    settings['face_ignore_names'] = [str(n).strip().lower() for n in getattr(cfg, 'VISION_FACE_IGNORE_NAMES', []) if str(n).strip()]
    settings['face_dir'] = getattr(cfg, 'VISION_FACE_DIR', 'models/faces')
    settings['face_event_url'] = f"http://{getattr(cfg, 'SERVER_HOST', '127.0.0.1')}:{getattr(cfg, 'SERVER_PORT', 5000)}/api/face_event"

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
        
        # Select source (exact match first, then substring, else first found)
        selected = None
        if source_name:
            source_lower = source_name.lower()
            for s in sources:
                if s.ndi_name.lower() == source_lower:
                    selected = s
                    break
            if selected is None:
                for s in sources:
                    if source_lower in s.ndi_name.lower():
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


class FaceRecognizer:
    """Detects and recognizes people in the current stream frame using OpenCV's
    YuNet detector + SFace recognizer (official opencv_zoo ONNX models).

    - Enrolled people live in <face_dir>/enrolled/ (one <name>.json holding ALL
      their sample embeddings + a <name>.jpg thumbnail each). Recognition scores a
      face against every sample of a person and uses the best match — so more
      samples (angles, lighting, looks) = better recognition.
    - Enroll from photos: drop them into <face_dir>/photos/ as <name>.jpg,
      <name>_2.jpg, <name>_3.jpg, ... — or put several images in a <name>/
      subfolder. All become samples of one person (picked up on startup or via
      POST /faces/refresh). Near-duplicate shots are skipped automatically.
    - Live enrollment (GUI "Enroll from Camera") appends a sample each time.
    - A background scan thread watches the stream, tracks who is currently
      visible, and pushes "appeared" events to the MCP server.
    """
    YUNET_FILE = 'face_detection_yunet_2023mar.onnx'
    SFACE_FILE = 'face_recognition_sface_2021dec.onnx'
    MAX_SAMPLES = 20  # per person; oldest samples are dropped above this

    def __init__(self, face_dir, camera_stream, match_threshold=0.363,
                 scan_interval_s=5.0, absence_reset_s=120.0, report_unknown=True,
                 event_url=None, ignore_names=None):
        self.face_dir = os.path.abspath(face_dir)
        self.enrolled_dir = os.path.join(self.face_dir, 'enrolled')
        self.photos_dir = os.path.join(self.face_dir, 'photos')
        os.makedirs(self.enrolled_dir, exist_ok=True)
        os.makedirs(self.photos_dir, exist_ok=True)

        self.camera_stream = camera_stream
        self.match_threshold = float(match_threshold)
        self.scan_interval_s = float(scan_interval_s)
        self.absence_reset_s = float(absence_reset_s)
        self.report_unknown = bool(report_unknown)
        self.event_url = event_url
        # Faces that are enrolled but should never count (channel avatar/logo,
        # Gem's own face on the canvas, ...): no events, no presence, no greetings
        self.ignore_names = {str(n).strip().lower() for n in (ignore_names or []) if str(n).strip()}

        yunet_path = os.path.join(self.face_dir, self.YUNET_FILE)
        sface_path = os.path.join(self.face_dir, self.SFACE_FILE)
        if not os.path.exists(yunet_path) or not os.path.exists(sface_path):
            raise IOError(
                f"Face models not found in '{self.face_dir}'. Download "
                f"{self.YUNET_FILE} and {self.SFACE_FILE} from the official "
                f"opencv_zoo repository (github.com/opencv/opencv_zoo)."
            )
        # score_threshold: YuNet detection confidence; 0.6 balances misses vs false positives
        self.detector = cv2.FaceDetectorYN.create(yunet_path, "", (320, 240), score_threshold=0.6)
        self.recognizer = cv2.FaceRecognizerSF.create(sface_path, "")

        self.enrolled = {}   # name -> list of np.ndarray (1,128) sample embeddings
        self.people = {}     # name -> {'last_seen', 'off_since', 'known', 'confidence'}
        self.grace_s = 10.0  # considered visible if seen within this window
        self.lock = threading.Lock()
        self.stopped = False
        self.thread = None

    # --- Enrollment ---------------------------------------------------------
    def load_enrolled(self):
        """Load all enrolled embeddings from enrolled/*.json. New format stores
        a list of sample embeddings per person ('embeddings'); the old
        single-'embedding' format is still accepted for backward compat."""
        with self.lock:
            self.enrolled.clear()
            for path in glob.glob(os.path.join(self.enrolled_dir, '*.json')):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    name = entry.get('name', os.path.basename(path)[:-5])
                    raw = entry.get('embeddings')
                    if raw is None and entry.get('embedding'):
                        raw = [entry['embedding']]  # old single-sample format
                    samples = []
                    for emb in raw or []:
                        arr = np.asarray(emb, dtype=np.float32)
                        if arr.size == 128:
                            samples.append(arr.reshape(1, 128))
                    if samples:
                        self.enrolled[name] = samples
                except Exception as e:
                    print(f"FACES WARN: could not load enrollment '{path}': {e}")

    def _person_name_from_photo(self, path):
        """Person name for a photo under photos/: the subfolder name if it lives
        in one (photos/jaygee/x.jpg -> 'jaygee'), else the filename stem with any
        trailing sample suffix stripped (jaygee_2.jpg -> 'jaygee')."""
        rel = os.path.relpath(path, self.photos_dir)
        parts = rel.split(os.sep)
        if len(parts) > 1:
            return parts[0].strip()
        stem = os.path.splitext(parts[0])[0]
        return re.sub(r'[_\-\s]\d+$', '', stem).strip() or stem

    def _photo_paths(self):
        """All enrollment photos: top-level images + one level of person subfolders."""
        exts = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        paths = []
        for entry in sorted(os.listdir(self.photos_dir)):
            full = os.path.join(self.photos_dir, entry)
            if os.path.isdir(full):
                for sub in sorted(os.listdir(full)):
                    if os.path.splitext(sub)[1].lower() in exts:
                        paths.append(os.path.join(full, sub))
            elif os.path.splitext(entry)[1].lower() in exts:
                paths.append(full)
        return paths

    def refresh_from_photos(self):
        """Detect + embed faces from photos/ and enroll them. Multiple photos of
        the same person are supported: name.jpg, name_2.jpg, ... or a name/
        subfolder — all become samples of one person. Photos with no face (or
        multiple faces) are skipped and reported. Re-running on the same folder
        is stable: near-duplicate samples are not added twice.
        Returns (enrolled_names, skipped_names)."""
        enrolled, skipped = [], []
        for path in self._photo_paths():
            name = self._person_name_from_photo(path)
            img_bgr = cv2.imread(path)
            if img_bgr is None:
                skipped.append(name)
                print(f"FACES WARN: could not read photo '{path}'")
                continue
            frame, faces = self._detect_faces(img_bgr)
            if len(faces) == 0:
                skipped.append(name)
                print(f"FACES WARN: no face found in photo '{path}' (skipped)")
                continue
            if len(faces) > 1:
                skipped.append(name)
                print(f"FACES WARN: {len(faces)} faces found in photo '{path}' — need exactly one (skipped)")
                continue
            if self._append_sample(name, frame, faces[0]):
                if name not in enrolled:
                    enrolled.append(name)
                print(f"FACES INFO: enrolled '{name}' from photo")
            else:
                print(f"FACES INFO: photo '{path}' is a near-duplicate of an existing '{name}' sample")
        self.load_enrolled()
        return enrolled, skipped

    def enroll_from_stream(self, name):
        """Capture the current frame and add it as a sample for that person.
        If several faces are visible (e.g. the avatar is on the stream too):
        already-enrolled faces are skipped, a face that already matches the
        enrollment name is preferred, and among remaining new faces the most
        confident detection wins (real faces out-score stylized/drawn ones)."""
        if not name or not name.strip():
            raise ValueError("No name provided")
        name = name.strip()
        frame_bgr = self._current_bgr()
        if frame_bgr is None:
            raise ValueError("No frame available from the vision source")
        frame, faces = self._detect_faces(frame_bgr)
        if len(faces) == 0:
            raise ValueError("No face detected in the current frame")

        target_face = None   # the face to enroll
        unknowns = []
        for face in faces:
            d = self._match_face(frame, face)
            if d['known'] and d['name'] == name:
                target_face = face  # the person being enrolled is visible — use them
            elif d['known']:
                print(f"FACES INFO: enrollment skipping already-enrolled face ({d['name']})")
            else:
                unknowns.append(face)

        if target_face is None and unknowns:
            if len(unknowns) > 1:
                # Most confident detection wins (real faces score higher than
                # drawn/stylized faces); ties broken by face size.
                target_face = max(unknowns,
                                  key=lambda f: (float(f[-1]), float(f[2]) * float(f[3])))
                print(f"FACES INFO: {len(unknowns)} new faces visible — enrolling the most prominent one")
            else:
                target_face = unknowns[0]

        if target_face is None:
            raise ValueError("Only already-enrolled faces are visible — show the new person and retry")

        self._append_sample(name, frame, target_face)
        self.load_enrolled()
        return name

    def _append_sample(self, name, frame, face_row):
        """Add one embedding sample for a person and persist json + thumbnail.
        Skips near-duplicates (> 0.95 cosine vs an existing sample) and caps
        stored samples at MAX_SAMPLES (oldest dropped). Returns True if added."""
        feat = self.recognizer.feature(self.recognizer.alignCrop(frame, face_row))
        with self.lock:
            samples = list(self.enrolled.get(name, []))
            for ref in samples:
                if float(self.recognizer.match(feat, ref, cv2.FaceRecognizerSF_FR_COSINE)) > 0.95:
                    return False
            if len(samples) >= self.MAX_SAMPLES:
                samples = samples[1:]
            samples.append(feat)
            self._write_enrollment(name, samples, frame, face_row)
            self.enrolled[name] = samples
        return True

    def _write_enrollment(self, name, samples, frame, face_row):
        """Persist a person's samples (json, 'embeddings' list) + thumbnail (jpg)."""
        entry = {
            'name': name,
            'embeddings': [s.reshape(-1).tolist() for s in samples],
            'samples': len(samples),
            'enrolled_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        with open(os.path.join(self.enrolled_dir, f"{name}.json"), 'w', encoding='utf-8') as f:
            json.dump(entry, f)
        # Thumbnail: the face box with generous margin so the WHOLE face
        # (chin, forehead, hair) is visible — not just the tight 112x112
        # alignment crop. Recognition still uses alignCrop internally.
        try:
            if face_row is not None and len(face_row) >= 4:
                x, y, w, h = (int(face_row[0]), int(face_row[1]),
                              int(face_row[2]), int(face_row[3]))
                mx = int(w * 0.35)   # side margin
                my = int(h * 0.55)   # extra vertical margin (forehead + chin)
                x0, y0 = max(0, x - mx), max(0, y - my)
                x1, y1 = min(frame.shape[1], x + w + mx), min(frame.shape[0], y + h + my)
                crop = frame[y0:y1, x0:x1]
                if crop.size:
                    cv2.imwrite(os.path.join(self.enrolled_dir, f"{name}.jpg"),
                                cv2.resize(crop, (200, 200), interpolation=cv2.INTER_CUBIC))
        except Exception:
            pass

    def delete_enrollment(self, name):
        """Remove an enrolled person (json + thumbnail)."""
        removed = False
        for ext in ('.json', '.jpg'):
            path = os.path.join(self.enrolled_dir, f"{name}{ext}")
            if os.path.exists(path):
                try:
                    os.remove(path)
                    removed = True
                except Exception as e:
                    print(f"FACES WARN: could not delete '{path}': {e}")
        with self.lock:
            self.enrolled.pop(name, None)
        return removed

    # --- Detection & recognition ---------------------------------------------
    def _current_bgr(self):
        """Latest frame from the vision source as an OpenCV BGR array (or None)."""
        pil = self.camera_stream.get_current_frame()
        if pil is None:
            return None
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    def _detect_faces(self, bgr):
        """Downscale large frames for speed, run YuNet.
        Returns (frame_used, faces) — face rows are aligned to frame_used, so
        pass frame_used (not the original) to alignCrop/feature."""
        h, w = bgr.shape[:2]
        scale = 960.0 / float(max(w, h))
        frame = cv2.resize(bgr, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr
        fh, fw = frame.shape[:2]
        self.detector.setInputSize((fw, fh))
        _, faces = self.detector.detect(frame)
        return frame, [] if faces is None else faces

    def _match_face(self, frame, face):
        """Match one detected face row against enrolled people's samples
        (best score across all of each person's samples wins).
        Returns {'name', 'known', 'confidence'} (unmatched -> 'unknown')."""
        feat = self.recognizer.feature(self.recognizer.alignCrop(frame, face))
        with self.lock:
            enrolled = dict(self.enrolled)
        best_name, best_score = None, 0.0
        for name, refs in enrolled.items():
            for ref in refs:
                score = float(self.recognizer.match(feat, ref, cv2.FaceRecognizerSF_FR_COSINE))
                if score > best_score:
                    best_name, best_score = name, score
        if best_name is not None and best_score >= self.match_threshold:
            return {'name': best_name, 'known': True, 'confidence': round(best_score, 3)}
        return {'name': 'unknown', 'known': False, 'confidence': round(best_score, 3)}

    def recognize(self, bgr):
        """Detect faces and match them against enrolled people's samples.
        Returns a list of {'name', 'known', 'confidence'} (unmatched -> 'unknown')."""
        frame, faces = self._detect_faces(bgr)
        return [self._match_face(frame, face) for face in faces]

    # --- Presence tracking + event push ---------------------------------------
    def scan_once(self):
        """One recognition pass; updates presence state and pushes appearance events."""
        bgr = self._current_bgr()
        if bgr is None:
            return
        detected = self.recognize(bgr)
        now = time.time()
        seen = set()
        with self.lock:
            for d in detected:
                if not d['known'] and not self.report_unknown:
                    continue
                name = d['name']
                if name.strip().lower() in self.ignore_names:
                    continue  # enrolled-but-ignored face (channel avatar/logo, Gem's own face)
                state = self.people.get(name)
                if state is None:
                    emit = True  # first time ever seen
                elif state.get('off_since') is not None and (now - state['off_since']) >= self.absence_reset_s:
                    emit = True  # back after a long absence
                else:
                    emit = False
                if emit:
                    self._emit_event('appeared', d)
                state = self.people.setdefault(name, {})
                state.update({'last_seen': now, 'off_since': None,
                              'known': d['known'], 'confidence': d['confidence']})
                seen.add(name)
            # Grace-expiry: anyone not seen this pass starts their off-screen clock
            for name, state in self.people.items():
                if name not in seen and state.get('off_since') is None:
                    state['off_since'] = now

    def current_people(self):
        """Who is visible right now (seen within the grace window)."""
        now = time.time()
        out = []
        with self.lock:
            for name, st in self.people.items():
                if st.get('last_seen') and (now - st['last_seen']) <= self.grace_s:
                    out.append({'name': name, 'known': st.get('known', True),
                                'confidence': st.get('confidence', 0.0)})
        return out

    def _emit_event(self, event, d):
        if not self.event_url:
            return
        payload = {'event': event, 'name': d['name'], 'known': d['known'],
                   'confidence': d.get('confidence', 0.0), 'source': 'vision'}
        try:
            requests.post(self.event_url, json=payload, timeout=2)
        except Exception as e:
            print(f"FACES INFO: could not push '{event}' event to MCP: {e}")

    def start(self):
        self.load_enrolled()
        print(f"FACES INFO: {len(self.enrolled)} enrolled face(s) loaded")
        enrolled, skipped = self.refresh_from_photos()
        if enrolled:
            print(f"FACES INFO: enrolled from photos: {', '.join(enrolled)}")
        if skipped:
            print(f"FACES INFO: skipped photos (no single face): {', '.join(skipped)}")
        self.thread = threading.Thread(target=self._scan_loop, args=())
        self.thread.daemon = True
        self.thread.start()
        print(f"FACES INFO: face recognition scan loop started (every {self.scan_interval_s}s)")

    def _scan_loop(self):
        while not self.stopped:
            try:
                self.scan_once()
            except Exception as e:
                print(f"FACES WARN: scan failed: {e}")
            time.sleep(self.scan_interval_s)

    def stop(self):
        self.stopped = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

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
        # Downscale (aspect ratio preserved) so encoding/transfer/inference stay
        # fast, but keep enough resolution for faces to carry detail for the LLM.
        # Longest edge = config 'frame_max_edge' (default 1280); never upscale.
        max_edge = int(config.get('frame_max_edge', 1280))
        w, h = current_frame.size
        scale = min(1.0, max_edge / float(max(w, h)))
        if scale < 1.0:
            resized_frame = current_frame.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS)
        else:
            resized_frame = current_frame

        base64_image = encode_image_to_base64(resized_frame)
        return jsonify({"image_base64": base64_image})
    else:
        return jsonify({"error": "Could not capture frame"}), 500


# --- FACE RECOGNITION API ---
face_recognizer = None

@vision_app.route('/faces/current', methods=['GET'])
def faces_current():
    """Who is visible on the stream right now (recognized people + unknowns)."""
    if face_recognizer is None:
        return jsonify({"error": "Face recognition is not enabled"}), 503
    return jsonify({"people": face_recognizer.current_people()})

@vision_app.route('/faces/scan', methods=['POST'])
def faces_scan():
    """One-shot recognition pass on the current frame (debug / GUI)."""
    if face_recognizer is None:
        return jsonify({"error": "Face recognition is not enabled"}), 503
    bgr = face_recognizer._current_bgr()
    if bgr is None:
        return jsonify({"error": "Could not capture frame"}), 500
    return jsonify({"faces": face_recognizer.recognize(bgr)})

@vision_app.route('/faces/list', methods=['GET'])
def faces_list():
    """List enrolled people."""
    if face_recognizer is None:
        return jsonify({"error": "Face recognition is not enabled"}), 503
    with face_recognizer.lock:
        names = sorted(face_recognizer.enrolled.keys())
    return jsonify({"people": names, "count": len(names)})

@vision_app.route('/faces/enroll', methods=['POST'])
def faces_enroll():
    """Enroll a person from the current frame: {'name': 'jaygee'}.
    Requires exactly one face on screen. Re-enrolling averages samples."""
    if face_recognizer is None:
        return jsonify({"error": "Face recognition is not enabled"}), 503
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"error": "No name provided"}), 400
    try:
        face_recognizer.enroll_from_stream(name)
        print(f"FACES INFO: enrolled '{name}' from live capture")
        return jsonify({"status": "ok", "name": name})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@vision_app.route('/faces/refresh', methods=['POST'])
def faces_refresh():
    """Re-scan the photos/ drop folder and enroll any new photos."""
    if face_recognizer is None:
        return jsonify({"error": "Face recognition is not enabled"}), 503
    enrolled, skipped = face_recognizer.refresh_from_photos()
    return jsonify({"status": "ok", "enrolled": enrolled, "skipped": skipped})

@vision_app.route('/faces/<name>', methods=['DELETE'])
def faces_delete(name):
    """Delete an enrolled person by name."""
    if face_recognizer is None:
        return jsonify({"error": "Face recognition is not enabled"}), 503
    removed = face_recognizer.delete_enrollment(name)
    return jsonify({"status": "ok" if removed else "not_found"})


@vision_app.route('/ndi/sources', methods=['GET'])
def ndi_sources():
    """List NDI sources currently visible on the network (for the GUI dropdown).
    If an NDIStream is already running, it owns the NDI runtime and we only
    borrow it; otherwise this endpoint initializes/destroys NDI itself."""
    if not NDI_AVAILABLE:
        return jsonify({"error": "NDIlib not installed. Run: pip install ndi-python"}), 503

    owns_runtime = not isinstance(camera_stream, NDIStream)
    if owns_runtime:
        if not ndi.initialize():
            return jsonify({"error": "Cannot initialize NDI runtime"}), 500
    finder = None
    try:
        finder = ndi.find_create_v2()
        if finder is None:
            return jsonify({"error": "Cannot create NDI finder"}), 500
        # Give sources a moment to announce themselves on the network
        ndi.find_wait_for_sources(finder, 2000)
        sources = ndi.find_get_current_sources(finder)
        names = [s.ndi_name for s in sources]
        return jsonify({"sources": names, "count": len(names)})
    except Exception as e:
        return jsonify({"error": f"NDI scan failed: {e}"}), 500
    finally:
        if finder is not None:
            ndi.find_destroy(finder)
        if owns_runtime:
            ndi.destroy()

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
        print("VISION INFO: Camera Service mode — frames are served to main.py,")
        print("             where Gem 'sees' them via the multimodal Ollama model.")
        print("             (Legacy local SmolVLM scene descriptions are NOT loaded, saving GPU/memory.")
        print("             Face recognition is separate and still runs when enabled.)")

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

    # Face recognition (OpenCV YuNet + SFace) on the vision source
    if config.get('face_recognition_enabled', False):
        try:
            face_recognizer = FaceRecognizer(
                face_dir=config.get('face_dir', 'models/faces'),
                camera_stream=camera_stream,
                match_threshold=config.get('face_match_threshold', 0.363),
                scan_interval_s=config.get('face_scan_interval_s', 5.0),
                absence_reset_s=config.get('face_absence_reset_s', 120.0),
                report_unknown=config.get('face_report_unknown', True),
                event_url=config.get('face_event_url'),
                ignore_names=config.get('face_ignore_names', []),
            )
            face_recognizer.start()
        except IOError as e:
            print(f"FACES WARN: face recognition disabled: {e}")
            face_recognizer = None

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
    if face_recognizer is not None:
        face_recognizer.stop()
    print("VISION INFO: Script has shut down.")
    os._exit(0)
# ------------------------------------------------------------------------------