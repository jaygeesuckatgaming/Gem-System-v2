"""
Browser-Use Client
Lets Gem open a real (visible) browser and perform tasks driven by an LLM,
so the window can be captured by OBS for the livestream.

The driving LLM is configurable:
  - "ollama"  -> browser_use.ChatOllama (default, local)
  - "openai"  -> browser_use.ChatOpenAI (needs BROWSER_OPENAI_API_KEY)

browser_use is imported lazily so the rest of the system still runs if it
isn't installed. A single BrowserSession is created once and reused so the
same visible window persists across tasks.
"""

import asyncio
import logging
import os
import re

# browser_use's __init__ calls setup_logging() on import, which wipes the
# root logger's handlers and installs its own (spamming access logs). The
# BROWSER_USE_SETUP_LOGGING=false env var makes it skip that entirely.
os.environ.setdefault('BROWSER_USE_SETUP_LOGGING', 'false')


def _import_browser_use():
    """Import browser_use without letting it clobber the root logging config."""
    import browser_use  # noqa: F401
    return browser_use


def _strip_fences(text: str) -> str:
    """Remove ```json / ``` markdown fences a model may wrap around its output."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    return text.strip()


class FenceStrippingChatOllama:
    """Wraps browser_use.ChatOllama and strips markdown fences from output.

    Some local models (e.g. gemma4) wrap their structured JSON in ```json
    fences even when Ollama is asked for a JSON schema, which makes
    pydantic's model_validate_json fail. This wrapper mirrors ChatOllama's
    ainvoke but strips fences before validation.
    """

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    async def ainvoke(self, messages, output_format=None, **kwargs):
        from browser_use.llm.base import ChatInvokeCompletion
        from browser_use.llm.ollama.chat import OllamaMessageSerializer, ModelProviderError

        try:
            client = self._wrapped.get_client()
            ollama_messages = OllamaMessageSerializer.serialize_messages(messages)

            if output_format is None:
                response = await client.chat(
                    model=self._wrapped.model,
                    messages=ollama_messages,
                    options=self._wrapped.ollama_options,
                )
                return ChatInvokeCompletion(completion=response.message.content or '', usage=None)

            schema = output_format.model_json_schema()
            response = await client.chat(
                model=self._wrapped.model,
                messages=ollama_messages,
                format=schema,
                options=self._wrapped.ollama_options,
            )
            completion = _strip_fences(response.message.content or '')
            completion = output_format.model_validate_json(completion)
            return ChatInvokeCompletion(completion=completion, usage=None)
        except Exception as e:
            raise ModelProviderError(message=str(e), model=self._wrapped.model) from e


class BrowserClient:
    def __init__(self, provider: str = "ollama",
                 ollama_model: str = "gemma4:31b-cloud",
                 ollama_host: str = "http://localhost:11434",
                 openai_model: str = "gpt-4o",
                 openai_api_key: str = "",
                 headless: bool = False,
                 viewport_width: int = 1280,
                 viewport_height: int = 720,
                 window_x: int = 0,
                 window_y: int = 0):
        self.provider = provider.lower()
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host
        self.openai_model = openai_model
        self.openai_api_key = openai_api_key
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.window_x = window_x
        self.window_y = window_y
        self.enabled = False
        self._session = None
        self._llm = None

    def _make_llm(self):
        """Build the browser_use LLM driving the agent."""
        from browser_use import ChatOllama, ChatOpenAI

        if self.provider == "openai":
            kwargs = {"model": self.openai_model}
            if self.openai_api_key:
                kwargs["api_key"] = self.openai_api_key
            return ChatOpenAI(**kwargs)

        base = ChatOllama(model=self.ollama_model, host=self.ollama_host)
        return FenceStrippingChatOllama(base)

    def _make_session(self):
        from browser_use import BrowserSession, BrowserProfile
        from browser_use.browser.profile import ViewportSize

        # A fixed user_data_dir keeps the same browser process/profile across
        # tasks (persistent cookies, logins, and a single stable window).
        profile_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "browser_profile",
        )

        profile = BrowserProfile(
            headless=self.headless,
            disable_security=True,
            keep_alive=True,  # don't kill the browser when an agent finishes
            user_data_dir=profile_dir,
            viewport=ViewportSize(width=self.viewport_width, height=self.viewport_height),
            # An explicit window_size forces Chrome to use --window-size instead
            # of --start-maximized (which would ignore --window-position and snap
            # to the primary display).
            window_size=ViewportSize(width=self.viewport_width, height=self.viewport_height),
            # window_position defaults to ViewportSize(0,0) and its injected
            # --window-position=0,0 would override our raw arg (dedup keeps the
            # last). Set it to None so only our raw arg below takes effect.
            window_position=None,
            # window_position uses ViewportSize (ge=0), so it can't express a
            # negative offset for a monitor left of the primary. Use the raw
            # Chrome CLI arg instead, which accepts any coordinate.
            args=[f"--window-position={self.window_x},{self.window_y}"],
        )
        return BrowserSession(browser_profile=profile)

    def check_connection(self) -> bool:
        """Probe that browser_use + a driving LLM are importable."""
        try:
            _import_browser_use()
            self._llm = self._make_llm()
            self.enabled = True
            print(f"[OK] Browser-Use connected (provider={self.provider})")
            return True
        except Exception as e:
            print(f"[X] Browser-Use not available: {e}")
            self.enabled = False
            return False

    def _get_session(self):
        if self._session is None:
            self._session = self._make_session()
        return self._session

    async def run_task(self, task: str) -> str:
        """Run a browsing task and return the final text result."""
        if not self.enabled:
            return "Browser-Use is not available."

        from browser_use import Agent

        llm = self._llm or self._make_llm()
        session = self._get_session()

        try:
            agent = Agent(task=task, llm=llm, browser_session=session)
            result = await agent.run()
        except Exception as e:
            print(f"Browser task failed: {e}")
            return f"Browser task failed: {e}"

        # In browser_use 0.11.x, final_result() is a method on AgentHistoryList.
        try:
            final = result.final_result()
        except Exception:
            final = None

        if final:
            return str(final)

        return "Task completed."

    async def close(self):
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception:
                pass
            self._session = None
