import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .npc import Npc
from .constants import SEASONAL_STEALTH_MODIFIER, SEASONAL_PERCEPTION_MODIFIER


@dataclass

class TailingState:
    target_npc_id: str
    distance: int = 2
    elapsed_minutes: int = 0
    last_checked_minute: int = 0
    stealth_awarded: bool = False

@dataclass
class Disguise:
    id: str
    name: str
    apparent_faction: str
    bonus: int
    description: str


class StealthSystem:
    def _init_(self, disguises: Dict[str, Disguise]):
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
        season: str = "spring",
        room_hiding_spots: bool = False,
    ) -> Tuple[bool, int]:
        observer_pressure = sum(npc.awareness for npc in observers) // max(1, len(observers)) if observers else 25
        roll = random.randint(1, 100)
        seasonal_mod = SEASONAL_STEALTH_MODIFIER.get(season, 0)
        hiding_spot_bonus = 15 if room_hiding_spots else 0
        score = stealth_skill + disguise_bonus + (10 if room_indoors else 0) + hiding_spot_bonus - (observer_pressure // 2) + seasonal_mod
        return roll <= max(15, score), roll

    def tutorial_hide_check(
            self, 
            stealth_skill: int,
            disguise_bonus: int,
            room_indoors: bool,
            observers: List[Npc],
            season: str = "spring",
            room_hiding_spots: bool = False,
    ) -> Tuple[bool, int]:
        hiding_spot_bonus = 15 if room_hiding_spots else 0
        score = stealth_skill + disguise_bonus + (10 if room_indoors else 0) + hiding_spot_bonus + 50
        return True, 1
    
    def tail_check(
        self,
        state: TailingState,
        target: Npc,
        stealth_skill: int,
        disguise_bonus: int,
        hidden: bool,
        season: str = "spring",
    ) -> Tuple[bool, int]:
        roll = random.randint(1, 100)
        difficulty = target.awareness + 5 * (2 - state.distance)
        seasonal_mod = SEASONAL_STEALTH_MODIFIER.get(season, 0)
        bonus = stealth_skill + disguise_bonus + (10 if hidden else 0) + seasonal_mod
        success = roll + bonus >= difficulty
        if success:
            state.distance = min(3, state.distance + 1)
        else:
            state.distance = max(0, state.distance - 1)
        return success, roll
    
    @staticmethod
    def _perception_contest(npc: Npc, defense_stat: int, base_difficulty: int, season: str = "spring") -> bool:
        seasonal_mod = SEASONAL_PERCEPTION_MODIFIER.get(season, 0)
        return random.randint(1, 100) + npc.perception + seasonal_mod >= base_difficulty + defense_stat
    
    def disguise_pierce_check(self, npc: Npc, disguise_bonus: int, wanted_level: int = 0, season: str = "spring") -> bool:
        wanted_penalty = wanted_level * 10
        return self._perception_contest(npc, disguise_bonus + wanted_penalty, 50, season)
    
    def passive_detection_check(self, npc: Npc, player_stealth: int, season: str = "spring") -> bool:
        return self._perception_contest(npc, player_stealth, 40, season)