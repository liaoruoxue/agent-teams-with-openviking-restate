"""Application entry point — registers all Restate services and serves via Hypercorn."""

import asyncio
import logging

import restate

from src.agents.coder import coder
from src.agents.manager import manager
from src.agents.tester import tester
from src.infra.sandbox import sandbox

# ── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Restate application ────────────────────────────────────────────
app = restate.app(services=[sandbox, manager, coder, tester])


async def _serve() -> None:
    import hypercorn.asyncio
    from hypercorn import Config

    conf = Config()
    conf.bind = ["0.0.0.0:9080"]
    log.info("Starting Restate app on %s", conf.bind)
    await hypercorn.asyncio.serve(app, conf)  # type: ignore[arg-type]


if __name__ == "__main__":
    asyncio.run(_serve())
