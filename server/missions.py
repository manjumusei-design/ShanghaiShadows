from dataclasses import dataclass, field
from typing import Dict, List, Literal, TYPE_CHECKING
import yaml
from pathlib import Path

from .dataclass_utils import filter_to_dataclass
from .constants import MISSIONS_PATH
from .trust import get_role_trust
from .content_validation import load_strict_yaml

if TYPE_CHECKING:
    from .player_data import PlayerData


def _mission_target_dead(world, inner_world, target: str) -> bool:
    if getattr(world, "named_npc_deaths", None) is not None:
        from .game_world import is_named_npc_dead
        return is_named_npc_dead(world, target)
    return target in getattr(inner_world, "dead_npcs", set())


@dataclass
class MissionObjective:
    type: str
    target: str
    count: int = 1
    current: int = 0
    item: str = ""


@dataclass
class MissionReward:
    money_fabi: int = 0
    money_silver: int = 0
    trust: Dict[str, int] = field(default_factory=dict)
    influence: Dict[str, int] = field(default_factory=dict)
    health_restore: int = 0
    morale_restore: int = 0
    add_flag: str = ""
    add_item: str = ""
    cross_faction_penalty: Dict[str, int] = field(default_factory=dict)


@dataclass
class Mission:
    id: str
    title: str
    description: str
    faction: str
    min_trust: int = 0
    giver_npc_hint: str = ""
    prerequisite_mission: str = ""
    dilemma_group: str = ""
    objectives: List[MissionObjective] = field(default_factory=list)
    rewards: MissionReward = field(default_factory=MissionReward)
    expires_days: int = 7
    offer_hours: tuple[int, ...] | None = None


class MissionManager:
    def __init__(self, missions: Dict[str, Mission]):
        self.missions = missions

    def get_available(
        self,
        player: "PlayerData",
        world=None,
        current_day: int = None,
        current_hour: int = None,
    ) -> List[Mission]:
        available = []
        active_ids = {entry.get("mission_id") for entry in player.active_missions}
        completed_ids = set(getattr(player, "completed_missions", []))
        abandoned_ids = set(getattr(player, "abandoned_missions", []))
        failed_ids = set(getattr(player, "failed_missions", []))
        declined_ids = set(getattr(player, "declined_missions", []))
        deferred = getattr(player, "deferred_missions", None)
        if not isinstance(deferred, dict):
            player.deferred_missions = {}
            deferred = player.deferred_missions
        if current_day is not None:
            for mission_id, until_day in list(deferred.items()):
                try:
                    expired = current_day >= int(until_day)
                except (TypeError, ValueError):
                    expired = True
                if expired:
                    deferred.pop(mission_id, None)
        commitments = getattr(player, "dilemma_commitments", None)
        if not isinstance(commitments, dict):
            player.dilemma_commitments = {}
            commitments = player.dilemma_commitments
        committed_ids = set(commitments.values())
        blocked_groups = set(commitments.keys())
        for mission in self.missions.values():
            if not mission.dilemma_group:
                continue
            if mission.id in active_ids or mission.id in completed_ids or mission.id in abandoned_ids or mission.id in failed_ids:
                blocked_groups.add(mission.dilemma_group)

        for mission in self.missions.values():
            if mission.id in active_ids:
                continue
            if mission.id in completed_ids or mission.id in abandoned_ids or mission.id in failed_ids:
                continue
            if mission.id in declined_ids or mission.id in committed_ids:
                continue
            if mission.dilemma_group and mission.dilemma_group in blocked_groups:
                continue
            if current_day is not None and mission.id in deferred:
                try:
                    if current_day < int(deferred[mission.id]):
                        continue
                except (TypeError, ValueError):
                    deferred.pop(mission.id, None)
            faction_trust = get_role_trust(player.trust, mission.faction, None)
            if faction_trust < mission.min_trust:
                continue
            if mission.prerequisite_mission and mission.prerequisite_mission not in completed_ids:
                continue
            if mission.offer_hours is not None and current_hour not in mission.offer_hours:
                continue
            valid, _ = self.validate_mission(mission, world, player)
            if not valid:
                continue
            available.append(mission)
        return available

    def offer_for_giver(
        self,
        player: "PlayerData",
        giver_npc_id: str,
        world=None,
        current_day: int = None,
        current_hour: int = None,
    ) -> List[Mission]:
        return [
            mission
            for mission in self.get_available(player, world, current_day, current_hour)
            if mission.giver_npc_hint == giver_npc_id
        ]

    def resolve_offer(
        self,
        player: "PlayerData",
        mission_id: str,
        action: Literal["accept", "defer", "decline"],
        current_day: int,
        world=None,
        current_hour: int = None,
    ) -> tuple[bool, str]:
        if action not in ("accept", "defer", "decline"):
            return False, "That is not a valid mission-offer choice."
        mission = self.missions.get(mission_id)
        if not mission:
            return False, "That opportunity is no longer available."
        available_ids = {
            item.id for item in self.get_available(player, world, current_day, current_hour)
        }
        if mission_id not in available_ids:
            return False, "You cannot choose that mission now."
        if action == "accept" and len(player.active_missions) >= 5:
            return False, "You cannot take on another mission while five are active."
        if action == "accept":
            progress = [
                {"type": obj.type, "target": obj.target, "count": obj.count, "current": 0, "item": obj.item}
                for obj in mission.objectives
            ]
            for obj, prog in zip(mission.objectives, progress):
                if obj.type == "collect_item":
                    held = sum(1 for i in player.inventory if getattr(i, "id", "") == obj.target)
                    prog["current"] = min(held, prog["count"])
            player.active_missions.append({
                "mission_id": mission_id,
                "accepted_day": current_day,
                "objectives_progress": progress,
            })
            if mission.dilemma_group:
                commitments = getattr(player, "dilemma_commitments", None)
                if not isinstance(commitments, dict):
                    player.dilemma_commitments = {}
                    commitments = player.dilemma_commitments
                commitments[mission.dilemma_group] = mission_id
            return True, f"You accepted {mission.title}."
        if action == "defer":
            deferred = getattr(player, "deferred_missions", None)
            if not isinstance(deferred, dict):
                player.deferred_missions = {}
                deferred = player.deferred_missions
            deferred[mission_id] = current_day + 1
            return True, "You leave the offer for another day."
        declined = getattr(player, "declined_missions", None)
        if not isinstance(declined, list):
            player.declined_missions = []
            declined = player.declined_missions
        declined.append(mission_id)
        return True, "You leave the offer behind."

    def accept_with_reason(
        self,
        player: "PlayerData",
        mission_id: str,
        current_day: int,
        world=None,
        current_hour: int = None,
    ) -> tuple[bool, str]:
        return self.resolve_offer(player, mission_id, "accept", current_day, world, current_hour)

    def accept(
        self,
        player: "PlayerData",
        mission_id: str,
        current_day: int,
        world=None,
        current_hour: int = None,
    ) -> bool:
        accepted, _ = self.accept_with_reason(player, mission_id, current_day, world, current_hour)
        return accepted

    def decline(self, player: "PlayerData", mission_id: str) -> bool:
        return self.resolve_offer(player, mission_id, "decline", 0)[0]

    def update_objectives(self, player: "PlayerData", event_type: str, target_id: str, item_id: str = None) -> List[str]:
        completed = []
        for active in player.active_missions:
            mission = self.missions.get(active["mission_id"])
            if not mission:
                continue
            for prog in active["objectives_progress"]:
                if prog["current"] >= prog["count"]:
                    continue
                if prog["type"] == event_type and prog["target"] == target_id:
                    required = prog.get("item", "")
                    if not required or item_id == required:
                        prog["current"] += 1
            if self._is_complete(active):
                completed.append(active["mission_id"])
        return completed

    def _is_complete(self, active: dict) -> bool:
        return all(
            prog["current"] >= prog["count"]
            for prog in active["objectives_progress"]
        )

    def complete(self, player: "PlayerData", mission_id: str) -> Mission | None:
        active = next(
            (entry for entry in player.active_missions if entry["mission_id"] == mission_id),
            None,
        )
        if not active or not self._is_complete(active):
            return None
        player.active_missions.remove(active)
        if mission_id not in player.completed_missions:
            player.completed_missions.append(mission_id)
        return self.missions.get(mission_id)

    def abandon(self, player: "PlayerData", mission_id: str) -> bool:
        active = next(
            (entry for entry in player.active_missions if entry["mission_id"] == mission_id),
            None,
        )
        if not active:
            return False
        player.active_missions.remove(active)
        if mission_id not in player.abandoned_missions:
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
        failed = getattr(player, "failed_missions", None)
        if not isinstance(failed, list):
            player.failed_missions = []
            failed = player.failed_missions
        for mission_id in expired:
            if mission_id not in failed:
                failed.append(mission_id)
        return expired

    def validate_mission(self, mission: Mission, world=None, player: "PlayerData" = None) -> tuple:
        inner_world = getattr(world, "world", world)
        for obj in mission.objectives:
            if obj.type == "kill_npc" and world:
                if _mission_target_dead(world, inner_world, obj.target):
                    return False, f"Target NPC {obj.target} is already dead"
            if obj.type in ("collect_item", "deliver_item") and world:
                found = any(
                    hasattr(item, "id") and item.id == obj.target
                    for room in getattr(inner_world, "rooms", {}).values()
                    for item in getattr(room, "items", [])
                )
                if not found:
                    held = player is not None and any(
                        getattr(item, "id", "") == obj.target
                        for item in getattr(player, "inventory", [])
                    )
                    if not held:
                        return False, f"Target item {obj.target} no longer exists in the world"
            if obj.type in ("deliver_to_npc", "talk_to_npc") and world:
                if obj.target not in inner_world.npcs:
                    return False, f"Delivery NPC {obj.target} no longer exists"
            if obj.type == "visit_room" and world:
                if obj.target not in getattr(inner_world, "rooms", {}):
                    return False, f"Target room {obj.target} no longer exists"
        return True, ""

    def check_staleness(self, player: "PlayerData", world=None) -> List[str]:
        stale = []
        inner_world = getattr(world, "world", world)
        for active in player.active_missions[:]:
            mission = self.missions.get(active["mission_id"])
            if not mission:
                continue
            for prog in active["objectives_progress"]:
                ptype, ptarget = prog["type"], prog["target"]
                if ptype == "kill_npc" and world:
                    if _mission_target_dead(world, inner_world, ptarget) and prog["current"] == 0:
                        stale.append(active["mission_id"])
                        player.active_missions.remove(active)
                        if active["mission_id"] not in player.failed_missions:
                            player.failed_missions.append(active["mission_id"])
                        break
                if ptype == "deliver_to_npc" and world:
                    if ptarget not in inner_world.npcs and prog["current"] == 0:
                        stale.append(active["mission_id"])
                        player.active_missions.remove(active)
                        if active["mission_id"] not in player.failed_missions:
                            player.failed_missions.append(active["mission_id"])
                        break
        return stale

    def get_active(self, player: "PlayerData") -> List[dict]:
        return player.active_missions


def load_missions(path: str = MISSIONS_PATH) -> Dict[str, Mission]:
    p = Path(path)
    if not p.exists():
        return {}
    data = load_strict_yaml(p) or {}
    missions: Dict[str, Mission] = {}
    for row in data.get("missions", []):
        missing_offer_hours = object()
        raw_offer_hours = row.get("offer_hours", missing_offer_hours)
        offer_hours = None
        if raw_offer_hours is not missing_offer_hours:
            if not isinstance(raw_offer_hours, list) or not raw_offer_hours:
                raise ValueError(f"offer_hours for {row['id']} must be a non-empty list")
            if any(isinstance(hour, bool) or not isinstance(hour, int) for hour in raw_offer_hours):
                raise ValueError(f"offer_hours for {row['id']} must contain integers")
            if len(set(raw_offer_hours)) != len(raw_offer_hours):
                raise ValueError(f"offer_hours for {row['id']} must not contain duplicates")
            if any(hour < 0 or hour > 23 for hour in raw_offer_hours):
                raise ValueError(f"offer_hours for {row['id']} must be between 0 and 23")
            offer_hours = tuple(raw_offer_hours)
        objectives = [
            MissionObjective(**filter_to_dataclass(o, MissionObjective, warn_unknown=True))
            for o in row.get("objectives", [])
        ]
        rewards = MissionReward(**filter_to_dataclass(row.get("rewards", {}), MissionReward, warn_unknown=True))
        missions[row["id"]] = Mission(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            faction=row["faction"],
            min_trust=int(row.get("min_trust", 0)),
            giver_npc_hint=row.get("giver_npc_hint", ""),
            prerequisite_mission=row.get("prerequisite_mission", ""),
            dilemma_group=row.get("dilemma_group", ""),
            objectives=objectives,
            rewards=rewards,
            expires_days=int(row.get("expires_days", 7)),
            offer_hours=offer_hours,
        )
    return missions
