"""
Music Client
Integrates song requests, downloads, library, and playback
into the main Gem-System server.
"""

import os
import sys
import time
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Callable

# Add music folder to path for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(PROJECT_ROOT, "music")
sys.path.insert(0, MUSIC_DIR)

from song_library import SongLibrary
from download_worker import run_download, is_youtube_url
from twitch_music_checker import TwitchMusicChecker


class MusicClient:
    def __init__(self, music_folder: str = None, download_folder: str = None, device_name: Optional[str] = None):
        # Song library (karaoke dual-track songs)
        if music_folder is None:
            music_folder = os.path.join(MUSIC_DIR, "requests", "karaoke")
        self.library = SongLibrary(music_folder=music_folder)

        # Download folder (mp3 requests)
        if download_folder is None:
            download_folder = os.path.join(MUSIC_DIR, "requests")
        self.download_folder = download_folder

        # Background songs folder
        self.background_folder = os.path.join(MUSIC_DIR, "background_songs")

        self.device_name = device_name
        self.queue: List[str] = []
        self.current_download: Optional[str] = None
        self.download_history: List[str] = []
        self.enabled = False
        self.now_playing: Optional[str] = None
        self._stop_requested = False
        self.on_download_complete: Optional[Callable] = None
        self.state_file = os.path.join(PROJECT_ROOT, "now_playing_state.txt")

        # Twitch music checker
        self.twitch_checker = TwitchMusicChecker()

        # Background song state
        self.background_song_path: Optional[str] = None
        self.background_song_paused = False
        self.background_resume_time = 0.0
        self.bg_channel = None
        self.bg_sound = None
        self._cached_duration = 0.0
        self._cached_duration_path = None
        # User's desired background volume (0.0 - 1.0). Ducking restores to this.
        self.background_volume = 1.0
        # Background state persistence (song + position + volume across restarts)
        self.bg_state_file = os.path.join(PROJECT_ROOT, "background_state.json")

    def check_connection(self) -> bool:
        """Check if music system is ready"""
        self.enabled = True
        print(f"✓ Music system ready (library: {len(self.library.list_songs())} songs)")
        return True

    def list_songs(self) -> List[str]:
        """List available karaoke songs"""
        return self.library.list_songs()

    def list_downloaded_songs(self) -> List[str]:
        """List downloaded MP3 request songs (in the download folder)."""
        if not os.path.isdir(self.download_folder):
            return []
        return sorted(
            [f[:-4] for f in os.listdir(self.download_folder) if f.lower().endswith(".mp3")]
        )

    def find_song(self, song_name: str) -> Optional[tuple]:
        """Find a song in the library"""
        return self.library.find_song(song_name)

    def add_to_queue(self, song_name: str) -> bool:
        """Add a song request to the queue"""
        self.queue.append(song_name)
        print(f"🎵 Added to queue: {song_name}")
        return True

    def get_queue(self) -> List[str]:
        """Get current queue"""
        return self.queue

    def clear_queue(self):
        """Clear the queue"""
        self.queue.clear()

    def check_song_exists(self, query: str) -> Optional[str]:
        """Check if a similar song already exists in the download folder.
        Returns the filename if found, otherwise None.
        """
        if not os.path.isdir(self.download_folder):
            return None

        query_clean = query.lower().strip()
        for suffix in [" official video", " official audio", " lyrics", " hd", " 4k"]:
            query_clean = query_clean.replace(suffix, "")

        if " - " in query_clean:
            parts = query_clean.split(" - ")
            artist = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else ""
        else:
            artist = ""
            title = query_clean

        import re
        for filename in os.listdir(self.download_folder):
            if not filename.lower().endswith(".mp3"):
                continue
            filename_clean = filename.lower()[:-4]
            filename_clean = re.sub(r'\s*\[[a-zA-Z0-9_-]+\]\s*$', '', filename_clean)

            artist_match = (artist in filename_clean or filename_clean in artist) if artist else False
            title_match = (title in filename_clean or filename_clean in title) if title else False
            full_match = query_clean in filename_clean or filename_clean in query_clean

            if (artist_match and title_match) or full_match:
                print(f"🎵 Found existing file: {filename}")
                return filename

        return None

    def download_song(self, query: str) -> bool:
        """Download a song (runs in background thread)"""
        if self.current_download:
            print(f"⚠️ Download already in progress: {self.current_download}")
            return False

        self.current_download = query
        thread = threading.Thread(target=self._download_worker, args=(query,), daemon=True)
        thread.start()
        return True

    def verify_song(self, request_text: str) -> Dict:
        """Check if a song is allowed under Twitch DJ Program.
        Returns a dict with status, artist, track, and message.
        """
        return self.twitch_checker.verify_request(request_text)

    def _download_worker(self, query: str):
        """Background download worker"""
        try:
            print(f"🎵 Downloading: {query}")
            run_download(query)
            self.download_history.append(query)
            # Notify memory that a song was downloaded
            if self.on_download_complete:
                try:
                    self.on_download_complete(query)
                except Exception as e:
                    print(f"✗ Download memory callback failed: {e}")
            # Auto-play the downloaded song
            self._play_latest_download()
        except Exception as e:
            print(f"✗ Download failed: {e}")
        finally:
            self.current_download = None

    def _play_latest_download(self):
        """Play the most recently downloaded MP3"""
        try:
            mp3_files = sorted(
                [f for f in os.listdir(self.download_folder) if f.endswith('.mp3')],
                key=lambda f: os.path.getmtime(os.path.join(self.download_folder, f)),
                reverse=True
            )
            if not mp3_files:
                print("⚠️ No MP3 files found to play")
                return

            latest = os.path.join(self.download_folder, mp3_files[0])
            print(f"🎵 Playing downloaded song: {mp3_files[0]}")
            self._play_mp3(latest)
        except Exception as e:
            print(f"✗ Failed to play downloaded song: {e}")

    def _write_state_file(self, song_name: Optional[str]):
        """Write the current song to now_playing_state.txt (or clear it)."""
        try:
            if song_name:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    f.write(song_name)
            else:
                if os.path.exists(self.state_file):
                    os.remove(self.state_file)
        except Exception as e:
            print(f"✗ State file write error: {e}")

    def _play_mp3(self, filepath: str):
        """Play a single MP3 file using pygame (routed to Voicemeeter device)"""
        try:
            import pygame

            # Track what's playing so we can stop it later
            self.now_playing = os.path.basename(filepath)
            self._write_state_file(self.now_playing)

            # Pause background music while the request plays
            self.pause_background_song()

            # Resolve device name (handle '[ID] Name' format)
            resolved_device = None
            if self.device_name:
                try:
                    import sounddevice as sd
                    devices = sd.query_devices()
                    if ']' in self.device_name:
                        device_id = int(self.device_name.split(']')[0].strip('['))
                        for dev in devices:
                            if dev['index'] == device_id and dev['max_output_channels'] > 0:
                                resolved_device = dev['name']
                                break
                    else:
                        resolved_device = self.device_name
                except Exception:
                    resolved_device = self.device_name

            # Initialize mixer with device
            if resolved_device:
                from pygame._sdl2 import get_audio_device_names
                available = get_audio_device_names(False)
                final_device = None
                for device in available:
                    if resolved_device == device or resolved_device in device:
                        final_device = device
                        break
                if final_device:
                    pygame.mixer.pre_init(44100, -16, 2, 512, devicename=final_device)
                    pygame.init()
                    pygame.mixer.init()
                else:
                    pygame.mixer.init()
            else:
                pygame.mixer.init()

            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                import time
                if self._stop_requested:
                    pygame.mixer.music.stop()
                    self._stop_requested = False
                    break
                time.sleep(0.1)
            pygame.mixer.music.unload()
            self.now_playing = None
            self._write_state_file(None)

            # Resume background music after the request finishes
            self.resume_background_song()
        except Exception as e:
            print(f"✗ MP3 playback error: {e}")
            self.now_playing = None
            self._write_state_file(None)
            self.resume_background_song()

    def stop_music(self) -> bool:
        """Stop the currently playing request song (if any)."""
        try:
            import pygame
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                self._stop_requested = True
                pygame.mixer.music.stop()
                self.now_playing = None
                self._write_state_file(None)
                print("🎵 Music stopped")
                return True
            self.now_playing = None
            self._write_state_file(None)
            return False
        except Exception as e:
            print(f"✗ Stop music error: {e}")
            return False

    def play_mp3(self, filename: str) -> bool:
        """Play a downloaded MP3 by filename"""
        filepath = os.path.join(self.download_folder, filename)
        if not os.path.exists(filepath):
            print(f"❌ File not found: {filepath}")
            return False

        print(f"🎵 Playing: {filename}")
        thread = threading.Thread(target=self._play_mp3, args=(filepath,), daemon=True)
        thread.start()
        return True

    # ==================== BACKGROUND SONGS ====================
    def list_background_songs(self) -> List[str]:
        """List available background songs"""
        if not os.path.isdir(self.background_folder):
            return []
        return sorted([f for f in os.listdir(self.background_folder) if f.endswith('.mp3')])

    def set_background_song(self, song_name: str) -> bool:
        """Set and start playing a background song (looping)"""
        filepath = os.path.join(self.background_folder, song_name)
        if not os.path.exists(filepath):
            print(f"❌ Background song not found: {song_name}")
            return False

        self.background_song_path = filepath
        self.background_song_paused = False
        print(f"🎵 Set background song: {song_name}")

        thread = threading.Thread(target=self._play_background_loop, args=(filepath,), daemon=True)
        thread.start()
        return True

    def _play_background_loop(self, filepath: str, start_pos: float = 0.0):
        """Play background song in a loop using mixer.music (supports MP3)"""
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play(loops=-1, start=start_pos)
            pygame.mixer.music.set_volume(self.background_volume)
            print(f"🎵 Background music playing (looping) at volume {self.background_volume:.2f}")
        except Exception as e:
            print(f"✗ Background playback error: {e}")

    def duck_music(self, duck_amount: float = -15.0, attack_ms: int = 100, release_ms: int = 500):
        """Lower background music volume (ducking) when TTS speaks"""
        try:
            import pygame
            if not pygame.mixer.get_init() or not pygame.mixer.music.get_busy():
                return
            # Use the user's desired volume (do NOT overwrite it with the current mixer volume)
            target_volume = max(0.0, self.background_volume * (10.0 ** (duck_amount / 20.0)))
            current_volume = self.background_volume
            steps = max(1, attack_ms // 20)
            volume_step = (current_volume - target_volume) / steps
            for i in range(steps):
                new_vol = current_volume - (volume_step * (i + 1))
                pygame.mixer.music.set_volume(max(0.0, new_vol))
                time.sleep(0.02)
            print(f"🎵 Music ducked to {target_volume:.2f} ({duck_amount}dB)")
        except Exception as e:
            print(f"✗ Duck music error: {e}")

    def unduck_music(self, release_ms: int = 500):
        """Restore background music volume after TTS finishes"""
        try:
            import pygame
            if not pygame.mixer.get_init() or not pygame.mixer.music.get_busy():
                return
            target_volume = self.background_volume
            current_volume = pygame.mixer.music.get_volume()
            steps = max(1, release_ms // 20)
            volume_step = (target_volume - current_volume) / steps
            for i in range(steps):
                new_vol = current_volume + (volume_step * (i + 1))
                pygame.mixer.music.set_volume(min(1.0, max(0.0, new_vol)))
                time.sleep(0.02)
            pygame.mixer.music.set_volume(target_volume)
            print(f"🎵 Music volume restored to {target_volume:.2f}")
        except Exception as e:
            print(f"✗ Unduck music error: {e}")

    def pause_background_song(self) -> bool:
        """Pause the background song (if playing)"""
        try:
            import pygame
            mixer_init = pygame.mixer.get_init()
            music_busy = pygame.mixer.music.get_busy() if mixer_init else False
            print(f"DEBUG pause: mixer_init={mixer_init}, music_busy={music_busy}, bg_path={self.background_song_path}")
            if mixer_init and music_busy:
                pygame.mixer.music.pause()
                self.background_song_paused = True
                print("🎵 Background music paused")
                return True
        except Exception as e:
            print(f"✗ Pause background error: {e}")
        return False

    def resume_background_song(self) -> bool:
        """Resume the background song (if it was paused)"""
        try:
            import pygame
            if self.background_song_paused:
                pygame.mixer.music.unpause()
                self.background_song_paused = False
                print("🎵 Background music resumed")
                return True
        except Exception as e:
            print(f"✗ Resume background error: {e}")
        return False

    def restart_background_song(self) -> bool:
        """Restart the background song from the beginning (reloads it into the mixer)."""
        try:
            import pygame
            if not self.background_song_path or not os.path.exists(self.background_song_path):
                print("⚠️ No background song set to resume")
                return False
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(self.background_song_path)
            pygame.mixer.music.play(loops=-1)
            pygame.mixer.music.set_volume(self.background_volume)
            self.background_song_paused = False
            print(f"🎵 Background music restarted: {os.path.basename(self.background_song_path)}")
            return True
        except Exception as e:
            print(f"✗ Restart background error: {e}")
            return False

    def stop_background_song(self) -> bool:
        """Stop the background song"""
        try:
            import pygame
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            self.background_song_path = None
            self.background_song_paused = False
            print("🎵 Background music stopped")
            return True
        except Exception as e:
            print(f"✗ Stop background error: {e}")
            return False

    def get_background_status(self) -> Dict:
        """Get background song status"""
        return {
            'current': os.path.basename(self.background_song_path) if self.background_song_path else None,
            'paused': self.background_song_paused
        }

    def get_background_position(self) -> float:
        """Get current playback position in seconds"""
        try:
            import pygame
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                return pygame.mixer.music.get_pos() / 1000.0
        except Exception:
            pass
        return 0.0

    def save_background_state(self):
        """Persist the current background song, position, and volume to disk."""
        try:
            import json
            state = {
                "song": os.path.basename(self.background_song_path) if self.background_song_path else None,
                "position": self.get_background_position(),
                "volume": self.background_volume,
            }
            with open(self.bg_state_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
            print(f"💾 Background state saved: {state}")
        except Exception as e:
            print(f"✗ Save background state error: {e}")

    def load_background_state(self) -> Optional[Dict]:
        """Load the persisted background state from disk (if any)."""
        try:
            import json
            if not os.path.exists(self.bg_state_file):
                return None
            with open(self.bg_state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            return state
        except Exception as e:
            print(f"✗ Load background state error: {e}")
            return None

    def resume_background_from_state(self) -> bool:
        """Resume the background song from the persisted state (after restart)."""
        state = self.load_background_state()
        if not state or not state.get("song"):
            return False

        song_name = state["song"]
        filepath = os.path.join(self.background_folder, song_name)
        if not os.path.exists(filepath):
            print(f"⚠️ Saved background song not found: {song_name}")
            return False

        position = float(state.get("position", 0.0))
        volume = float(state.get("volume", 1.0))
        self.background_volume = max(0.0, min(1.0, volume))
        self.background_song_path = filepath
        self.background_song_paused = False

        thread = threading.Thread(
            target=self._play_background_loop, args=(filepath, position), daemon=True
        )
        thread.start()
        print(f"▶️ Resumed background song '{song_name}' at {position:.1f}s (volume {self.background_volume:.2f})")
        return True

    def get_background_duration(self) -> float:
        """Get total duration of the current background song in seconds (cached)"""
        try:
            import pygame
            if self.background_song_path and pygame.mixer.get_init():
                # Cache the duration to avoid reloading the MP3 every poll
                if getattr(self, '_cached_duration_path', None) != self.background_song_path:
                    sound = pygame.mixer.Sound(self.background_song_path)
                    self._cached_duration = sound.get_length()
                    self._cached_duration_path = self.background_song_path
                return self._cached_duration
        except Exception:
            pass
        return 0.0

    def set_background_volume(self, volume: float) -> bool:
        """Set background music volume (0.0 to 1.0)"""
        try:
            import pygame
            volume = max(0.0, min(1.0, volume))
            self.background_volume = volume
            if pygame.mixer.get_init():
                pygame.mixer.music.set_volume(volume)
                return True
        except Exception as e:
            print(f"✗ Set volume error: {e}")
        return False

    def get_download_status(self) -> Dict:
        """Get current download status"""
        return {
            'current': self.current_download,
            'queue_length': len(self.queue),
            'history': self.download_history[-10:]
        }

    def play_song(self, song_name: str) -> bool:
        """Play a karaoke song (vocals + instrumental on separate devices)"""
        result = self.library.find_song(song_name)
        if not result:
            print(f"❌ Song '{song_name}' not found")
            return False

        file1, file2 = result
        print(f"🎵 Playing: {song_name}")
        print(f"  Vocals: {file1}")
        print(f"  Instrumental: {file2}")

        # Pause background music while the karaoke song plays
        self.pause_background_song()

        # Launch dual audio player in background
        thread = threading.Thread(target=self._launch_player, args=(file1, file2), daemon=True)
        thread.start()
        return True

    def _launch_player(self, file1: str, file2: str):
        """Launch headless dual audio player (no Tkinter)"""
        try:
            from headless_dual_audio import play_dual
            play_dual(file1, file2)
        except Exception as e:
            print(f"✗ Player error: {e}")
        finally:
            # Resume background music after the karaoke song finishes
            self.resume_background_song()


if __name__ == "__main__":
    client = MusicClient()
    client.check_connection()
    print(f"Available songs: {client.list_songs()}")
