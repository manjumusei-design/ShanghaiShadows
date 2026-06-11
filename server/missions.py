from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING
import yaml
from pathlib import Path

from .dataclass_utils import filter_to_dataclass
from .constants import MISSIONS_PATH
from .trust import get_role_trust

if TYPE_CHECKING:
    from .player_data import PlayerData


@dataclass
class MissionObjective:
    type: str
    target: str
    count: int = 1
    current: int = 0


@dataclass
class Mission:
    id: str
    title: str
    description: str
    faction: str
    morale_restore: int = 0
    add_flag: str = ""
    add_item: str = ""


@dataclass
class Mission:
    id: str
    title: str
    description: str
    faction: str
    min_trust: int = 0
    giver_npc_hint: str = ""
    objectives: List[MissionObjective] = field(default_factory=list)
    rewards: MissionReward = field(default_factory=MissionReward)
    expires_days = int = 7


class MissionManager:
    def __init__(self, missions: Dict[str, Mission]):
        self.missions = missions

    def get_available(self, player: "PlayerData") -> List[Mission]:
        available = []
        active_ids = {a["mission_id"] for a in player.active_missions}
        for mission in self.missions.values():
            if mission.id in active_ids:
                continue
            if mission.id in player.completed_missions:
                continue
            if mission.id in player.abandoned_missions:
                continue
            faction_trust = get_role_trust(player.trust, mission.faction, None)
            if faction_trust < mission.min_trust:
                continue
            available.append(mission)
        return available 
    
    def accept(self, player: "PlayerData", mission_id: str, current_day: int) -> bool:
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        if len(player.active_missions) >= 5:
            return False
        available_ids = {m.id for m in self.get_available(player)}
        if mission_id not in available_ids:
            return False
        progress = [
            {"type": obj.type, "target": obj.target, "count": obj.count, "current": 0}
            for obj in mission.objectives
        ]
        player.active_missions.append({
            "mission_id": mission_id,
            "accepted_day": current_day,
            "objectives_progress": progress,
        })
        return True
    
    def update_objectives(self, player: "PlayerData", event_type: str, target_id: str) -> List[str]:
        completed = []
        for active in player.active_missions:
            mission = self.missions.get(active["mission_id"])
            if not mission:
                continue
            for prog in active["objectives_progress"]:
                if prog["current"] >= prog["count"]:
                    continue
                if prog["type"] == event_type and prog["target"] == target_id:
                    prog["current"] += 1
            if self._is_complete(active):
                completed.append(active["mission_id"])
        return completed
    
    def _is_complete(self, active: dict) -> bool:
        return all(
            prog["current"] >= prog["count"]
            for prog in active["objectives_progress"]
        )
    
    def complete(self, player: "PlayerData", mission_id: str) -> Optional[Mission]:
        active = None
        for a in player.active_missions:
            if a ["mission_id"] == mission_id:
                active = a
                break
        if not active or not self._is_complete(active):
            return None
        player.active_missions.remove(active)
        player.completed_missions.append(mission_id)
        return self.missions.get(mission_id)
    
    def abandon(self, player: "PlayerData", mission_id: str) -> bool:
        active  = None
        for a in player.active_missions:
            if a ["mission_id"] == mission_id:
                active = a
                break
        if not active:
            return False
        player.active_missions.remove(active)
        player.abandoned_missions.append(mission_id)
        return True
    
    def check_expiry(self, player: "PlayerData", current_day: int) -> List[str]:
        expired = []
        remaining = []
        for active in player.active_missions:
            mission = self.missions.get(active["mission_id"])
            if mission and (current_day - active["accepted_day"]) > mission.expires_days:
                expired.append(active["mission_id"])
            else:
                remaining.append(active)
            player.active_missions = remaining
            return expired
        
    def get_active(self, player: "PlayerData") -> List[dict]:
        return player.active_missions
    

def load_missions(path: str = MISSIONS_PATH) -> Dict[str, Mission]:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    missions: Dict[str, Mission] = {}
    for row in data.get("missions", []):
        objectives = [
            MissionObjective(**filter_to_dataclass(o, MissionObjective))
            for o in row.get("objectives", [])
        ]
        rewards = MissionReward(**filter_to_dataclass(row.get("rewards", {}), MissionReward))
        missions[row["id"]] = Mission(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            faction=row["faction"],
            min_trust=int(row.get("min_trust", 0)),
            giver_npc_hint=row.get("giver_npc_hint", ""),
            objectives=objectives,
            rewards=rewards,
            expires_days=int(row.get("expires_days", 7)),
        )
    return missions