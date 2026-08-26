"""
Gem-System v2 - Control Panel GUI
Uses customtkinter for a modern look
Communicates with main.py via HTTP API
"""

import customtkinter as ctk
import httpx
import threading
import time

# Server URL
SERVER_URL = "http://127.0.0.1:5000"
COGNEE_SERVER_URL = "http://127.0.0.1:8011"

# Appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ControlPanel(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Gem-System v2 - Control Panel")
        self.geometry("900x650")
        
        # Create tab view
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Add tabs
        self.llm_tab = self.tabview.add("LLM")
        self.memory_tab = self.tabview.add("Memory")
        self.tts_tab = self.tabview.add("TTS")
        self.ssn_tab = self.tabview.add("Social Stream Ninja")
        
        self.build_llm_tab()
        self.build_memory_tab()
        self.build_tts_tab()
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
        
        # TTS URL
        url_label = ctk.CTkLabel(self.tts_tab, text="TTS Server URL:", font=ctk.CTkFont(size=14))
        url_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        self.tts_url_entry = ctk.CTkEntry(self.tts_tab)
        self.tts_url_entry.pack(fill="x", padx=20, pady=10)
        
        # Test TTS section
        test_label = ctk.CTkLabel(self.tts_tab, text="Test TTS:", font=ctk.CTkFont(size=14))
        test_label.pack(anchor="w", padx=20, pady=(20, 0))
        
        test_frame = ctk.CTkFrame(self.tts_tab)
        test_frame.pack(fill="x", padx=20, pady=10)
        
        self.tts_test_entry = ctk.CTkEntry(test_frame, placeholder_text="Enter text to speak")
        self.tts_test_entry.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        
        test_btn = ctk.CTkButton(test_frame, text="Speak", width=100, command=self.test_tts)
        test_btn.pack(side="right", padx=10, pady=10)
        
        # Save button
        save_btn = ctk.CTkButton(self.tts_tab, text="Save TTS Settings", command=self.save_tts_settings)
        save_btn.pack(pady=20)
        
        # Load current settings
        self.load_tts_settings()
    
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
        except Exception as e:
            print(f"Failed to load TTS settings: {e}")
    
    def save_tts_settings(self):
        """Save TTS settings to server"""
        try:
            payload = {
                'tts_enabled': self.tts_enabled_var.get(),
                'tts_url': self.tts_url_entry.get().strip()
            }
            
            response = httpx.post(f"{SERVER_URL}/api/settings", json=payload, timeout=5)
            if response.status_code == 200:
                print("✓ TTS settings saved")
        except Exception as e:
            print(f"Failed to save TTS settings: {e}")
    
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
        self.destroy()


if __name__ == "__main__":
    app = ControlPanel()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
