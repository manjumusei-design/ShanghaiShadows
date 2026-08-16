import random
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .npc import Npc
from .constants import SEASONAL_STEALTH_MODIFIER, SEASONAL_PERCEPTION_MODIFIER, WEATHER_STEALTH_MODIFIER, WEATHER_PERCEPTION_MODIFIER
from .survival import get_hunger_tier


def get_hunger_stealth_penalty(hunger: float) -> int:
    tier = get_hunger_tier(hunger)
    if tier == "FAMISHED":
        return -15
    if tier == "STARVING":
        return -5
    return 0


class PierceStage(Enum):
    NONE = 0
    SUSPICION = 1
    CHALLENGE = 2
    EXPOSED = 3


PIERCE_THRESHOLD_SUSPICION = 25
PIERCE_THRESHOLD_CHALLENGE = 50
PIERCE_THRESHOLD_EXPOSE = 75


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
    curfew_detection_modifier: int = 0


class StealthSystem:
    def __init__(self, disguises: Dict[str, Disguise]):
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
        morale: int = 50,
        hunger: int = 60,
        weather: str = "clear",
    ) -> Tuple[bool, int]:
        observer_pressure = sum(npc.awareness for npc in observers) // max(1, len(observers)) if observers else 25
        roll = random.randint(1, 100)
        seasonal_mod = SEASONAL_STEALTH_MODIFIER.get(season, 0)
        weather_mod = WEATHER_STEALTH_MODIFIER.get(weather, 0)
        hiding_spot_bonus = 15 if room_hiding_spots else 0

        morale_mod = 0
        if morale < 30:
            morale_mod = -5
        elif morale > 70:
            morale_mod = 5

        hunger_mod = get_hunger_stealth_penalty(hunger)

        score = stealth_skill + disguise_bonus + (10 if room_indoors else 0) + hiding_spot_bonus - (observer_pressure // 2) + seasonal_mod + weather_mod + morale_mod + hunger_mod
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
        hunger: int = 60,
    ) -> Tuple[bool, int]:
        roll = random.randint(1, 100)
        difficulty = target.awareness + 5 * (2 - state.distance)
        seasonal_mod = SEASONAL_STEALTH_MODIFIER.get(season, 0)
        hunger_mod = get_hunger_stealth_penalty(hunger)
        bonus = stealth_skill + disguise_bonus + (10 if hidden else 0) + seasonal_mod + hunger_mod
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

    def disguise_pierce_check(
        self,
        npc: Npc,
        disguise_bonus: int,
        wanted_level: int = 0,
        season: str = "spring",
        perception_bonus: int = 0,
    ) -> PierceStage:
        seasonal_mod = SEASONAL_PERCEPTION_MODIFIER.get(season, 0)
        roll = random.randint(1, 100)
        wanted_penalty = wanted_level * 10
        effective_defense = disguise_bonus - wanted_penalty

        total = roll + npc.perception + seasonal_mod + perception_bonus

        if total >= PIERCE_THRESHOLD_EXPOSED + effective_defense:
            return PierceStage.EXPOSED
        elif total >= PIERCE_THRESHOLD_CHALLENGE + effective_defense:
            return PierceStage.CHALLENGE
        elif total >= PIERCE_THRESHOLD_SUSPICION + effective_defense:
            return PierceStage.SUSPICION
        else:
            return PierceStage.NONE

    def passive_detection_check(
        self,
        npc: Npc,
        player_stealth: int,
        season: str = "spring",
        room_indoors: bool = False,
        player_moving: bool = False,
        game_hour: int = 12,
        weather: str = "clear",
    ) -> PierceStage:
        seasonal_mod = SEASONAL_PERCEPTION_MODIFIER.get(season, 0)
        weather_perception_mod = WEATHER_PERCEPTION_MODIFIER.get(weather, 0)
        roll = random.randint(1, 100)

        BASE_THRESHOLD_SUSPICION = 35
        BASE_THRESHOLD_CHALLENGE = 60
        BASE_THRESHOLD_EXPOSED = 85

        is_night = game_hour < 6 or game_hour >= 20
        dark_bonus = 15 if (room_indoors and is_night) else 0

        movement_penalty = 10 if player_moving else 0

        effective_defense = player_stealth + dark_bonus - movement_penalty

        total = roll + npc.perception + seasonal_mod + weather_perception_mod

        if total >= BASE_THRESHOLD_EXPOSED + effective_defense:
            return PierceStage.EXPOSED
        elif total >= BASE_THRESHOLD_CHALLENGE + effective_defense:
            return PierceStage.CHALLENGE
        elif total >= BASE_THRESHOLD_SUSPICION + effective_defense:
            return PierceStage.SUSPICION
        else:
            return PierceStage.NONE

    def stealth_check(
        self,
        player_steath: int,
        target_perception: int,
        difficulty_modifier: int,
        room_indoors: bool,
        observers: List[Npc],
        target_npc: Optional[Npc] = None,
        season: str = "spring",
        player_hidden: bool = False,
        hunger: int = 60,
    ) -> Tuple[bool, int]:
        roll = random.randint(1, 100)
        seasonal_mod = SEASONAL_STEALTH_MODIFIER.get(season, 0)

        base_difficulty = 60 + difficulty_modifier

        indoor_bonus = 10 if room_indoors else 0

        hidden_bonus = 10 if player_hidden else 0

        observer_pressure = sum(npc.awareness for npc in observers) // max(1, len(observers)) if observers else 0

        target_modifier = 0
        if target_npc:
            if target_npc.awareness < 30:
                target_modifier = -10
            elif target_npc.awareness > 70:
                target_modifier = 15

        hunger_mod = get_hunger_stealth_penalty(hunger)

        score = (
            player_stealth
            - target_perception // 2
            + indoor_bonus
            + hidden_bonus
            - observer_pressure // 3
            + seasonal_mod
            + target_modifier
            - difficulty_modifier
            + hunger_mod
        )

        success_threshold = max(10, base_difficulty - score)
        success = roll >= success_threshold

        return success, roll