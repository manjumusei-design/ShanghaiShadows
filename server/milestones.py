from dataclasses import dataclass, field
from typing import Dict, List, TYPE_CHECKING
from pathlib import Path
import yaml

if TYPE_CHECKING:
    from .player_data import PlayerData
    from .game_world import SharedWorldState


@dataclass
class Milestone:
    id: str
    trigger: str
    narrative: str
    day: int = 0
    effects: Dict = field(default_factory=dict)


class MilestoneManager:
    def __init__(self, milestones: List[Milestone]):
        self.milestones = {m.id: m for m in milestones}

    def check_day(self, current_day: int) -> List[Milestone]:
        return [m for m in self.milestones.values()
                if m.trigger == "day" and m.day == current_day]
    
    def check_action(self, action: str) -> List[Milestone]:
        return [m for m in self.milestones.values()
                if m.trigger == action]
    

def apply_milestone_effects(player: "PlayerData", milestone: Milestone, shared: "SharedWorldState") -> bool:
    flag = f"milestone_{milestone.id}"
    if flag in player.flags:
        return False
    player.flags.append(flag)
    effects = milestone.effects
    if effects.get("courage"):
        from .player_data import grow_stat
        grow_stat(player, "courage", effects["courage"])
    if effects.get("morale"):
        player.morale = min(100, player.morale + effects["morale"])
    if effects.get("influence"):
        from .victory import adjust_influence
        for faction, delta in effects["influence"].items():
            shared.ccp_influence, shared.gmd_influence = adjust_influence(
                shared.ccp_influence, shared.gmd_influence, faction, delta
            )
    return True


def load_milestones(path: str) -> List[Milestone]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    milestones = []
    for row in data.get("milestones", []):
        milestones.append(Milestone(
            id=row["id"],
            trigger=row["trigger"],
            narrative=row["narrative"],
            day=int(row.get("day", 0)),
            effects=row.get("effects", {}),
        ))
    return milestones
