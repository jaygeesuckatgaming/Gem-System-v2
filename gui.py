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
        self.llm_tab = self.tabview.add("LLM")
        self.memory_tab = self.tabview.add("Memory")
        self.tts_tab = self.tabview.add("TTS")
        self.audio_tab = self.tabview.add("Audio")
        self.ssn_tab = self.tabview.add("Social Stream Ninja")
        
        self.build_llm_tab()
        self.build_memory_tab()
        self.build_tts_tab()
        self.build_audio_tab()
        self.build_ssn_tab()
        
        # Start status polling
        self.polling = True
        self.poll_thread = threading.Thread(target=self.poll_status, daemon=True)
        self.poll_thread.start()
    
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
                
                # Restore current selection
                current = self._current_device
                if current and current in device_names:
                    self.audio_device_combo.set(current)
                else:
                    self.audio_device_combo.set("System Default")
        except Exception as e:
            print(f"Failed to fetch audio devices: {e}")
    
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
                else:
                    self.llm_status.configure(text="Status: ✗ Disconnected", text_color="red")
                
                # Memory status
                if data['cognee']['enabled']:
                    self.memory_status.configure(text="Status: ✓ Connected", text_color="green")
                else:
                    self.memory_status.configure(text="Status: ✗ Disconnected", text_color="red")
                
                # SSN status
                if data['ssn']['enabled']:
                    self.ssn_status.configure(text="Status: ✓ Connected", text_color="green")
                else:
                    self.ssn_status.configure(text="Status: ✗ Disconnected", text_color="red")
                
                # TTS status
                if data.get('tts', {}).get('enabled'):
                    self.tts_status.configure(text="Status: ✓ Connected", text_color="green")
                else:
                    self.tts_status.configure(text="Status: ✗ Disconnected", text_color="red")
        except Exception as e:
            self.llm_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.memory_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.ssn_status.configure(text="Status: ✗ Server unreachable", text_color="red")
            self.tts_status.configure(text="Status: ✗ Server unreachable", text_color="red")
    
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
