from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now_iso(self) -> str: ...


class SystemClock:
    def now_iso(self) -> str:
        return datetime.now(UTC).isoformat()


class FixedClock:
    def __init__(self, fixed: str) -> None:
        self._fixed = fixed

    def now_iso(self) -> str:
        return self._fixed
