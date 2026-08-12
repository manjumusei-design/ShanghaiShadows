from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CommandOutcome:
    suceeded: bool
    code: str
    facts: frozenset[str]
    data: Mapping[str, Any]


def success(code: str, *, facts: Iterable[str] = (), **data: Any) -> CommandOutcome:
    return CommandOutcome(True, code, frozenset(facts), data)


def failure(code: str, **data: Any) -> CommandOutcome:
    return CommandOutcome(False, code, frozenset(), data)
