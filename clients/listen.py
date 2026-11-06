# ==============================================================================
#                      Audio Client for MCP
# ==============================================================================
# This script acts as the "ears" of the system. Its sole purpose is to listen
# via the microphone, have the shared Whisper server transcribe speech, and
# send the resulting text to the MCP for filtering and reasoning.
#
# Whisper is NOT loaded here: clients/whisper_server.py owns the one model and
# both this listener and the m8 companion use it. The server routes transcripts
# using config.py's MIC_ROUTE, so while m8 is playing this listener receives
# empty text instead of Gem hearing the same words.
# ==============================================================================

import collections
import queue
import sys
import wave
import os
import requests
import configparser

import numpy as np
import sounddevice as sd
import webrtcvad

# --- Configuration (defaults; overridden from config.py at runtime) ---
VAD_AGGRESSIVENESS = 1
SAMPLE_RATE = 16000
FRAME_DURATION_MS = 20
FRAMES_PER_BUFFER = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
SILENCE_THRESHOLD_S = 2.0
PRE_BUFFER_S = 0.5
MAX_RECORD_S = 120.0  # Max recording duration; force-process even if no silence
MIN_DB = -40.0   # Energy gate threshold (dB); audio below this is treated as silence
WAV_FILE_NAME = "temp_audio_chunk.wav"

# --- Global State ---
audio_queue = queue.Queue()
is_recording = False
pre_buffer_frames = collections.deque(maxlen=int(PRE_BUFFER_S * SAMPLE_RATE / FRAMES_PER_BUFFER))
recorded_frames = []
silent_frames_count = 0

# --- CORE FUNCTIONS ---

def load_settings_from_ini():
    """
    Loads MCP URL and the selected audio device ID from config.py (single source of truth).
    """
    # Import config.py from the project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    import config as cfg

    global VAD_AGGRESSIVENESS, SILENCE_THRESHOLD_S, PRE_BUFFER_S, MAX_RECORD_S, MIN_DB

    settings = {}
    
    try:
        # Get the MCP URL from config.py
        host = getattr(cfg, 'SERVER_HOST', '127.0.0.1')
        port = getattr(cfg, 'SERVER_PORT', 5000)
        settings['mcp_url'] = f"http://{host}:{port}/process"
        settings['activity_url'] = f"http://{host}:{port}/api/voice_activity"
        print(f"AUDIO INFO: MCP URL set to -> {settings['mcp_url']}")

        # Load STT tuning values from config.py
        settings['stt_url'] = getattr(cfg, 'STT_SERVER_URL', 'http://127.0.0.1:13310').rstrip('/')
        print(f"AUDIO INFO: Whisper server -> {settings['stt_url']}")
        VAD_AGGRESSIVENESS = int(getattr(cfg, 'STT_VAD_AGGRESSIVENESS', 1))
        SILENCE_THRESHOLD_S = float(getattr(cfg, 'STT_SILENCE_THRESHOLD_S', 2.0))
        PRE_BUFFER_S = float(getattr(cfg, 'STT_PRE_BUFFER_S', 0.5))
        MAX_RECORD_S = float(getattr(cfg, 'STT_MAX_RECORD_S', 120.0))
        MIN_DB = float(getattr(cfg, 'STT_MIN_DB', -40.0))

        # Get the audio input device string from config.py
        device_string = getattr(cfg, 'AUDIO_INPUT_DEVICE', '')
        if not device_string or device_string.lower() == 'none':
            raise ValueError("No input device is selected. Please run the main MCP GUI to select one.")
        
        print(f"AUDIO INFO: Found saved input device -> '{device_string}'")

        # --- Device Validation (name-verified) ---
        # Windows shifts audio device indices between boots, so the stored ID is
        # only trusted when the name at that index still matches — otherwise the
        # device is found by name.
        from device_utils import resolve_device, device_to_option
        dev = resolve_device(device_string, want_input=True)
        if dev is None:
            raise ValueError(f"Saved input device ('{device_string}') is not available on this system.")
        settings['device_id'] = dev['index']

        print(f"AUDIO INFO: Using input device -> '{device_to_option(dev)}' (id {dev['index']})")

    except ValueError as e:
        sys.exit(f"FATAL ERROR: Problem with the audio device setting. Details: {e}")
        
    return settings

def send_to_mcp(transcribed_text: str, mcp_url: str):
    """Packages the transcribed text and sends it to the MCP."""
    print(f"AUDIO INFO: Sending to MCP -> '{transcribed_text}'")
    payload = {
        "source": "microphone",
        "text": transcribed_text,
        "vision_context": "" # Audio client has no vision context
    }
    try:
        response = requests.post(mcp_url, json=payload, timeout=60)
        response.raise_for_status()
        print("AUDIO INFO: MCP received the task.")
    except requests.exceptions.RequestException as e:
        print(f"MCP CONNECTION ERROR: Could not connect. Is MCP running? Details: {e}")


def notify_voice_activity(activity_url: str):
    """Ping the MCP so the idle monologue timer resets (speech detected)."""
    try:
        requests.post(activity_url, json={}, timeout=2)
    except requests.exceptions.RequestException:
        pass  # best-effort; ignore if MCP is briefly unreachable

def audio_callback(indata, frames, time, status):
    if status: print(f"Audio callback status: {status}", file=sys.stderr)
    audio_queue.put(bytes(indata))

def main():
    global is_recording, recorded_frames, silent_frames_count

    # Load all settings from the central INI file
    settings = load_settings_from_ini()
    mcp_url = settings['mcp_url']
    activity_url = settings['activity_url']
    selected_device = settings['device_id']

    stt_url = settings['stt_url']
    print("\nInitializing services...")
    try:
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS); print("- VAD initialized.")
        print(f"- Using the shared Whisper server at {stt_url} (no local model).")
    except Exception as e:
        sys.exit(f"An error occurred during initialization: {e}")

    max_silent_frames = int(SILENCE_THRESHOLD_S * SAMPLE_RATE / FRAMES_PER_BUFFER)
    max_record_frames = int(MAX_RECORD_S * SAMPLE_RATE / FRAMES_PER_BUFFER)

    # Smoothing state so the gate matches the VU meter (which uses 0.85 smoothing).
    _smoothed_db = -100.0
    SMOOTHING = 0.85

    def frame_is_speech(frame: bytes) -> bool:
        """A frame counts as speech if it passes BOTH the energy gate (MIN_DB)
        and the WebRTC VAD classifier. Uses the same smoothing as the VU meter
        so the threshold visually matches what you see."""
        nonlocal _smoothed_db
        arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        rms = np.sqrt(np.mean(arr ** 2))
        db = 20 * np.log10(rms) if rms > 0 else -100.0
        _smoothed_db = (SMOOTHING * _smoothed_db) + ((1 - SMOOTHING) * db)
        if _smoothed_db < MIN_DB:
            return False
        return vad.is_speech(frame, SAMPLE_RATE)
    
    # Get the device name for a user-friendly startup message
    device_name = sd.query_devices(selected_device)['name']
    print(f"\n--- Audio Client Listening on '{device_name}' ---")

    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=FRAMES_PER_BUFFER, device=selected_device, dtype="int16", channels=1, callback=audio_callback):
            def process_and_reset(reason: str):
                """Transcribe the recorded frames and reset for the next utterance."""
                global is_recording
                print(f"{reason}, processing...")
                all_frames = list(pre_buffer_frames) + recorded_frames
                with wave.open(WAV_FILE_NAME, 'wb') as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SAMPLE_RATE); wf.writeframes(b''.join(all_frames))

                try:
                    with open(WAV_FILE_NAME, 'rb') as fh:
                        wav_bytes = fh.read()
                    response = requests.post(
                        f"{stt_url}/v1/audio/transcriptions",
                        headers={'X-Mic-Client': 'gem'},
                        files={'file': ('speech.wav', wav_bytes, 'audio/wav')},
                        data={'model': 'gem'},
                        timeout=60,
                    )
                    response.raise_for_status()
                    body = response.json()
                    transcribed_text = str(body.get('text') or '').strip()
                    if body.get('skipped'):
                        # Mic is routed to m8: stay quiet, keep listening.
                        print("Transcription skipped (mic routed to m8)")
                except requests.exceptions.RequestException as e:
                    print(f"STT server error: {e}")
                    transcribed_text = ""
                except Exception as e:
                    print(f"Whisper transcription error: {e}")
                    transcribed_text = ""

                if transcribed_text:
                    print(f"Transcribed: '{transcribed_text}'")
                    send_to_mcp(transcribed_text, mcp_url)

                # Reset for next utterance
                is_recording = False
                recorded_frames.clear()
                pre_buffer_frames.clear()
                silent_frames_count = 0
                print(f"\n--- Audio Client Listening on '{device_name}' ---")

            while True:
                frame = audio_queue.get()
                is_speech = frame_is_speech(frame)

                if is_recording:
                    recorded_frames.append(frame)
                    # Force-process if someone talks non-stop for too long,
                    # otherwise the recording never resets and grows unbounded.
                    if len(recorded_frames) >= max_record_frames:
                        process_and_reset("Max recording duration reached")
                    elif not is_speech and len(recorded_frames) > 10: # Check for silence after some speech
                        silent_frames_count += 1
                        if silent_frames_count > max_silent_frames:
                            process_and_reset("Silence detected")
                    else:
                        silent_frames_count = 0 # Reset silence counter if speech is detected
                else:
                    pre_buffer_frames.append(frame)
                    if is_speech:
                        print("Speech detected, recording...")
                        # Reset the idle-monologue timer the moment someone talks.
                        notify_voice_activity(activity_url)
                        is_recording = True
                        recorded_frames.extend(pre_buffer_frames)
    except KeyboardInterrupt:
        print("\nStopping the script.")
    except Exception as e:
        print(f"A critical error occurred: {e}")

if __name__ == "__main__":
    main()