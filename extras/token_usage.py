import tkinter as tk
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(PROJECT_ROOT, "token_usage_state.json")


class TokenUsageOverlay(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Token Usage Overlay")
        self.geometry("420x160+100+220")

        # Always on top so OBS window capture can grab it
        self.attributes('-topmost', True)

        bg_color = "#1a1a1a"
        accent = "#00aaff"
        text_color = "#ffffff"
        dim = "#888888"

        self.configure(bg=bg_color)

        # Title
        title = tk.Label(
            self, text="LLM TOKENS", font=("Consolas", 14, "bold"),
            fg=accent, bg=bg_color
        )
        title.pack(pady=(10, 0))

        # Main token line: "IN 1,234 | OUT 567"
        self.main_label = tk.Label(
            self, text="IN 0 | OUT 0",
            font=("Consolas", 22, "bold"),
            fg=text_color, bg=bg_color
        )
        self.main_label.pack(pady=(4, 0))

        # Totals line
        self.total_label = tk.Label(
            self, text="Total: 0 in / 0 out",
            font=("Consolas", 12),
            fg=dim, bg=bg_color
        )
        self.total_label.pack(pady=(2, 0))

        # Model line
        self.model_label = tk.Label(
            self, text="",
            font=("Consolas", 10),
            fg=dim, bg=bg_color
        )
        self.model_label.pack(pady=(0, 8))

        self.is_moveable = False

        self.check_state()

    def toggle_moveable(self):
        """Toggle whether the window can be dragged (click-through for OBS)."""
        self.is_moveable = not self.is_moveable
        if self.is_moveable:
            self.attributes('-transparentcolor', self['bg'])
        else:
            self.attributes('-transparentcolor', '')

    def check_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                last_in = data.get('last_prompt_tokens', 0)
                last_out = data.get('last_eval_tokens', 0)
                total_in = data.get('total_prompt_tokens', 0)
                total_out = data.get('total_eval_tokens', 0)
                model = data.get('model', '')

                self.main_label.config(text=f"IN {last_in:,} | OUT {last_out:,}")
                self.total_label.config(text=f"Total: {total_in:,} in / {total_out:,} out")
                if model:
                    self.model_label.config(text=model)
        except Exception as e:
            print(f"Token overlay error: {e}")

        self.after(1000, self.check_state)

    def start_drag(self, event):
        if not self.is_moveable:
            return
        self.x = event.x
        self.y = event.y

    def do_drag(self, event):
        if not self.is_moveable:
            return
        dx = event.x - self.x
        dy = event.y - self.y
        self.geometry(f"+{self.winfo_x() + dx}+{self.winfo_y() + dy}")


if __name__ == "__main__":
    app = TokenUsageOverlay()
    app.bind("<ButtonPress-1>", app.start_drag)
    app.bind("<B1-Motion>", app.do_drag)
    app.mainloop()
