import sys
import os
import subprocess
import re
import ytmusicapi

def is_youtube_url(text):
    """Check if text is a YouTube URL"""
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+',
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def extract_youtube_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([\w-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def run_download(query):
    """
    Finds a song on YouTube Music and downloads it as an MP3
    using the yt-dlp command-line tool.
    """
    try:
        # Output folder is music/requests (relative to this file)
        output_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requests")
        os.makedirs(output_folder, exist_ok=True)
        
        # Assumes yt-dlp executable is in the same folder or in system PATH
        yt_dlp_command = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
        
        # --- 1. Check if it's a direct YouTube URL ---
        if is_youtube_url(query):
            print(f"Direct YouTube URL detected: {query}")
            video_url = query
            video_id = extract_youtube_video_id(query)
            if not video_id:
                print("ERROR: Could not extract video ID from URL")
                return
            
            # Get video title from URL for display
            print(f"Video ID: {video_id}")
        else:
            # --- 2. Search for the song ---
            print(f"Searching for: '{query}'...")
            yt = ytmusicapi.YTMusic()
            search_results = yt.search(query)

            if not search_results:
                print("ERROR: No results found for your query.")
                return

            video_id = search_results[0]["videoId"]
            video_title = search_results[0]["title"]
            print(f"Found Video: '{video_title}' (ID: {video_id})")

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"Preparing to download from: {video_url}")
        
        print("-" * 50)

        # Cookies file is in the project root (one level up from music/)
        cookies_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt")
        
        command = [
            yt_dlp_command,
            "-f", "bv*[height<=144]+ba/b[height<=144]/w",
            "-x",
            "--audio-format", "mp3",
            "--extractor-args", "youtube:player_client=android",
            "--cookies", cookies_path,
            "-P", output_folder,
            "-o", "%(title)s.%(ext)s",
            "--no-playlist",
            video_url
        ]
        
        # Use Popen to stream output in real-time
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')

        # Print each line of output as it comes
        for line in iter(process.stdout.readline, ''):
            print(line.strip())
        
        process.wait() # Wait for the download to complete
        
        if process.returncode == 0:
            print("-" * 50)
            print("SUCCESS: Download complete.")
            
            # Clean up filenames - remove YouTube video IDs in brackets
            for filename in os.listdir(output_folder):
                if filename.endswith(('.mp3', '.mp4', '.webm', '.mkv')):
                    # Remove YouTube video ID in square brackets [ebXbLfLACGM]
                    clean_name = re.sub(r'\s*\[[a-zA-Z0-9_-]{11}\](\.[a-zA-Z0-9]+)$', r'\1', filename)
                    if clean_name != filename:
                        old_path = os.path.join(output_folder, filename)
                        new_path = os.path.join(output_folder, clean_name)
                        os.rename(old_path, new_path)
                        print(f"Renamed: '{filename}' -> '{clean_name}'")
        else:
            print("-" * 50)
            print(f"ERROR: yt-dlp exited with error code {process.returncode}")

    except FileNotFoundError:
        print("ERROR: 'yt-dlp' command not found.")
        print("Please make sure the yt-dlp executable is in your system's PATH or in the same directory as the script.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    # Get the search query from the command-line arguments
    if len(sys.argv) > 1:
        search_query = " ".join(sys.argv[1:])
        run_download(search_query)
    else:
        print("Usage: python download_worker.py <search query>")