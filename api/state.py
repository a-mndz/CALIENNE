"""Shared runtime singletons for route modules.

``server.py`` owns construction (in its lifespan) and publishes the instances
here; route modules read them late-bound at request time, so import order
between ``server`` and ``api.*`` never matters and no circular import exists.
"""

from __future__ import annotations

from typing import Any


class AppState:
    def __init__(self) -> None:
        self.gateway: Any = None
        self.strategy: Any = None
        self.pool: Any = None
        self.streaming_manager: Any = None
        self.calienne: dict[str, Any] = {}
        self.background_tasks: Any = None


state = AppState()
