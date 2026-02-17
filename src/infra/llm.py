"""LLM client wrapping the Anthropic SDK for a custom-endpoint provider."""

import logging

from anthropic import Anthropic

log = logging.getLogger(__name__)


class LLMClient:
    """Thin wrapper around the Anthropic SDK that points at a custom base URL."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = Anthropic(base_url=base_url, api_key=api_key)
        self._model = model
        log.info("LLMClient initialised (model=%s, base_url=%s)", model, base_url)

    def chat(self, system: str, user: str) -> str:
        """Send a single-turn chat and return the assistant text."""
        log.debug("LLM request  model=%s system=%s user=%s", self._model, system[:80], user[:120])
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = resp.content[0].text
            log.debug("LLM response length=%d", len(text))
            return text
        except Exception:
            log.exception("LLM request failed")
            raise
