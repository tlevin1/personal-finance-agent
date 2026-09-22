from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class AnthropicClient:
    """Real Anthropic API client. Only imports the SDK when actually used."""

    def __init__(self, model: str, api_key: str | None = None):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str) -> str:
        # Note: the installed anthropic SDK (1.8.0, targeting the Claude 5 model
        # line) does not expose a `temperature` param on messages.create at all --
        # it was removed from the request schema. Documented as a deviation from
        # the brief's "use temperature 0" guidance in the README.
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


class RecordingClient:
    """Wraps another client and persists every prompt/response pair to disk."""

    def __init__(self, wrapped: LLMClient, path: Path):
        self._wrapped = wrapped
        self._path = path
        self._data: dict[str, str] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def complete(self, prompt: str) -> str:
        response = self._wrapped.complete(prompt)
        self._data[_hash_prompt(prompt)] = response
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        return response


class ReplayClient:
    """Reads recorded responses from disk. Makes no network calls."""

    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(
                f"No recording found at {path}. Run once without --replay first to create it."
            )
        self._data: dict[str, str] = json.loads(path.read_text())

    def complete(self, prompt: str) -> str:
        key = _hash_prompt(prompt)
        if key not in self._data:
            raise KeyError(
                f"No recorded response for this prompt (hash {key[:8]}...). "
                "The recording may be stale for the current code path."
            )
        return self._data[key]


class ScriptedClient:
    """Returns canned responses in order. Used by offline tests and to demo
    bad-model-output handling without depending on a live API call."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            raise RuntimeError("ScriptedClient exhausted its canned responses")
        return self._responses.pop(0)
