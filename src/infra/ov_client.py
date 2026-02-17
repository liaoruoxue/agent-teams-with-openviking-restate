"""OpenViking knowledge-base client."""

import json
import logging
import os
import tempfile
from pathlib import Path

import openviking as ov

from src.config import cfg

log = logging.getLogger(__name__)

# Default ov.conf location used by the SDK
_OV_CONF_DIR = Path.home() / ".openviking"
_OV_CONF_PATH = _OV_CONF_DIR / "ov.conf"


def _ensure_ov_conf() -> None:
    """Generate ~/.openviking/ov.conf from .env values if it does not exist."""
    if _OV_CONF_PATH.exists():
        log.debug("ov.conf already exists at %s", _OV_CONF_PATH)
        return

    if not cfg.volcengine_api_key:
        log.warning("VOLCENGINE_API_KEY not set — skipping ov.conf generation")
        return

    conf: dict = {
        "embedding": {
            "dense": {
                "provider": "volcengine",
                "api_key": cfg.volcengine_api_key,
                "api_base": cfg.volcengine_api_base,
                "model": cfg.doubao_embedding_model,
                "dimension": cfg.doubao_embedding_dim,
            }
        },
    }

    # Only add VLM section when the model is configured
    if cfg.doubao_vlm_model:
        conf["vlm"] = {
            "provider": "volcengine",
            "api_key": cfg.volcengine_api_key,
            "api_base": cfg.volcengine_api_base,
            "model": cfg.doubao_vlm_model,
        }

    _OV_CONF_DIR.mkdir(parents=True, exist_ok=True)
    _OV_CONF_PATH.write_text(json.dumps(conf, indent=2, ensure_ascii=False))
    log.info("Generated ov.conf at %s", _OV_CONF_PATH)


class OVClient:
    """Wrapper around the synchronous OpenViking SDK."""

    def __init__(self, data_path: str) -> None:
        _ensure_ov_conf()
        self._client = ov.SyncOpenViking(path=data_path)
        log.info("OVClient created (data_path=%s)", data_path)

    def init(self) -> None:
        """Initialise / load the local index."""
        log.info("OVClient.init — initialising index")
        self._client.initialize()

    def add(self, content: str, uri: str) -> None:
        """Persist *content* as a knowledge resource under *uri*."""
        log.info("OVClient.add uri=%s length=%d", uri, len(content))
        fd, temp_path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            self._client.add_resource(path=temp_path, target=uri)
            self._client.wait_processed(timeout=60)
            log.debug("OVClient.add — resource processed")
        except Exception:
            log.exception("OVClient.add failed for uri=%s", uri)
            raise
        finally:
            os.unlink(temp_path)

    def retrieve(self, query: str) -> str:
        """Search the knowledge base and return an L1 overview of the best hit."""
        log.info("OVClient.retrieve query=%s", query[:80])
        try:
            results = self._client.find(query, limit=3)
            if not results.resources:
                log.debug("OVClient.retrieve — no results")
                return ""
            best = results.resources[0]
            overview = self._client.overview(best.uri)
            log.debug("OVClient.retrieve — hit uri=%s overview_len=%d", best.uri, len(overview or ""))
            return overview or ""
        except Exception:
            log.exception("OVClient.retrieve failed")
            raise

    def close(self) -> None:
        log.info("OVClient.close")
        self._client.close()
