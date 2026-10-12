"""Calls a language model served from AMD's Token Factory (an OpenAI-compatible API).

AMD_TOKEN_FACTORY_KEY   the team's API key; read from the environment or a local .env file
FLOWCAST_LLM_MODEL      model to use (default Gemma-4-31B-IT)
FLOWCAST_LLM_URL        base URL (default the Token Factory shared endpoint)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://developer.amd.com.cn/radeon/api/v1"
DEFAULT_MODEL = "Gemma-4-31B-IT"
HOSTED_ON = "AMD Token Factory (AMD GPUs)"


def _load_env_file(path: Path = Path(".env")) -> None:
    """Read KEY=value lines into the environment without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


class LanguageModelError(RuntimeError):
    pass


def model_name() -> str:
    return os.environ.get("FLOWCAST_LLM_MODEL", DEFAULT_MODEL)


def available() -> bool:
    return bool(os.environ.get("AMD_TOKEN_FACTORY_KEY"))


def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 500, temperature: float = 0.2) -> dict:
    """One chat completion. Returns the assistant message (which may contain tool calls).

    The first message must be a system message: without one, Gemma on this endpoint keeps
    generating until it reaches the token limit. Rate-limit replies are retried briefly.
    """
    key = os.environ.get("AMD_TOKEN_FACTORY_KEY")
    if not key:
        raise LanguageModelError("no Token Factory key is configured")
    if not messages or messages[0].get("role") != "system":
        raise ValueError("the first message must be a system message")
    body = {"model": model_name(), "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    request = urllib.request.Request(
        os.environ.get("FLOWCAST_LLM_URL", DEFAULT_URL) + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.load(response)
            return data["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            if error.code == 429 and attempt < 3:
                # The per-minute limit asks for 60 s, which is too long for a page; wait briefly
                # and try again in case it was the concurrency limit, then give up.
                time.sleep(min(float(error.headers.get("Retry-After", 1)), 4.0) + attempt)
                continue
            if error.code == 429:
                raise LanguageModelError("the language model is rate limited; try again in a minute") from error
            raise LanguageModelError(f"the language model returned {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
            raise LanguageModelError(f"the language model could not be reached: {error}") from error
    raise LanguageModelError("the language model did not answer")
