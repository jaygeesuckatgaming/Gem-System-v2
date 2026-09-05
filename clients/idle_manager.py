"""
Idle Manager
Tracks chat activity and triggers autonomous "idle monologues" when the chat
goes quiet, so the AI VTuber stays lively. Sends OSC state/action messages to
Unreal Engine to drive facial expressions and animations.
"""

import asyncio
import random
import time
from typing import Optional, Callable, Awaitable


class IdleManager:
    def __init__(
        self,
        inactivity_limit: float = 60.0,
        cooldown: float = 180.0,
        enabled: bool = True,
        osc_state_address: str = "/vtuber/state",
        osc_action_address: str = "/vtuber/action",
        osc_bored_value: str = "bored",
        osc_normal_value: str = "normal",
        osc_talk_value: str = "talk_thoughtful",
        osc_idle_value: str = "idle",
        topics: Optional[list] = None,
    ):
        self.inactivity_limit = inactivity_limit
        self.cooldown = cooldown
        self.enabled = enabled

        self.osc_state_address = osc_state_address
        self.osc_action_address = osc_action_address
        self.osc_bored_value = osc_bored_value
        self.osc_normal_value = osc_normal_value
        self.osc_talk_value = osc_talk_value
        self.osc_idle_value = osc_idle_value

        self.topics = topics or [
            "Complain about how weird humans are.",
            "Talk about a random shower thought or philosophical paradox.",
            "Talk about what you were doing before the stream started.",
            "Bring up a random conspiracy theory about video game NPCs.",
            "Ask a random rhetorical question to the silent chat.",
        ]

        self.last_message_time = time.time()
        self.last_idle_time = 0.0
        self.is_idle = False
        self.is_speaking = False
        self._interrupt = False

        # Callbacks (set by main.py)
        self.on_monologue: Optional[Callable[[str], Awaitable[None]]] = None
        self.send_osc: Optional[Callable[[str, str], None]] = None
        self.on_interrupt: Optional[Callable[[], None]] = None
        self.is_speaking_check: Optional[Callable[[], bool]] = None

    def update_activity(self):
        """Call this every time a real chat message comes in."""
        self.last_message_time = time.time()
        if self.is_idle:
            self.exit_idle_state()
        # If a monologue is currently playing, interrupt it
        if self.is_speaking:
            self.interrupt()

    def interrupt(self):
        """Interrupt the currently playing monologue."""
        if not self.is_speaking:
            return
        print("[IdleManager] Interrupting monologue (chat activity detected).")
        self._interrupt = True
        if self.on_interrupt:
            try:
                self.on_interrupt()
            except Exception as e:
                print(f"[IdleManager] Interrupt callback error: {e}")

    def _osc(self, address: str, value: str):
        if self.send_osc:
            try:
                self.send_osc(address, value)
            except Exception as e:
                print(f"[IdleManager] OSC send failed: {e}")

    def enter_idle_state(self):
        self.is_idle = True
        print("[IdleManager] Chat is slow. Entering idle/daydream state.")
        self._osc(self.osc_state_address, self.osc_bored_value)

    def exit_idle_state(self):
        self.is_idle = False
        print("[IdleManager] Chat resumed. Exiting idle state.")
        self._osc(self.osc_state_address, self.osc_normal_value)
        self.last_idle_time = time.time()

    def pick_topic(self) -> str:
        return random.choice(self.topics)

    async def trigger_monologue(self):
        """Generate and speak an idle monologue (called by the monitor loop)."""
        if not self.on_monologue:
            print("[IdleManager] No monologue callback set, skipping.")
            return

        topic = self.pick_topic()
        print(f"[IdleManager] Triggering monologue. Topic: {topic}")

        self.is_speaking = True
        self._interrupt = False

        # Tell Unreal to play a thinking/talking animation
        self._osc(self.osc_action_address, self.osc_talk_value)

        try:
            await self.on_monologue(topic)
        except Exception as e:
            print(f"[IdleManager] Monologue callback error: {e}")

        # Return to regular idle animation once done speaking
        self._osc(self.osc_action_address, self.osc_idle_value)

        # Reset timers so the countdown starts fresh
        self.last_message_time = time.time()
        self.last_idle_time = time.time()
        self.is_idle = False
        self.is_speaking = False
        self._interrupt = False

    async def monitor_loop(self):
        """Background loop that checks for idle conditions every 5 seconds."""
        while True:
            await asyncio.sleep(5)

            if not self.enabled:
                continue

            # If the VTuber is currently speaking (monologue or otherwise),
            # keep resetting the inactivity timer so monologues don't pile up.
            if self.is_speaking_check and self.is_speaking_check():
                self.last_message_time = time.time()
                continue

            current_time = time.time()
            time_since_chat = current_time - self.last_message_time
            time_since_last_idle = current_time - self.last_idle_time

            if (
                not self.is_idle
                and time_since_chat > self.inactivity_limit
                and time_since_last_idle > self.cooldown
            ):
                self.enter_idle_state()
                await self.trigger_monologue()
