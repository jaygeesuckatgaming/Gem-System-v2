"""
Simple Audio File Watcher and Player
Watches for new WAV files and plays them automatically
No Neurosync, no face tracking - just audio playback

Can be run standalone OR imported and started as a background thread
from main.py (so you don't need to run it separately).
"""

import os
import time
import threading
from typing import Optional

import pygame


class AudioPlayer:
    def __init__(self, watch_path: str, device_name: Optional[str] = None):
        self.watch_path = watch_path
        self.device_name = device_name
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._initialized = False
        # Ducking callbacks (set by main.py to coordinate with music client)
        self.duck_callback = None
        self.unduck_callback = None

    def _resolve_device_name(self) -> Optional[str]:
        """Resolve the stored device string to an SDL-compatible device name.

        The stored value may be in '[ID] Name' format (from sounddevice).
        SDL's get_audio_device_names returns names WITHOUT the '[ID]' prefix,
        so we must resolve the ID to the full name first.
        """
        if not self.device_name:
            return None

        try:
            import sounddevice as sd
            devices = sd.query_devices()

            # Case 1: '[ID] Name' format -> resolve ID to full name
            if ']' in self.device_name:
                device_id = int(self.device_name.split(']')[0].strip('['))
                for dev in devices:
                    if dev['index'] == device_id and dev['max_output_channels'] > 0:
                        return dev['name']
                # ID not found, fall back to partial name
                name_partial = self.device_name.split('] ', 1)[1]
                for dev in devices:
                    if dev['name'].startswith(name_partial[:20]) and dev['max_output_channels'] > 0:
                        return dev['name']
                return None

            # Case 2: plain name -> use as-is
            return self.device_name
        except Exception as e:
            print(f"AudioPlayer: Device resolution error: {e}")
            return self.device_name

    def _init_mixer(self) -> bool:
        """Initialize pygame mixer with the selected device"""
        try:
            pygame.init()

            resolved_name = self._resolve_device_name()

            if resolved_name:
                from pygame._sdl2 import get_audio_device_names
                available = get_audio_device_names(False)
                final_device = None
                for device in available:
                    if resolved_name == device or resolved_name in device:
                        final_device = device
                        break
                if final_device:
                    pygame.quit()
                    pygame.mixer.pre_init(44100, -16, 2, 512, devicename=final_device)
                    pygame.init()
                    pygame.mixer.init()
                    print(f"AudioPlayer: Using device '{final_device}'")
                else:
                    pygame.mixer.pre_init(44100, -16, 2, 512, devicename=None)
                    pygame.init()
                    pygame.mixer.init()
                    print(f"AudioPlayer: Device '{resolved_name}' not in SDL list, using default")
            else:
                pygame.mixer.pre_init(44100, -16, 2, 512, devicename=None)
                pygame.init()
                pygame.mixer.init()

            if pygame.mixer.get_init():
                print("AudioPlayer: Audio engine ready")
                self._initialized = True
                return True
            else:
                print("AudioPlayer: Audio engine failed to start")
                return False
        except Exception as e:
            print(f"AudioPlayer: Init error: {e}")
            try:
                pygame.quit()
                pygame.init()
                pygame.mixer.init()
                self._initialized = True
                return True
            except Exception:
                return False

    def _delete_file(self, filepath: str):
        """Delete file with retry to handle locks"""
        for _ in range(5):
            try:
                os.remove(filepath)
                return
            except PermissionError:
                time.sleep(0.2)
            except FileNotFoundError:
                return
            except Exception:
                return

    def _watch_loop(self):
        """Main watch loop (runs in background thread)"""
        print(f"AudioPlayer: Watching for {self.watch_path}")

        while not self._stop_event.is_set():
            if os.path.exists(self.watch_path):
                # Wait for file to be fully written
                last_size = os.path.getsize(self.watch_path)
                time.sleep(0.1)
                while last_size != os.path.getsize(self.watch_path):
                    last_size = os.path.getsize(self.watch_path)
                    time.sleep(0.1)

                print("AudioPlayer: Playing audio...")
                # Signal ducking start
                if self.duck_callback:
                    try:
                        self.duck_callback()
                    except Exception as e:
                        print(f"AudioPlayer: duck callback error: {e}")
                try:
                    # Play TTS on a dedicated channel (WAV), leaving mixer.music
                    # free for background music so ducking can lower it.
                    tts_sound = pygame.mixer.Sound(self.watch_path)
                    tts_channel = tts_sound.play()
                    while tts_channel.get_busy() and not self._stop_event.is_set():
                        time.sleep(0.1)
                except Exception as e:
                    print(f"AudioPlayer: Playback error: {e}")
                finally:
                    try:
                        pygame.mixer.stop()
                    except Exception:
                        pass
                    self._delete_file(self.watch_path)
                    # Signal ducking release
                    if self.unduck_callback:
                        try:
                            self.unduck_callback()
                        except Exception as e:
                            print(f"AudioPlayer: unduck callback error: {e}")

            time.sleep(0.5)

    def start(self):
        """Start the audio player in a background thread"""
        if self._thread and self._thread.is_alive():
            print("AudioPlayer: Already running")
            return

        if not self._init_mixer():
            print("AudioPlayer: Failed to initialize, not starting")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop_playback(self):
        """Immediately stop the currently playing TTS audio (for interruption)."""
        try:
            pygame.mixer.stop()
        except Exception:
            pass
        try:
            if os.path.exists(self.watch_path):
                self._delete_file(self.watch_path)
        except Exception:
            pass

    def is_playing(self) -> bool:
        """Return True if TTS audio is currently playing."""
        try:
            return bool(pygame.mixer.get_busy())
        except Exception:
            return False

    def stop(self):
        """Stop the audio player"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        try:
            pygame.quit()
        except Exception:
            pass
        print("AudioPlayer: Stopped")


if __name__ == "__main__":
    # Standalone mode: watch the default tts_output folder
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    watch_path = os.path.join(project_root, "tts_output", "server_output.wav")

    player = AudioPlayer(watch_path=watch_path)
    player.start()

    print("Audio Player Started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        player.stop()
