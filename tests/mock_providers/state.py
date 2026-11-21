"""What the mock has seen and how its configurable behaviours are set; reset between tests."""

from dataclasses import dataclass, field

from web.types import JsonValue


@dataclass
class Recorded:
    """One request the app sent to a mock provider."""

    provider: str
    method: str
    path: str
    body: JsonValue
    params: dict[str, str]

    def as_json(self) -> dict[str, JsonValue]:
        """The request as JSON for the control API."""
        return {
            "provider": self.provider,
            "method": self.method,
            "path": self.path,
            "body": self.body,
            "params": dict[str, JsonValue](self.params),
        }


@dataclass
class Settings:
    """Knobs a test can turn through ``POST /__mock/settings``."""

    slow_seconds: float = 3.0  # how long the "slow" models take
    drop_after_seconds: float = 1.0  # how long the "drop" models wait before cutting the connection
    video_polls: int = 2  # how many status checks a video stays in progress for
    venice_usd: float = 0.76
    venice_credits: float = 4.76
    venice_diem: float = 0.0


@dataclass
class State:
    """The mock's whole state."""

    requests: list[Recorded] = field(default_factory=list[Recorded])
    settings: Settings = field(default_factory=Settings)
    video_checks: dict[str, int] = field(default_factory=dict[str, int])  # queue id -> status checks so far

    def reset(self) -> None:
        """Forget every request and restore the default settings."""
        self.requests.clear()
        self.video_checks.clear()
        self.settings = Settings()


state = State()
