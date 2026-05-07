import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .npc import Npc


@dataclass
class TailingState:
    target_npc_id: str
    distance: int = 2
    elapsed_minutes: int = 0
    last_checked_minute: int = 0


@dataclass
class Disguise:
    id: str
    name: str
    apparent_faction: str
    bonus: int
    description: str


class StealthSystem:
    def _init_(self, disguises: Dict[str. Disguise]):
        self.disguises = disguises

    def apply_disguise(self, disguise_id: str) -> Optional[Disguise]:
        return self.disguises.get(disguise_id)

    def start_tail(self, target_npc_id: str) -> TailingState:
        return TailingState(target_npc_id=target_npc_id)
    
    def hide_check(
        self,
        stealth_skill: int,
        disguise_bonus: int,
        room_indoors: bool,
        observers: List[Npc],
    ) -> Tuple[bool, int]:
        observer_pressure = sum(npc.awareness for npc in observers) // max(1, len(observers)) if observers else 25
        roll = random.randint(1, 100)
        score = stealth_skill + disguise_bonus + (10 if room_indoors else 0) - (observer_pressure // 2)
        return roll <= max(15, score), roll
    
    def tail_check(
        self,
        state: TailingState,
        target: Npc,
        stealth_skill: int,
        disguise_bonus: int,
        hidden: bool,
    ) -> Tuple[bool, int]:
        roll = random.randint(1, 100)
        difficulty = target.awareness + 5 * (2 - state.distance)
        bonus = stealth_skill + disguise_bonus + (10 if hidden else 0)
        success = roll + bonus >= difficulty
        if success:
            state.distance = min(3, state.distance + 1)
        else:
            state.distance = max(0, state.distance - 1)
        return success, roll