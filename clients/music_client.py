"""
Music Client
Integrates song requests, downloads, library, and playback
into the main Gem-System server.
"""

import os
import sys
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict

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
        self.background_folder = os.path.join(PROJECT_ROOT, "background_songs")

        self.device_name = device_name
        self.queue: List[str] = []
        self.current_download: Optional[str] = None
        self.download_history: List[str] = []
        self.enabled = False

        # Twitch music checker
        self.twitch_checker = TwitchMusicChecker()

        # Background song state
        self.background_song_path: Optional[str] = None
        self.background_song_paused = False
        self.background_resume_time = 0.0

    def check_connection(self) -> bool:
        """Check if music system is ready"""
        self.enabled = True
        print(f"✓ Music system ready (library: {len(self.library.list_songs())} songs)")
        return True

    def list_songs(self) -> List[str]:
        """List available karaoke songs"""
        return self.library.list_songs()

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

    def _play_mp3(self, filepath: str):
        """Play a single MP3 file using pygame (routed to Voicemeeter device)"""
        try:
            import pygame

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
                time.sleep(0.1)
            pygame.mixer.music.unload()
        except Exception as e:
            print(f"✗ MP3 playback error: {e}")

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

    def _play_background_loop(self, filepath: str):
        """Play background song in a loop"""
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play(loops=-1)
            print(f"🎵 Background music playing (looping)")
        except Exception as e:
            print(f"✗ Background playback error: {e}")

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

        # Launch dual audio player in background
        thread = threading.Thread(target=self._launch_player, args=(file1, file2), daemon=True)
        thread.start()
        return True

    def _launch_player(self, file1: str, file2: str):
        """Launch dual audio player"""
        try:
            from dual_audio_player import DualAudioPlayer
            player = DualAudioPlayer()
            player.load_files(file1, file2)
            player.run()
        except Exception as e:
            print(f"✗ Player error: {e}")


if __name__ == "__main__":
    client = MusicClient()
    client.check_connection()
    print(f"Available songs: {client.list_songs()}")
