from __future__ import annotations

import asyncio
import logging
import signal

import structlog

logger = structlog.get_logger("account-opening-worker")


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main() -> None:
    _configure_logging()

    try:
        import agent_framework_foundry  # noqa: F401
    except ImportError:
        logger.error("agent-framework-foundry is not installed")

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("No agents registered, waiting...")
    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
