"""
Gem-System v2 - Control Panel GUI
Uses customtkinter for a modern look
Communicates with main.py via HTTP API
"""

import customtkinter as ctk
import httpx
import threading
import time
import math
import numpy as np
import sounddevice as sd
import subprocess
import os

# Server URL
SERVER_URL = "http://127.0.0.1:5000"
COGNEE_SERVER_URL = "http://127.0.0.1:8011"

# VU meter constants
MIN_DB = -60.0
MAX_DB = 0.0
SMOOTHING_FACTOR = 0.85
PEAK_HOLD_DURATION = 1.5
TEST_TONE_FREQUENCY = 440

# Appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ControlPanel(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Gem-System v2 - Control Panel")
        self.geometry("1000x800")
        
        # Create tab view
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Add tabs
        self.status_tab = self.tabview.add("Status")
        self.llm_tab = self.tabview.add("LLM")
        self.memory_tab = self.tabview.add("Memory")
        self.tts_tab = self.tabview.add("TTS")
        self.audio_tab = self.tabview.add("Audio")
        self.music_tab = self.tabview.add("Music Requests")
        self.neurosync_tab = self.tabview.add("Neurosync")
        self.osc_tab = self.tabview.add("OSC")
        self.ssn_tab = self.tabview.add("Social Stream Ninja")
        
        self.build_status_tab()
        self.build_llm_tab()
        self.build_memory_tab()
        self.build_tts_tab()
        self.build_audio_tab()
        self.build_music_tab()
        self.build_neurosync_tab()
        self.build_osc_tab()
        self.build_ssn_tab()
        
        # Start status polling
        self.polling = True
        self.poll_thread = threading.Thread(target=self.poll_status, daemon=True)
        self.poll_thread.start()
    
    # ==================== STATUS TAB ====================
    def build_status_tab(self):
        """Build the Status tab with all connection indicators"""
        title = ctk.CTkLabel(self.status_tab, text="System Status", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=20)
        
        status_frame = ctk.CTkFrame(self.status_tab)
        status_frame.pack(fill="x", padx=20, pady=10)
        
        # LLM status
        self.status_llm = ctk.CTkLabel(status_frame, text="LLM: Checking...", font=ctk.CTkFont(size=16))
        self.status_llm.pack(anchor="w", padx=20, pady=10)
        
        # SSN status
        self.status_ssn = ctk.CTkLabel(status_frame, text="SSN: Checking...", font=ctk.CTkFont(size=16))
        self.status_ssn.pack(anchor="w", padx=20, pady=10)
        
        # Cognee status
        self.status_cognee = ctk.CTkLabel(status_frame, text="Cognee: Checking...", font=ctk.CTkFont(size=16))
        self.status_cognee.pack(anchor="w", padx=20, pady=10)
        
        # TTS status
        self.status_tts = ctk.CTkLabel(status_frame, text="TTS: Checking...", font=ctk.CTkFont(size=16))
        self.status_tts.pack(anchor="w", padx=20, pady=10)
        
        # Music status
        self.status_music = ctk.CTkLabel(status_frame, text="Music: Checking...", font=ctk.CTkFont(size=16))
        self.status_music.pack(anchor="w", padx=20, pady=10)
        
        # Refresh button
        refresh_btn = ctk.CTkButton(self.status_tab, text="Refresh", command=self.refresh_status)
        refresh_btn.pack(pady=20)
        
        # Start Listener button
        start_listen_btn = ctk.CTkButton(self.status_tab, text="Start Audio Listener", command=self.start_listener)
        start_listen_btn.pack(pady=10)
    
    def start_listener(self):
        """Launch the audio listener (listen.py)"""
        bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_scripts", "start_listen.bat")
        try:
            subprocess.Popen([bat_path], shell=True)
            print("✓ Started Audio Listener")
        except Exception as e:
            print(f"Failed to start listener: {e}")
    
    # ==================== LLM TAB ====================
    def build_llm_tab(self):
        """Build the LLM tab"""
        title = ctk.CTkLabel(self.llm_tab, text="LLM Configuration", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=20)
        
        # Connection status
        self.llm_status = ctk.CTkLabel(self.llm_tab, text="Status: Checking...", font=ctk.CTkFont(size=16))
        self.llm_status.pack(anchor="w", padx=20, pady=5)
        
        # Model
        model_label = ctk.CTkLabel(self.llm_tab, text="Ollama Model:", font=ctk.CTkFont(size=14))
        model_label.pack(anchor="w", padx=20, pady=(20, 0))
        
        self.model_entry = ctk.CTkEntry(self.llm_tab)
        self.model_entry.pack(fill="x", padx=20, pady=10)
        
        # System prompt
        prompt_label = ctk.CTkLabel(self.llm_tab, text="System Prompt:", font=ctk.CTkFont(size=14))
        prompt_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        self.prompt_textbox = ctk.CTkTextbox(self.llm_tab, height=200)
        self.prompt_textbox.pack(fill="x", padx=20, pady=10)
        
        # Wake words
        wake_label = ctk.CTkLabel(self.llm_tab, text="Wake Words (comma separated):", font=ctk.CTkFont(size=14))
        wake_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        self.wake_entry = ctk.CTkEntry(self.llm_tab)
        self.wake_entry.pack(fill="x", padx=20, pady=10)
        
        # Save button
        save_btn = ctk.CTkButton(self.llm_tab, text="Save LLM Settings", command=self.save_llm_settings)
        save_btn.pack(pady=20)
        
        # Load current settings
        self.load_llm_settings()
    
    # ==================== MEMORY TAB ====================
    def build_memory_tab(self):
        """Build the Memory tab with all Cognee settings"""
        title = ctk.CTkLabel(self.memory_tab, text="Memory (Cognee)", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10)
        
        # Connection status
        self.memory_status = ctk.CTkLabel(self.memory_tab, text="Status: Checking...", font=ctk.CTkFont(size=16))
        self.memory_status.pack(anchor="w", padx=20, pady=5)
        
        # Scrollable frame for settings
        scroll_frame = ctk.CTkScrollableFrame(self.memory_tab)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # --- LLM Settings ---
        llm_section = ctk.CTkLabel(scroll_frame, text="LLM Configuration", font=ctk.CTkFont(size=16, weight="bold"))
        llm_section.pack(anchor="w", pady=(10, 5))
        
        llm_model_label = ctk.CTkLabel(scroll_frame, text="LLM Model:", font=ctk.CTkFont(size=13))
        llm_model_label.pack(anchor="w")
        self.cognee_llm_model = ctk.CTkEntry(scroll_frame)
        self.cognee_llm_model.pack(fill="x", pady=(0, 10))
        
        llm_endpoint_label = ctk.CTkLabel(scroll_frame, text="LLM Endpoint:", font=ctk.CTkFont(size=13))
        llm_endpoint_label.pack(anchor="w")
        self.cognee_llm_endpoint = ctk.CTkEntry(scroll_frame)
        self.cognee_llm_endpoint.pack(fill="x", pady=(0, 10))
        
        # --- Embedding Settings ---
        emb_section = ctk.CTkLabel(scroll_frame, text="Embedding Configuration", font=ctk.CTkFont(size=16, weight="bold"))
        emb_section.pack(anchor="w", pady=(10, 5))
        
        emb_model_label = ctk.CTkLabel(scroll_frame, text="Embedding Model:", font=ctk.CTkFont(size=13))
        emb_model_label.pack(anchor="w")
        self.cognee_emb_model = ctk.CTkEntry(scroll_frame)
        self.cognee_emb_model.pack(fill="x", pady=(0, 10))
        
        emb_endpoint_label = ctk.CTkLabel(scroll_frame, text="Embedding Endpoint:", font=ctk.CTkFont(size=13))
        emb_endpoint_label.pack(anchor="w")
        self.cognee_emb_endpoint = ctk.CTkEntry(scroll_frame)
        self.cognee_emb_endpoint.pack(fill="x", pady=(0, 10))
        
        emb_dim_label = ctk.CTkLabel(scroll_frame, text="Embedding Dimensions:", font=ctk.CTkFont(size=13))
        emb_dim_label.pack(anchor="w")
        self.cognee_emb_dim = ctk.CTkEntry(scroll_frame)
        self.cognee_emb_dim.pack(fill="x", pady=(0, 10))
        
        # --- Storage Settings ---
        storage_section = ctk.CTkLabel(scroll_frame, text="Storage", font=ctk.CTkFont(size=16, weight="bold"))
        storage_section.pack(anchor="w", pady=(10, 5))
        
        data_dir_label = ctk.CTkLabel(scroll_frame, text="Data Directory:", font=ctk.CTkFont(size=13))
        data_dir_label.pack(anchor="w")
        self.cognee_data_dir = ctk.CTkEntry(scroll_frame)
        self.cognee_data_dir.pack(fill="x", pady=(0, 10))
        
        system_dir_label = ctk.CTkLabel(scroll_frame, text="System Directory:", font=ctk.CTkFont(size=13))
        system_dir_label.pack(anchor="w")
        self.cognee_system_dir = ctk.CTkEntry(scroll_frame)
        self.cognee_system_dir.pack(fill="x", pady=(0, 10))
        
        # --- Behavior Settings ---
        behavior_section = ctk.CTkLabel(scroll_frame, text="Behavior", font=ctk.CTkFont(size=16, weight="bold"))
        behavior_section.pack(anchor="w", pady=(10, 5))
        
        self.cognee_caching = ctk.BooleanVar(value=True)
        caching_check = ctk.CTkCheckBox(scroll_frame, text="Caching (session memory)", variable=self.cognee_caching)
        caching_check.pack(anchor="w", pady=5)
        
        self.cognee_feedback = ctk.BooleanVar(value=False)
        feedback_check = ctk.CTkCheckBox(scroll_frame, text="Auto Feedback", variable=self.cognee_feedback)
        feedback_check.pack(anchor="w", pady=5)
        
        # Save button
        save_btn = ctk.CTkButton(scroll_frame, text="Save Cognee Settings", command=self.save_cognee_settings)
        save_btn.pack(pady=20)
        
        # --- Test Recall Section ---
        recall_section = ctk.CTkLabel(scroll_frame, text="Test Memory Recall", font=ctk.CTkFont(size=16, weight="bold"))
        recall_section.pack(anchor="w", pady=(10, 5))
        
        recall_frame = ctk.CTkFrame(scroll_frame)
        recall_frame.pack(fill="x", pady=5)
        
        self.recall_entry = ctk.CTkEntry(recall_frame, placeholder_text="Enter query (e.g. Alice123)")
        self.recall_entry.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        
        recall_btn = ctk.CTkButton(recall_frame, text="Recall", width=100, command=self.test_recall)
        recall_btn.pack(side="right", padx=10, pady=10)
        
        # Results display
        self.recall_results = ctk.CTkTextbox(scroll_frame, height=150)
        self.recall_results.pack(fill="x", pady=10)
        self.recall_results.configure(state="disabled")
        
        # Load current settings
        self.load_cognee_settings()
    
    # ==================== TTS TAB ====================
    def build_tts_tab(self):
        """Build the TTS tab with StyleTTS2 settings"""
        title = ctk.CTkLabel(self.tts_tab, text="Text-to-Speech (StyleTTS2)", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10)
        
        # Connection status
        self.tts_status = ctk.CTkLabel(self.tts_tab, text="Status: Checking...", font=ctk.CTkFont(size=16))
        self.tts_status.pack(anchor="w", padx=20, pady=5)
        
        # Enable toggle
        self.tts_enabled_var = ctk.BooleanVar(value=False)
        enable_check = ctk.CTkCheckBox(self.tts_tab, text="Enable TTS", variable=self.tts_enabled_var)
        enable_check.pack(anchor="w", padx=20, pady=10)
        
        # Audio player toggle (plays TTS output when not using Neurosync)
        self.audio_player_var = ctk.BooleanVar(value=True)
        audio_check = ctk.CTkCheckBox(self.tts_tab, text="Enable Audio Player (disable when using Neurosync)", variable=self.audio_player_var)
        audio_check.pack(anchor="w", padx=20, pady=10)
        
        # TTS URL
        url_label = ctk.CTkLabel(self.tts_tab, text="TTS Server URL:", font=ctk.CTkFont(size=14))
        url_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        self.tts_url_entry = ctk.CTkEntry(self.tts_tab)
        self.tts_url_entry.pack(fill="x", padx=20, pady=10)
        
        # Save button (top, always visible)
        save_btn = ctk.CTkButton(self.tts_tab, text="Save TTS Settings", command=self.save_tts_settings)
        save_btn.pack(pady=10)
        
        # Scrollable frame for StyleTTS2 parameters
        params_frame = ctk.CTkScrollableFrame(self.tts_tab, height=400)
        params_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # StyleTTS2 parameters section
        params_label = ctk.CTkLabel(params_frame, text="StyleTTS2 Parameters", font=ctk.CTkFont(size=16, weight="bold"))
        params_label.pack(anchor="w", pady=(5, 10))
        
        # Diffusion steps
        diff_label = ctk.CTkLabel(params_frame, text="Diffusion Steps:", font=ctk.CTkFont(size=13))
        diff_label.pack(anchor="w")
        self.diffusion_steps_slider = ctk.CTkSlider(params_frame, from_=5, to=50, number_of_steps=45, command=self.update_diffusion_label)
        self.diffusion_steps_slider.pack(fill="x", pady=(0, 5))
        self.diffusion_value_label = ctk.CTkLabel(params_frame, text="20", font=ctk.CTkFont(size=12))
        self.diffusion_value_label.pack(anchor="e")
        
        # Embedding scale
        emb_label = ctk.CTkLabel(params_frame, text="Embedding Scale:", font=ctk.CTkFont(size=13))
        emb_label.pack(anchor="w", pady=(10, 0))
        self.embedding_scale_slider = ctk.CTkSlider(params_frame, from_=0.5, to=1.5, number_of_steps=20, command=self.update_embedding_label)
        self.embedding_scale_slider.pack(fill="x", pady=(0, 5))
        self.embedding_value_label = ctk.CTkLabel(params_frame, text="1.0", font=ctk.CTkFont(size=12))
        self.embedding_value_label.pack(anchor="e")
        
        # Alpha
        alpha_label = ctk.CTkLabel(params_frame, text="Alpha (speed):", font=ctk.CTkFont(size=13))
        alpha_label.pack(anchor="w", pady=(10, 0))
        self.alpha_slider = ctk.CTkSlider(params_frame, from_=0.0, to=1.0, number_of_steps=20, command=self.update_alpha_label)
        self.alpha_slider.pack(fill="x", pady=(0, 5))
        self.alpha_value_label = ctk.CTkLabel(params_frame, text="0.3", font=ctk.CTkFont(size=12))
        self.alpha_value_label.pack(anchor="e")
        
        # Beta
        beta_label = ctk.CTkLabel(params_frame, text="Beta (emotion):", font=ctk.CTkFont(size=13))
        beta_label.pack(anchor="w", pady=(10, 0))
        self.beta_slider = ctk.CTkSlider(params_frame, from_=0.0, to=1.0, number_of_steps=20, command=self.update_beta_label)
        self.beta_slider.pack(fill="x", pady=(0, 5))
        self.beta_value_label = ctk.CTkLabel(params_frame, text="0.7", font=ctk.CTkFont(size=12))
        self.beta_value_label.pack(anchor="e")
        
        # Reference voice
        voice_label = ctk.CTkLabel(params_frame, text="Reference Voice:", font=ctk.CTkFont(size=13))
        voice_label.pack(anchor="w", pady=(10, 0))
        self.reference_voice_entry = ctk.CTkEntry(params_frame)
        self.reference_voice_entry.pack(fill="x", pady=(0, 10))
        
        # Test TTS section
        test_label = ctk.CTkLabel(self.tts_tab, text="Test TTS:", font=ctk.CTkFont(size=14))
        test_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        test_frame = ctk.CTkFrame(self.tts_tab)
        test_frame.pack(fill="x", padx=20, pady=10)
        
        self.tts_test_entry = ctk.CTkEntry(test_frame, placeholder_text="Enter text to speak")
        self.tts_test_entry.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        
        test_btn = ctk.CTkButton(test_frame, text="Speak", width=100, command=self.test_tts)
        test_btn.pack(side="right", padx=10, pady=10)
        
        # Load current settings
        self.load_tts_settings()
    
    def update_diffusion_label(self, value):
        self.diffusion_value_label.configure(text=str(int(value)))
    
    def update_embedding_label(self, value):
        self.embedding_value_label.configure(text=f"{value:.1f}")
    
    def update_alpha_label(self, value):
        self.alpha_value_label.configure(text=f"{value:.2f}")
    
    def update_beta_label(self, value):
        self.beta_value_label.configure(text=f"{value:.2f}")
    
    # ==================== AUDIO TAB ====================
    def build_audio_tab(self):
        """Build the Audio settings tab"""
        self._current_device = ""
        self._current_input_device = ""
        self._is_testing_output = False
        self._output_stream = None
        self._output_start_idx = 0
        self._output_smoothed_db = MIN_DB
        self._output_peak_db = MIN_DB
        self._output_peak_hold_time = time.time()
        
        title = ctk.CTkLabel(self.audio_tab, text="Audio Settings", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10)
        
        # Scrollable frame
        scroll_frame = ctk.CTkScrollableFrame(self.audio_tab)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # --- Output Device ---
        device_section = ctk.CTkLabel(scroll_frame, text="Output Device", font=ctk.CTkFont(size=16, weight="bold"))
        device_section.pack(anchor="w", pady=(5, 10))
        
        device_label = ctk.CTkLabel(scroll_frame, text="Audio Output Device:", font=ctk.CTkFont(size=13))
        device_label.pack(anchor="w")
        
        self.audio_device_combo = ctk.CTkComboBox(scroll_frame, values=["System Default"], width=400)
        self.audio_device_combo.pack(fill="x", pady=(0, 5))
        
        # Device buttons row
        device_btn_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        device_btn_frame.pack(fill="x", pady=(0, 5))
        
        refresh_devices_btn = ctk.CTkButton(device_btn_frame, text="Refresh Devices", width=150, command=self.refresh_audio_devices)
        refresh_devices_btn.pack(side="left", padx=(0, 10))
        
        self.test_output_btn = ctk.CTkButton(device_btn_frame, text="Test", width=100, command=self.toggle_output_test)
        self.test_output_btn.pack(side="left")
        
        # Output VU meter
        vu_label = ctk.CTkLabel(scroll_frame, text="Output VU Meter:", font=ctk.CTkFont(size=13))
        vu_label.pack(anchor="w", pady=(10, 0))
        
        self.output_vu_canvas = ctk.CTkCanvas(scroll_frame, height=30, bg="#1a1a1a", highlightthickness=0)
        self.output_vu_canvas.pack(fill="x", pady=(0, 15))
        
        # --- Input Device (for listener) ---
        input_section = ctk.CTkLabel(scroll_frame, text="Input Device (Listener)", font=ctk.CTkFont(size=16, weight="bold"))
        input_section.pack(anchor="w", pady=(5, 10))
        
        input_label = ctk.CTkLabel(scroll_frame, text="Audio Input Device:", font=ctk.CTkFont(size=13))
        input_label.pack(anchor="w")
        
        self.audio_input_combo = ctk.CTkComboBox(scroll_frame, values=["None"], width=400)
        self.audio_input_combo.pack(fill="x", pady=(0, 5))
        
        input_btn_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        input_btn_frame.pack(fill="x", pady=(0, 15))
        
        refresh_input_btn = ctk.CTkButton(input_btn_frame, text="Refresh Input Devices", width=180, command=self.refresh_input_devices)
        refresh_input_btn.pack(side="left", padx=(0, 10))
        
        save_input_btn = ctk.CTkButton(input_btn_frame, text="Save Input Device", width=150, command=self.save_input_device)
        save_input_btn.pack(side="left")
        
        # --- Audio Ducking ---
        ducking_section = ctk.CTkLabel(scroll_frame, text="Audio Ducking", font=ctk.CTkFont(size=16, weight="bold"))
        ducking_section.pack(anchor="w", pady=(10, 5))
        
        self.ducking_enabled_var = ctk.BooleanVar(value=False)
        ducking_check = ctk.CTkCheckBox(scroll_frame, text="Enable Audio Ducking (lower music when TTS speaks)", variable=self.ducking_enabled_var)
        ducking_check.pack(anchor="w", pady=5)
        
        # Duck amount
        duck_amount_label = ctk.CTkLabel(scroll_frame, text="Duck Amount (dB):", font=ctk.CTkFont(size=13))
        duck_amount_label.pack(anchor="w", pady=(10, 0))
        self.duck_amount_slider = ctk.CTkSlider(scroll_frame, from_=-30, to=0, number_of_steps=30, command=self.update_duck_amount_label)
        self.duck_amount_slider.pack(fill="x", pady=(0, 5))
        self.duck_amount_value = ctk.CTkLabel(scroll_frame, text="-15 dB", font=ctk.CTkFont(size=12))
        self.duck_amount_value.pack(anchor="e")
        
        # Attack time
        attack_label = ctk.CTkLabel(scroll_frame, text="Attack Time (ms):", font=ctk.CTkFont(size=13))
        attack_label.pack(anchor="w", pady=(10, 0))
        self.attack_slider = ctk.CTkSlider(scroll_frame, from_=0, to=1000, number_of_steps=100, command=self.update_attack_label)
        self.attack_slider.pack(fill="x", pady=(0, 5))
        self.attack_value = ctk.CTkLabel(scroll_frame, text="100 ms", font=ctk.CTkFont(size=12))
        self.attack_value.pack(anchor="e")
        
        # Release time
        release_label = ctk.CTkLabel(scroll_frame, text="Release Time (ms):", font=ctk.CTkFont(size=13))
        release_label.pack(anchor="w", pady=(10, 0))
        self.release_slider = ctk.CTkSlider(scroll_frame, from_=0, to=2000, number_of_steps=200, command=self.update_release_label)
        self.release_slider.pack(fill="x", pady=(0, 5))
        self.release_value = ctk.CTkLabel(scroll_frame, text="500 ms", font=ctk.CTkFont(size=12))
        self.release_value.pack(anchor="e")
        
        # Save button
        save_btn = ctk.CTkButton(scroll_frame, text="Save Audio Settings", command=self.save_audio_settings)
        save_btn.pack(pady=20)
        
        # Load current settings
        self.load_audio_settings()
        self.refresh_audio_devices()
        
        # Start VU meter update loop
        self.after(50, self.update_vu_meter)
    
    def update_duck_amount_label(self, value):
        self.duck_amount_value.configure(text=f"{int(value)} dB")
    
    def update_attack_label(self, value):
        self.attack_value.configure(text=f"{int(value)} ms")
    
    def update_release_label(self, value):
        self.release_value.configure(text=f"{int(value)} ms")
    
    def refresh_audio_devices(self):
        """Fetch available audio output devices"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/audio/devices", timeout=5)
            if response.status_code == 200:
                data = response.json()
                devices = data.get('devices', [])
                
                device_names = ["System Default"]
                for dev in devices:
                    device_names.append(f"[{dev['index']}] {dev['name']}")
                
                self.audio_device_combo.configure(values=device_names)
                
                # Restore current selection by matching device ID
                current = self._current_device
                matched = False
                if current and current != "System Default" and '[' in current:
                    current_id = current.split(']')[0].strip('[')
                    for name in device_names:
                        if name.startswith(f"[{current_id}]"):
                            self.audio_device_combo.set(name)
                            matched = True
                            break
                if not matched:
                    self.audio_device_combo.set("System Default")
        except Exception as e:
            print(f"Failed to fetch audio devices: {e}")
    
    def refresh_input_devices(self):
        """Fetch available audio input devices"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/audio/input_devices", timeout=5)
            if response.status_code == 200:
                data = response.json()
                devices = data.get('devices', [])
                
                device_names = ["None"]
                for dev in devices:
                    device_names.append(f"[{dev['index']}] {dev['name']}")
                
                self.audio_input_combo.configure(values=device_names)
                
                # Restore current selection by matching device ID
                current = self._current_input_device
                matched = False
                if current and current != "None" and '[' in current:
                    current_id = current.split(']')[0].strip('[')
                    for name in device_names:
                        if name.startswith(f"[{current_id}]"):
                            self.audio_input_combo.set(name)
                            matched = True
                            break
                if not matched:
                    self.audio_input_combo.set("None")
        except Exception as e:
            print(f"Failed to fetch input devices: {e}")
    
    def save_input_device(self):
        """Save the selected input device to mcp_settings.ini"""
        selected = self.audio_input_combo.get()
        if selected == "None":
            device_string = "None"
        else:
            device_string = selected
        
        try:
            response = httpx.post(f"{SERVER_URL}/api/audio/input_device", json={"device": device_string}, timeout=5)
            if response.status_code == 200:
                self._current_input_device = device_string
                print(f"✓ Input device saved: {device_string}")
        except Exception as e:
            print(f"Failed to save input device: {e}")
    
    def load_audio_settings(self):
        """Load current audio settings from server"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                audio = data.get('audio', {})
                
                self._current_device = audio.get('output_device', '')
                
                self.ducking_enabled_var.set(audio.get('ducking_enabled', False))
                
                self.duck_amount_slider.set(audio.get('duck_amount', -15))
                self.duck_amount_value.configure(text=f"{audio.get('duck_amount', -15)} dB")
                
                self.attack_slider.set(audio.get('attack_ms', 100))
                self.attack_value.configure(text=f"{audio.get('attack_ms', 100)} ms")
                
                self.release_slider.set(audio.get('release_ms', 500))
                self.release_value.configure(text=f"{audio.get('release_ms', 500)} ms")
        except Exception as e:
            print(f"Failed to load audio settings: {e}")
        
        # Load input device from mcp_settings.ini
        try:
            response = httpx.get(f"{SERVER_URL}/api/audio/input_device", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self._current_input_device = data.get('selected_input', '')
        except Exception as e:
            print(f"Failed to load input device: {e}")
        
        # Refresh input devices
        self.refresh_input_devices()
    
    def save_audio_settings(self):
        """Save audio settings to server"""
        try:
            selected_device = self.audio_device_combo.get()
            if selected_device == "System Default":
                device_name = ""
            else:
                device_name = selected_device
            
            payload = {
                'audio_output_device': device_name,
                'audio_ducking_enabled': self.ducking_enabled_var.get(),
                'audio_duck_amount': int(self.duck_amount_slider.get()),
                'audio_duck_attack_ms': int(self.attack_slider.get()),
                'audio_duck_release_ms': int(self.release_slider.get())
            }
            
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ Audio settings saved")
        except Exception as e:
            print(f"Failed to save audio settings: {e}")
    
    # ==================== OUTPUT TEST + VU METER ====================
    def _get_selected_device_id(self):
        """Extract device ID from the selected combo value"""
        selected = self.audio_device_combo.get()
        if selected == "System Default" or '[' not in selected:
            return None
        try:
            return int(selected.split(']')[0].strip('['))
        except Exception:
            return None
    
    def toggle_output_test(self):
        """Start/stop the output test tone"""
        if getattr(self, '_is_testing_output', False):
            self.stop_output_test()
        else:
            self.start_output_test()
    
    def start_output_test(self):
        """Play a 440Hz test tone through the selected device"""
        device_id = self._get_selected_device_id()
        if device_id is None:
            print("No valid device selected for test")
            return
        
        self._is_testing_output = True
        self._output_start_idx = 0
        self._output_smoothed_db = MIN_DB
        self._output_peak_db = MIN_DB
        self._output_peak_hold_time = time.time()
        self.test_output_btn.configure(text="Stop")
        
        try:
            samplerate = sd.query_devices(device_id, 'output')['default_samplerate']
            self._output_stream = sd.OutputStream(
                device=device_id, channels=1, samplerate=samplerate,
                callback=self._output_audio_callback
            )
            self._output_stream.start()
            print(f"Output test started on device {device_id}")
        except Exception as e:
            print(f"Error starting output test: {e}")
            self.stop_output_test()
    
    def stop_output_test(self):
        """Stop the output test tone"""
        if getattr(self, '_output_stream', None):
            try:
                self._output_stream.close()
            except Exception:
                pass
        self._output_stream = None
        self._is_testing_output = False
        self.test_output_btn.configure(text="Test")
        self._output_smoothed_db = MIN_DB
        self._output_peak_db = MIN_DB
    
    def _output_audio_callback(self, outdata, frames, time_info, status):
        """Generate test tone and measure output level"""
        t = (self._output_start_idx + np.arange(frames)) / self._output_stream.samplerate
        outdata[:] = 0.5 * np.sin(2 * np.pi * TEST_TONE_FREQUENCY * t).reshape(-1, 1)
        self._output_start_idx += frames
        
        rms = np.sqrt(np.mean(outdata[:] ** 2))
        current_db = 20 * math.log10(rms) if rms > 0 else MIN_DB
        
        self._output_smoothed_db = (SMOOTHING_FACTOR * self._output_smoothed_db) + ((1 - SMOOTHING_FACTOR) * current_db)
        if self._output_smoothed_db > self._output_peak_db:
            self._output_peak_db = self._output_smoothed_db
            self._output_peak_hold_time = time.time()
    
    def update_vu_meter(self):
        """Update the VU meter canvas (called periodically)"""
        if not hasattr(self, 'output_vu_canvas'):
            return
        
        # Decay peak hold
        if getattr(self, '_is_testing_output', False):
            if time.time() - getattr(self, '_output_peak_hold_time', time.time()) > PEAK_HOLD_DURATION:
                self._output_peak_db = max(self._output_smoothed_db, self._output_peak_db - 2)
        else:
            self._output_smoothed_db = max(MIN_DB, self._output_smoothed_db - 3)
            self._output_peak_db = max(self._output_smoothed_db, self._output_peak_db - 3)
        
        canvas = self.output_vu_canvas
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1:
            return
        
        canvas.delete("all")
        
        smoothed_db = getattr(self, '_output_smoothed_db', MIN_DB)
        peak_db = getattr(self, '_output_peak_db', MIN_DB)
        
        bar_len = int(((max(MIN_DB, min(smoothed_db, MAX_DB)) - MIN_DB) / (MAX_DB - MIN_DB)) * width)
        green_w = int(width * 0.7)
        yellow_w = int(width * 0.9)
        
        if bar_len > 0:
            canvas.create_rectangle(0, 0, min(bar_len, green_w), height, fill="#4CAF50", width=0)
        if bar_len > green_w:
            canvas.create_rectangle(green_w, 0, min(bar_len, yellow_w), height, fill="#FFC107", width=0)
        if bar_len > yellow_w:
            canvas.create_rectangle(yellow_w, 0, bar_len, height, fill="#F44336", width=0)
        
        peak_pos = int(((max(MIN_DB, min(peak_db, MAX_DB)) - MIN_DB) / (MAX_DB - MIN_DB)) * width)
        if peak_pos > 1:
            canvas.create_line(peak_pos, 0, peak_pos, height, fill="white", width=2)
        
        canvas.create_text(width - 10, height / 2, text=f"{smoothed_db:.1f} dB", anchor="e", fill="white")
        
        # Schedule next update
        self.after(50, self.update_vu_meter)
    
    # ==================== MUSIC TAB ====================
    def build_music_tab(self):
        """Build the Music Requests tab"""
        title = ctk.CTkLabel(self.music_tab, text="Music Requests", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10)
        
        # Scrollable frame
        scroll_frame = ctk.CTkScrollableFrame(self.music_tab)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # --- Download Section ---
        download_section = ctk.CTkLabel(scroll_frame, text="Download Song", font=ctk.CTkFont(size=16, weight="bold"))
        download_section.pack(anchor="w", pady=(5, 10))
        
        download_frame = ctk.CTkFrame(scroll_frame)
        download_frame.pack(fill="x", pady=5)
        
        self.music_download_entry = ctk.CTkEntry(download_frame, placeholder_text="Song name or YouTube URL")
        self.music_download_entry.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        
        download_btn = ctk.CTkButton(download_frame, text="Download", width=100, command=self.download_song)
        download_btn.pack(side="right", padx=10, pady=10)
        
        # Download status
        self.music_status_label = ctk.CTkLabel(scroll_frame, text="Status: Idle", font=ctk.CTkFont(size=13))
        self.music_status_label.pack(anchor="w", pady=5)
        
        # --- Queue Section ---
        queue_section = ctk.CTkLabel(scroll_frame, text="Song Queue", font=ctk.CTkFont(size=16, weight="bold"))
        queue_section.pack(anchor="w", pady=(15, 5))
        
        self.music_queue_textbox = ctk.CTkTextbox(scroll_frame, height=100)
        self.music_queue_textbox.pack(fill="x", pady=5)
        self.music_queue_textbox.configure(state="disabled")
        
        queue_btn_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        queue_btn_frame.pack(fill="x", pady=5)
        
        clear_queue_btn = ctk.CTkButton(queue_btn_frame, text="Clear Queue", width=120, command=self.clear_music_queue)
        clear_queue_btn.pack(side="left", padx=(0, 10))
        
        refresh_queue_btn = ctk.CTkButton(queue_btn_frame, text="Refresh", width=100, command=self.refresh_music_queue)
        refresh_queue_btn.pack(side="left")
        
        # --- Library Section ---
        library_section = ctk.CTkLabel(scroll_frame, text="Song Library (Karaoke)", font=ctk.CTkFont(size=16, weight="bold"))
        library_section.pack(anchor="w", pady=(15, 5))
        
        self.music_library_textbox = ctk.CTkTextbox(scroll_frame, height=150)
        self.music_library_textbox.pack(fill="x", pady=5)
        self.music_library_textbox.configure(state="disabled")
        
        library_btn_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        library_btn_frame.pack(fill="x", pady=5)
        
        refresh_library_btn = ctk.CTkButton(library_btn_frame, text="Refresh Library", width=140, command=self.refresh_music_library)
        refresh_library_btn.pack(side="left", padx=(0, 10))
        
        play_btn = ctk.CTkButton(library_btn_frame, text="Play Selected", width=120, command=self.play_selected_song)
        play_btn.pack(side="left")
        
        # --- Background Songs Section ---
        bg_section = ctk.CTkLabel(scroll_frame, text="Background Music", font=ctk.CTkFont(size=16, weight="bold"))
        bg_section.pack(anchor="w", pady=(15, 5))
        
        bg_frame = ctk.CTkFrame(scroll_frame)
        bg_frame.pack(fill="x", pady=5)
        
        self.bg_song_combo = ctk.CTkComboBox(bg_frame, values=["No background songs"], width=400)
        self.bg_song_combo.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        
        set_bg_btn = ctk.CTkButton(bg_frame, text="Set", width=60, command=self.set_background_song)
        set_bg_btn.pack(side="left", padx=(0, 5), pady=10)
        
        stop_bg_btn = ctk.CTkButton(bg_frame, text="Stop", width=60, command=self.stop_background_song)
        stop_bg_btn.pack(side="left", padx=(0, 10), pady=10)
        
        self.bg_status_label = ctk.CTkLabel(scroll_frame, text="Background: None", font=ctk.CTkFont(size=13))
        self.bg_status_label.pack(anchor="w", pady=5)
        
        # Load initial data
        self.refresh_music_library()
        self.refresh_music_queue()
        self.refresh_background_songs()
    
    def download_song(self):
        """Download a song from the entry field"""
        query = self.music_download_entry.get().strip()
        if not query:
            return
        
        try:
            response = httpx.post(f"{SERVER_URL}/api/music/download", json={"query": query}, timeout=5)
            if response.status_code == 200:
                self.music_status_label.configure(text=f"Status: Downloading '{query}'...")
                self.music_download_entry.delete(0, "end")
        except Exception as e:
            print(f"Download failed: {e}")
    
    def refresh_music_queue(self):
        """Refresh the song queue display"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/music/queue", timeout=5)
            if response.status_code == 200:
                data = response.json()
                queue = data.get('queue', [])
                
                self.music_queue_textbox.configure(state="normal")
                self.music_queue_textbox.delete("1.0", "end")
                if queue:
                    for i, song in enumerate(queue, 1):
                        self.music_queue_textbox.insert("end", f"{i}. {song}\n")
                else:
                    self.music_queue_textbox.insert("end", "Queue is empty")
                self.music_queue_textbox.configure(state="disabled")
        except Exception as e:
            print(f"Failed to refresh queue: {e}")
    
    def clear_music_queue(self):
        """Clear the song queue"""
        try:
            response = httpx.delete(f"{SERVER_URL}/api/music/queue", timeout=5)
            if response.status_code == 200:
                self.refresh_music_queue()
        except Exception as e:
            print(f"Failed to clear queue: {e}")
    
    def refresh_music_library(self):
        """Refresh the song library display"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/music/songs", timeout=5)
            if response.status_code == 200:
                data = response.json()
                songs = data.get('songs', [])
                
                self.music_library_textbox.configure(state="normal")
                self.music_library_textbox.delete("1.0", "end")
                if songs:
                    for song in songs:
                        self.music_library_textbox.insert("end", f"• {song}\n")
                else:
                    self.music_library_textbox.insert("end", "No songs in library")
                self.music_library_textbox.configure(state="disabled")
        except Exception as e:
            print(f"Failed to refresh library: {e}")
    
    def play_selected_song(self):
        """Play the selected song from the library"""
        try:
            # Get selected text from library textbox
            selected = self.music_library_textbox.get("sel.first", "sel.last").strip()
            if not selected:
                print("No song selected")
                return
            
            # Remove bullet point
            song_name = selected.lstrip("• ").strip()
            
            response = httpx.post(f"{SERVER_URL}/api/music/play", json={"song": song_name}, timeout=5)
            if response.status_code == 200:
                print(f"Playing: {song_name}")
        except Exception as e:
            print(f"Failed to play song: {e}")
    
    def refresh_background_songs(self):
        """Refresh the background songs list"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/music/background", timeout=5)
            if response.status_code == 200:
                data = response.json()
                songs = data.get('songs', [])
                current = data.get('current')
                
                if songs:
                    self.bg_song_combo.configure(values=songs)
                    if current and current in songs:
                        self.bg_song_combo.set(current)
                    else:
                        self.bg_song_combo.set(songs[0])
                else:
                    self.bg_song_combo.configure(values=["No background songs"])
                    self.bg_song_combo.set("No background songs")
                
                if current:
                    self.bg_status_label.configure(text=f"Background: {current}")
                else:
                    self.bg_status_label.configure(text="Background: None")
        except Exception as e:
            print(f"Failed to refresh background songs: {e}")
    
    def set_background_song(self):
        """Set the selected background song"""
        song_name = self.bg_song_combo.get()
        if not song_name or song_name == "No background songs":
            return
        
        try:
            response = httpx.post(f"{SERVER_URL}/api/music/background", json={"song": song_name}, timeout=5)
            if response.status_code == 200:
                self.bg_status_label.configure(text=f"Background: {song_name}")
                print(f"Background song set: {song_name}")
        except Exception as e:
            print(f"Failed to set background song: {e}")
    
    def stop_background_song(self):
        """Stop the background song"""
        try:
            response = httpx.post(f"{SERVER_URL}/api/music/background/stop", timeout=5)
            if response.status_code == 200:
                self.bg_status_label.configure(text="Background: None")
                print("Background song stopped")
        except Exception as e:
            print(f"Failed to stop background song: {e}")
    
    # ==================== NEUROSYNC TAB ====================
    def build_neurosync_tab(self):
        """Build the Neurosync tab with blendshape and OSC emote controls"""
        title = ctk.CTkLabel(self.neurosync_tab, text="Neurosync", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10)
        
        # --- Start/Stop buttons ---
        start_frame = ctk.CTkFrame(self.neurosync_tab)
        start_frame.pack(fill="x", padx=20, pady=10)
        
        start_label = ctk.CTkLabel(start_frame, text="Neurosync Services:", font=ctk.CTkFont(size=14, weight="bold"))
        start_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        btn_row = ctk.CTkFrame(start_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        
        self.start_localapi_btn = ctk.CTkButton(btn_row, text="Start Local API", width=150, command=self.start_neurosync_localapi)
        self.start_localapi_btn.pack(side="left", padx=5)
        
        self.start_watcher_btn = ctk.CTkButton(btn_row, text="Start Watcher To Face", width=180, command=self.start_neurosync_watcher)
        self.start_watcher_btn.pack(side="left", padx=5)
        
        # Scrollable frame
        scroll_frame = ctk.CTkScrollableFrame(self.neurosync_tab)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # --- Blendshape Controls ---
        bs_section = ctk.CTkLabel(scroll_frame, text="Blendshape Intensity Controls", font=ctk.CTkFont(size=16, weight="bold"))
        bs_section.pack(anchor="w", pady=(5, 5))
        
        bs_info = ctk.CTkLabel(scroll_frame, text="Adjust facial expression intensity (values > 1.0 will be clamped to 1.0)", font=ctk.CTkFont(size=12))
        bs_info.pack(anchor="w", pady=(0, 10))
        
        # Mouth scale
        mouth_label = ctk.CTkLabel(scroll_frame, text="Mouth Scale:", font=ctk.CTkFont(size=13))
        mouth_label.pack(anchor="w")
        self.mouth_scale_slider = ctk.CTkSlider(scroll_frame, from_=0.5, to=2.0, number_of_steps=30, command=self.update_mouth_label)
        self.mouth_scale_slider.pack(fill="x", pady=(0, 5))
        self.mouth_scale_value = ctk.CTkLabel(scroll_frame, text="1.0", font=ctk.CTkFont(size=12))
        self.mouth_scale_value.pack(anchor="e")
        
        # Eye scale
        eye_label = ctk.CTkLabel(scroll_frame, text="Eye Scale:", font=ctk.CTkFont(size=13))
        eye_label.pack(anchor="w", pady=(10, 0))
        self.eye_scale_slider = ctk.CTkSlider(scroll_frame, from_=0.5, to=2.0, number_of_steps=30, command=self.update_eye_label)
        self.eye_scale_slider.pack(fill="x", pady=(0, 5))
        self.eye_scale_value = ctk.CTkLabel(scroll_frame, text="1.0", font=ctk.CTkFont(size=12))
        self.eye_scale_value.pack(anchor="e")
        
        # Eyebrow scale
        eyebrow_label = ctk.CTkLabel(scroll_frame, text="Eyebrow Scale:", font=ctk.CTkFont(size=13))
        eyebrow_label.pack(anchor="w", pady=(10, 0))
        self.eyebrow_scale_slider = ctk.CTkSlider(scroll_frame, from_=0.3, to=1.5, number_of_steps=24, command=self.update_eyebrow_label)
        self.eyebrow_scale_slider.pack(fill="x", pady=(0, 5))
        self.eyebrow_scale_value = ctk.CTkLabel(scroll_frame, text="0.6", font=ctk.CTkFont(size=12))
        self.eyebrow_scale_value.pack(anchor="e")
        
        # EyeWide scale
        eyewide_label = ctk.CTkLabel(scroll_frame, text="EyeWide Scale:", font=ctk.CTkFont(size=13))
        eyewide_label.pack(anchor="w", pady=(10, 0))
        self.eyewide_scale_slider = ctk.CTkSlider(scroll_frame, from_=0.1, to=1.0, number_of_steps=18, command=self.update_eyewide_label)
        self.eyewide_scale_slider.pack(fill="x", pady=(0, 5))
        self.eyewide_scale_value = ctk.CTkLabel(scroll_frame, text="0.4", font=ctk.CTkFont(size=12))
        self.eyewide_scale_value.pack(anchor="e")
        
        # EyeSquint scale
        eyesquint_label = ctk.CTkLabel(scroll_frame, text="EyeSquint Scale:", font=ctk.CTkFont(size=13))
        eyesquint_label.pack(anchor="w", pady=(10, 0))
        self.eyesquint_scale_slider = ctk.CTkSlider(scroll_frame, from_=0.5, to=2.0, number_of_steps=30, command=self.update_eyesquint_label)
        self.eyesquint_scale_slider.pack(fill="x", pady=(0, 5))
        self.eyesquint_scale_value = ctk.CTkLabel(scroll_frame, text="1.0", font=ctk.CTkFont(size=12))
        self.eyesquint_scale_value.pack(anchor="e")
        
        save_bs_btn = ctk.CTkButton(scroll_frame, text="Save Blendshape Settings", command=self.save_blendshape_settings)
        save_bs_btn.pack(pady=15)
        
        # --- OSC Emote Controls ---
        emote_section = ctk.CTkLabel(scroll_frame, text="OSC Emote Controls", font=ctk.CTkFont(size=16, weight="bold"))
        emote_section.pack(anchor="w", pady=(15, 5))
        
        # OSC config
        osc_config_frame = ctk.CTkFrame(scroll_frame)
        osc_config_frame.pack(fill="x", pady=5)
        
        ip_label = ctk.CTkLabel(osc_config_frame, text="IP:", font=ctk.CTkFont(size=13))
        ip_label.pack(side="left", padx=(10, 5), pady=10)
        self.osc_ip_entry = ctk.CTkEntry(osc_config_frame, width=120)
        self.osc_ip_entry.pack(side="left", padx=5, pady=10)
        
        port_label = ctk.CTkLabel(osc_config_frame, text="Port:", font=ctk.CTkFont(size=13))
        port_label.pack(side="left", padx=(10, 5), pady=10)
        self.osc_port_entry = ctk.CTkEntry(osc_config_frame, width=70)
        self.osc_port_entry.pack(side="left", padx=5, pady=10)
        
        address_label = ctk.CTkLabel(osc_config_frame, text="Address:", font=ctk.CTkFont(size=13))
        address_label.pack(side="left", padx=(10, 5), pady=10)
        self.osc_address_entry = ctk.CTkEntry(osc_config_frame, width=140)
        self.osc_address_entry.pack(side="left", padx=5, pady=10)
        
        save_osc_btn = ctk.CTkButton(osc_config_frame, text="Save OSC", width=80, command=self.save_osc_settings)
        save_osc_btn.pack(side="left", padx=10, pady=10)
        
        # Quick emote buttons
        emote_label = ctk.CTkLabel(scroll_frame, text="Quick Emote Buttons:", font=ctk.CTkFont(size=13))
        emote_label.pack(anchor="w", pady=(10, 5))
        
        emote_names = ["Wave", "Hello", "Yes", "No", "Happy", "Sad", "Angry", "Surprised"]
        
        emote_row1 = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        emote_row1.pack(fill="x", pady=5)
        for emote in emote_names[:4]:
            btn = ctk.CTkButton(emote_row1, text=emote, width=80, command=lambda e=emote: self.send_test_emote(e))
            btn.pack(side="left", padx=5)
        
        emote_row2 = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        emote_row2.pack(fill="x", pady=5)
        for emote in emote_names[4:]:
            btn = ctk.CTkButton(emote_row2, text=emote, width=80, command=lambda e=emote: self.send_test_emote(e))
            btn.pack(side="left", padx=5)
        
        # Custom emote
        custom_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        custom_frame.pack(fill="x", pady=10)
        
        custom_label = ctk.CTkLabel(custom_frame, text="Custom Emote:", font=ctk.CTkFont(size=13))
        custom_label.pack(side="left", padx=(0, 5))
        self.custom_emote_entry = ctk.CTkEntry(custom_frame, width=200)
        self.custom_emote_entry.pack(side="left", padx=5)
        custom_btn = ctk.CTkButton(custom_frame, text="Send", width=60, command=self.send_custom_emote)
        custom_btn.pack(side="left", padx=5)
        
        self.emote_status_label = ctk.CTkLabel(scroll_frame, text="", font=ctk.CTkFont(size=12))
        self.emote_status_label.pack(anchor="w", pady=10)
        
        # Load current settings
        self.load_neurosync_settings()
    
    def update_mouth_label(self, value):
        self.mouth_scale_value.configure(text=f"{value:.2f}")
    
    def update_eye_label(self, value):
        self.eye_scale_value.configure(text=f"{value:.2f}")
    
    def update_eyebrow_label(self, value):
        self.eyebrow_scale_value.configure(text=f"{value:.2f}")
    
    def update_eyewide_label(self, value):
        self.eyewide_scale_value.configure(text=f"{value:.2f}")
    
    def update_eyesquint_label(self, value):
        self.eyesquint_scale_value.configure(text=f"{value:.2f}")
    
    def load_neurosync_settings(self):
        """Load Neurosync settings from server"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                neuro = data.get('neurosync', {})
                
                self.mouth_scale_slider.set(neuro.get('mouth_scale', 1.0))
                self.mouth_scale_value.configure(text=f"{neuro.get('mouth_scale', 1.0):.2f}")
                
                self.eye_scale_slider.set(neuro.get('eye_scale', 1.0))
                self.eye_scale_value.configure(text=f"{neuro.get('eye_scale', 1.0):.2f}")
                
                self.eyebrow_scale_slider.set(neuro.get('eyebrow_scale', 0.6))
                self.eyebrow_scale_value.configure(text=f"{neuro.get('eyebrow_scale', 0.6):.2f}")
                
                self.eyewide_scale_slider.set(neuro.get('eyewide_scale', 0.4))
                self.eyewide_scale_value.configure(text=f"{neuro.get('eyewide_scale', 0.4):.2f}")
                
                self.eyesquint_scale_slider.set(neuro.get('eyesquint_scale', 1.0))
                self.eyesquint_scale_value.configure(text=f"{neuro.get('eyesquint_scale', 1.0):.2f}")
                
                osc = neuro.get('osc', {})
                self.osc_ip_entry.delete(0, "end")
                self.osc_ip_entry.insert(0, osc.get('ip', '127.0.0.1'))
                self.osc_port_entry.delete(0, "end")
                self.osc_port_entry.insert(0, str(osc.get('port', 10000)))
                self.osc_address_entry.delete(0, "end")
                self.osc_address_entry.insert(0, osc.get('address', '/chat/message'))
        except Exception as e:
            print(f"Failed to load Neurosync settings: {e}")
    
    def save_blendshape_settings(self):
        """Save blendshape settings to server"""
        try:
            payload = {
                'blendshape_mouth_scale': round(self.mouth_scale_slider.get(), 2),
                'blendshape_eye_scale': round(self.eye_scale_slider.get(), 2),
                'blendshape_eyebrow_scale': round(self.eyebrow_scale_slider.get(), 2),
                'blendshape_eyewide_scale': round(self.eyewide_scale_slider.get(), 2),
                'blendshape_eyesquint_scale': round(self.eyesquint_scale_slider.get(), 2)
            }
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ Blendshape settings saved")
        except Exception as e:
            print(f"Failed to save blendshape settings: {e}")
    
    def save_osc_settings(self):
        """Save OSC settings to server"""
        try:
            payload = {
                'osc_ip': self.osc_ip_entry.get().strip(),
                'osc_port': int(self.osc_port_entry.get().strip()),
                'osc_address': self.osc_address_entry.get().strip()
            }
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                self.emote_status_label.configure(text="OSC settings saved!", text_color="green")
                print("✓ OSC settings saved")
        except Exception as e:
            self.emote_status_label.configure(text="Save failed!", text_color="red")
            print(f"Failed to save OSC settings: {e}")
    
    def send_test_emote(self, emote_name):
        """Send a test emote via OSC"""
        try:
            response = httpx.post(
                f"{SERVER_URL}/api/osc/emote",
                json={"emote": emote_name},
                timeout=5
            )
            if response.status_code == 200:
                self.emote_status_label.configure(text=f"✅ Sent emote: '{emote_name}'", text_color="green")
        except Exception as e:
            self.emote_status_label.configure(text=f"Failed: {e}", text_color="red")
    
    def send_custom_emote(self):
        """Send a custom emote"""
        emote = self.custom_emote_entry.get().strip()
        if emote:
            self.send_test_emote(emote)
    
    def start_neurosync_localapi(self):
        """Launch the Neurosync Local API batch file"""
        bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_scripts", "start_neurosync_localapi.bat")
        try:
            subprocess.Popen([bat_path], shell=True)
            print("✓ Started Neurosync Local API")
        except Exception as e:
            print(f"Failed to start Local API: {e}")
    
    def start_neurosync_watcher(self):
        """Launch the Neurosync Watcher To Face batch file"""
        bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_scripts", "start_neurosync_watcher_to_face.bat")
        try:
            subprocess.Popen([bat_path], shell=True)
            print("✓ Started Watcher To Face")
        except Exception as e:
            print(f"Failed to start Watcher To Face: {e}")
    
    # ==================== OSC TAB ====================
    def build_osc_tab(self):
        """Build the OSC tab for custom actions"""
        title = ctk.CTkLabel(self.osc_tab, text="OSC Custom Actions", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10)
        
        info = ctk.CTkLabel(
            self.osc_tab,
            text="Map chat phrases to OSC commands. E.g. 'turn off light 1' → address '/light/1' value 'off'",
            font=ctk.CTkFont(size=12)
        )
        info.pack(anchor="w", padx=20, pady=(0, 10))
        
        # Scrollable frame for actions list
        self.osc_actions_frame = ctk.CTkScrollableFrame(self.osc_tab)
        self.osc_actions_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Add action button
        add_btn = ctk.CTkButton(self.osc_tab, text="+ Add Action", command=self.add_osc_action_row)
        add_btn.pack(pady=10)
        
        # Save button
        save_btn = ctk.CTkButton(self.osc_tab, text="Save Actions", command=self.save_osc_actions)
        save_btn.pack(pady=10)
        
        # Load existing actions
        self.load_osc_actions()
    
    def add_osc_action_row(self, phrase="", address="", value=""):
        """Add a new OSC action row"""
        row = ctk.CTkFrame(self.osc_actions_frame)
        row.pack(fill="x", pady=5)
        
        phrase_entry = ctk.CTkEntry(row, placeholder_text="Phrase (e.g. turn off light 1)", width=250)
        phrase_entry.pack(side="left", padx=5, pady=5)
        phrase_entry.insert(0, phrase)
        
        address_entry = ctk.CTkEntry(row, placeholder_text="OSC Address (e.g. /light/1)", width=200)
        address_entry.pack(side="left", padx=5, pady=5)
        address_entry.insert(0, address)
        
        value_entry = ctk.CTkEntry(row, placeholder_text="Value (e.g. off)", width=120)
        value_entry.pack(side="left", padx=5, pady=5)
        value_entry.insert(0, value)
        
        delete_btn = ctk.CTkButton(row, text="✕", width=30, fg_color="red", hover_color="darkred", command=lambda: row.destroy())
        delete_btn.pack(side="left", padx=5, pady=5)
    
    def load_osc_actions(self):
        """Load existing OSC actions from server"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/osc/actions", timeout=5)
            if response.status_code == 200:
                data = response.json()
                actions = data.get('actions', [])
                for action in actions:
                    self.add_osc_action_row(
                        phrase=action.get('phrase', ''),
                        address=action.get('address', ''),
                        value=action.get('value', '')
                    )
        except Exception as e:
            print(f"Failed to load OSC actions: {e}")
    
    def save_osc_actions(self):
        """Save OSC actions to server"""
        actions = []
        for row in self.osc_actions_frame.winfo_children():
            entries = [w for w in row.winfo_children() if isinstance(w, ctk.CTkEntry)]
            if len(entries) >= 3:
                phrase = entries[0].get().strip()
                address = entries[1].get().strip()
                value = entries[2].get().strip()
                if phrase and address:
                    actions.append({
                        'phrase': phrase,
                        'address': address,
                        'value': value
                    })
        
        try:
            response = httpx.post(f"{SERVER_URL}/api/osc/actions", json={"actions": actions}, timeout=5)
            if response.status_code == 200:
                print(f"✓ Saved {len(actions)} OSC actions")
        except Exception as e:
            print(f"Failed to save OSC actions: {e}")
    
    # ==================== SSN TAB ====================
    def build_ssn_tab(self):
        """Build the Social Stream Ninja tab"""
        title = ctk.CTkLabel(self.ssn_tab, text="Social Stream Ninja", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=20)
        
        # Connection status
        self.ssn_status = ctk.CTkLabel(self.ssn_tab, text="Status: Checking...", font=ctk.CTkFont(size=16))
        self.ssn_status.pack(anchor="w", padx=20, pady=5)
        
        # API URL
        url_label = ctk.CTkLabel(self.ssn_tab, text="API URL:", font=ctk.CTkFont(size=14))
        url_label.pack(anchor="w", padx=20, pady=(20, 0))
        
        self.ssn_url_entry = ctk.CTkEntry(self.ssn_tab)
        self.ssn_url_entry.pack(fill="x", padx=20, pady=10)
        
        # Session ID
        session_label = ctk.CTkLabel(self.ssn_tab, text="Session ID:", font=ctk.CTkFont(size=14))
        session_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        self.ssn_session_entry = ctk.CTkEntry(self.ssn_tab)
        self.ssn_session_entry.pack(fill="x", padx=20, pady=10)
        
        # Target platforms
        targets_label = ctk.CTkLabel(self.ssn_tab, text="Target Platforms:", font=ctk.CTkFont(size=14))
        targets_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        targets_frame = ctk.CTkFrame(self.ssn_tab)
        targets_frame.pack(fill="x", padx=20, pady=10)
        
        self.discord_var = ctk.BooleanVar(value=True)
        self.twitch_var = ctk.BooleanVar(value=True)
        self.youtube_var = ctk.BooleanVar(value=True)
        
        discord_check = ctk.CTkCheckBox(targets_frame, text="Discord", variable=self.discord_var)
        discord_check.pack(side="left", padx=20, pady=10)
        
        twitch_check = ctk.CTkCheckBox(targets_frame, text="Twitch", variable=self.twitch_var)
        twitch_check.pack(side="left", padx=20, pady=10)
        
        youtube_check = ctk.CTkCheckBox(targets_frame, text="YouTube", variable=self.youtube_var)
        youtube_check.pack(side="left", padx=20, pady=10)
        
        # Save button
        save_btn = ctk.CTkButton(self.ssn_tab, text="Save SSN Settings", command=self.save_ssn_settings)
        save_btn.pack(pady=20)
        
        # Load current settings
        self.load_ssn_settings()
    
    # ==================== STATUS POLLING ====================
    def poll_status(self):
        """Poll server status every 5 seconds"""
        while self.polling:
            self.refresh_status()
            time.sleep(5)
    
    def refresh_status(self):
        """Fetch and update status indicators"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                # LLM status
                if data['llm']['enabled']:
                    self.llm_status.configure(text=f"Status: ✓ Connected ({data['llm']['model']})", text_color="green")
                    self.status_llm.configure(text=f"LLM: ✓ Connected ({data['llm']['model']})", text_color="green")
                else:
                    self.llm_status.configure(text="Status: ✗ Disconnected", text_color="red")
                    self.status_llm.configure(text="LLM: ✗ Disconnected", text_color="red")
                
                # Memory status
                if data['cognee']['enabled']:
                    self.memory_status.configure(text="Status: ✓ Connected", text_color="green")
                    self.status_cognee.configure(text="Cognee: ✓ Connected", text_color="green")
                else:
                    self.memory_status.configure(text="Status: ✗ Disconnected", text_color="red")
                    self.status_cognee.configure(text="Cognee: ✗ Disconnected", text_color="red")
                
                # SSN status
                if data['ssn']['enabled']:
                    self.ssn_status.configure(text="Status: ✓ Connected", text_color="green")
                    self.status_ssn.configure(text="SSN: ✓ Connected", text_color="green")
                else:
                    self.ssn_status.configure(text="Status: ✗ Disconnected", text_color="red")
                    self.status_ssn.configure(text="SSN: ✗ Disconnected", text_color="red")
                
                # TTS status
                if data.get('tts', {}).get('enabled'):
                    self.tts_status.configure(text="Status: ✓ Connected", text_color="green")
                    self.status_tts.configure(text="TTS: ✓ Connected", text_color="green")
                else:
                    self.tts_status.configure(text="Status: ✗ Disconnected", text_color="red")
                    self.status_tts.configure(text="TTS: ✗ Disconnected", text_color="red")
                
                # Music status
                self.status_music.configure(text="Music: ✓ Ready", text_color="green")
        except Exception as e:
            self.llm_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.memory_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.ssn_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.tts_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.status_llm.configure(text="LLM: ✗ Server unreachable", text_color="red")
            self.status_ssn.configure(text="SSN: ✗ Server unreachable", text_color="red")
            self.status_cognee.configure(text="Cognee: ✗ Server unreachable", text_color="red")
            self.status_tts.configure(text="TTS: ✗ Server unreachable", text_color="red")
            self.status_music.configure(text="Music: ✗ Server unreachable", text_color="red")
    
    # ==================== LLM SETTINGS ====================
    def load_llm_settings(self):
        """Load current LLM settings from server"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/settings", timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                self.prompt_textbox.delete("1.0", "end")
                self.prompt_textbox.insert("1.0", data['system_prompt'])
                
                self.wake_entry.delete(0, "end")
                self.wake_entry.insert(0, ", ".join(data['wake_words']))
                
                self.model_entry.delete(0, "end")
                self.model_entry.insert(0, data['ollama_model'])
        except Exception as e:
            print(f"Failed to load settings: {e}")
    
    def save_llm_settings(self):
        """Save LLM settings to server"""
        try:
            wake_words = [w.strip() for w in self.wake_entry.get().split(",") if w.strip()]
            
            payload = {
                'system_prompt': self.prompt_textbox.get("1.0", "end").strip(),
                'wake_words': wake_words,
                'ollama_model': self.model_entry.get().strip()
            }
            
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ LLM settings saved")
        except Exception as e:
            print(f"Failed to save settings: {e}")
    
    # ==================== MEMORY ====================
    def test_recall(self):
        """Test memory recall with a query"""
        query = self.recall_entry.get().strip()
        if not query:
            return
        
        try:
            response = httpx.post(
                f"{SERVER_URL}/api/recall",
                json={"query": query, "top_k": 5},
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                
                self.recall_results.configure(state="normal")
                self.recall_results.delete("1.0", "end")
                if results:
                    for result in results:
                        self.recall_results.insert("end", f"• {result}\n\n")
                else:
                    self.recall_results.insert("end", "No memories found.")
                self.recall_results.configure(state="disabled")
        except Exception as e:
            self.recall_results.configure(state="normal")
            self.recall_results.delete("1.0", "end")
            self.recall_results.insert("end", f"Error: {e}")
            self.recall_results.configure(state="disabled")
    
    def load_cognee_settings(self):
        """Load Cognee settings from Cognee server"""
        try:
            response = httpx.get(f"{COGNEE_SERVER_URL}/settings", timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                self.cognee_llm_model.delete(0, "end")
                self.cognee_llm_model.insert(0, data.get('llm_model', ''))
                
                self.cognee_llm_endpoint.delete(0, "end")
                self.cognee_llm_endpoint.insert(0, data.get('llm_endpoint', ''))
                
                self.cognee_emb_model.delete(0, "end")
                self.cognee_emb_model.insert(0, data.get('embedding_model', ''))
                
                self.cognee_emb_endpoint.delete(0, "end")
                self.cognee_emb_endpoint.insert(0, data.get('embedding_endpoint', ''))
                
                self.cognee_emb_dim.delete(0, "end")
                self.cognee_emb_dim.insert(0, data.get('embedding_dimensions', ''))
                
                self.cognee_data_dir.delete(0, "end")
                self.cognee_data_dir.insert(0, data.get('data_root_directory', ''))
                
                self.cognee_system_dir.delete(0, "end")
                self.cognee_system_dir.insert(0, data.get('system_root_directory', ''))
                
                self.cognee_caching.set(data.get('caching', 'true').lower() == 'true')
                self.cognee_feedback.set(data.get('auto_feedback', 'false').lower() == 'true')
        except Exception as e:
            print(f"Failed to load Cognee settings: {e}")
    
    def save_cognee_settings(self):
        """Save Cognee settings to Cognee server"""
        try:
            payload = {
                'llm_model': self.cognee_llm_model.get().strip(),
                'llm_endpoint': self.cognee_llm_endpoint.get().strip(),
                'embedding_model': self.cognee_emb_model.get().strip(),
                'embedding_endpoint': self.cognee_emb_endpoint.get().strip(),
                'embedding_dimensions': self.cognee_emb_dim.get().strip(),
                'caching': 'true' if self.cognee_caching.get() else 'false',
                'auto_feedback': 'true' if self.cognee_feedback.get() else 'false'
            }
            
            response = httpx.post(f"{COGNEE_SERVER_URL}/settings", json=payload, timeout=10)
            if response.status_code == 200:
                print("✓ Cognee settings saved (restart Cognee server to apply)")
        except Exception as e:
            print(f"Failed to save Cognee settings: {e}")
    
    # ==================== SSN SETTINGS ====================
    def load_ssn_settings(self):
        """Load current SSN settings from server"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                ssn = data.get('ssn', {})
                
                self.ssn_url_entry.delete(0, "end")
                self.ssn_url_entry.insert(0, ssn.get('api_url', ''))
                
                self.ssn_session_entry.delete(0, "end")
                self.ssn_session_entry.insert(0, ssn.get('session_id', ''))
        except Exception as e:
            print(f"Failed to load SSN settings: {e}")
    
    def save_ssn_settings(self):
        """Save SSN settings to server"""
        try:
            targets = []
            if self.discord_var.get():
                targets.append('discord')
            if self.twitch_var.get():
                targets.append('twitch')
            if self.youtube_var.get():
                targets.append('youtube')
            
            payload = {
                'ssn_session_id': self.ssn_session_entry.get().strip(),
                'ssn_targets': targets
            }
            
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ SSN settings saved")
        except Exception as e:
            print(f"Failed to save SSN settings: {e}")
    
    # ==================== TTS SETTINGS ====================
    def load_tts_settings(self):
        """Load current TTS settings from server"""
        try:
            response = httpx.get(f"{SERVER_URL}/api/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                tts = data.get('tts', {})
                
                self.tts_url_entry.delete(0, "end")
                self.tts_url_entry.insert(0, tts.get('tts_url', ''))
                
                self.tts_enabled_var.set(tts.get('enabled', False))
                
                self.audio_player_var.set(tts.get('audio_player_enabled', True))
                
                # Load StyleTTS2 parameters from main server config
                self.diffusion_steps_slider.set(tts.get('diffusion_steps', 20))
                self.diffusion_value_label.configure(text=str(tts.get('diffusion_steps', 20)))
                
                self.embedding_scale_slider.set(tts.get('embedding_scale', 1.0))
                self.embedding_value_label.configure(text=f"{tts.get('embedding_scale', 1.0):.1f}")
                
                self.alpha_slider.set(tts.get('alpha', 0.3))
                self.alpha_value_label.configure(text=f"{tts.get('alpha', 0.3):.2f}")
                
                self.beta_slider.set(tts.get('beta', 0.7))
                self.beta_value_label.configure(text=f"{tts.get('beta', 0.7):.2f}")
                
                self.reference_voice_entry.delete(0, "end")
                self.reference_voice_entry.insert(0, tts.get('reference_voice', ''))
        except Exception as e:
            print(f"Failed to load TTS settings: {e}")
    
    def save_tts_settings(self):
        """Save TTS settings to server"""
        try:
            payload = {
                'tts_enabled': self.tts_enabled_var.get(),
                'tts_url': self.tts_url_entry.get().strip(),
                'tts_diffusion_steps': int(self.diffusion_steps_slider.get()),
                'tts_embedding_scale': round(self.embedding_scale_slider.get(), 1),
                'tts_alpha': round(self.alpha_slider.get(), 2),
                'tts_beta': round(self.beta_slider.get(), 2),
                'tts_reference_voice': self.reference_voice_entry.get().strip(),
                'audio_player_enabled': self.audio_player_var.get()
            }
            
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ TTS settings saved")
        except Exception as e:
            print(f"Failed to save TTS settings: {e}")
        
        # Also save StyleTTS2 parameters to StyleTTS2 server (if running)
        try:
            tts_url = self.tts_url_entry.get().strip()
            base_url = tts_url.replace('/tts', '')
            payload = {
                'diffusion_steps': int(self.diffusion_steps_slider.get()),
                'embedding_scale': round(self.embedding_scale_slider.get(), 1),
                'alpha': round(self.alpha_slider.get(), 2),
                'beta': round(self.beta_slider.get(), 2),
                'reference_voice': self.reference_voice_entry.get().strip()
            }
            
            response = httpx.post(f"{base_url}/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ StyleTTS2 parameters saved")
        except Exception as e:
            print(f"StyleTTS2 server not running, params saved to main config only: {e}")
    
    def test_tts(self):
        """Test TTS with entered text"""
        text = self.tts_test_entry.get().strip()
        if not text:
            return
        
        try:
            response = httpx.post(
                f"{SERVER_URL}/api/tts",
                json={"text": text},
                timeout=30
            )
            if response.status_code == 200:
                print("✓ TTS test sent")
        except Exception as e:
            print(f"TTS test failed: {e}")
    
    def on_close(self):
        """Clean up on window close"""
        self.polling = False
        if getattr(self, '_is_testing_output', False):
            self.stop_output_test()
        self.destroy()


if __name__ == "__main__":
    app = ControlPanel()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
