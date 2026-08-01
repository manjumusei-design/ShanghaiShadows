from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random
import time 
import yaml


@dataclass 
class NarrativeChain:
    id: str
    trigger: str
    npc: str
    precondition: Dict[str, object] = field(default_factory=dict)
    effects: Dict[str, object] = field(default_factory=dict)
    feed: str = "" 


@dataclass
class StoryletOption:
    text: str
    effects: Dict[str, object] =  field(default_factory=dict)
    followup_storylet: str = ""
    disabled: bool = False
    disabled_reason: str = ""
    response_msg: str = ""


@dataclass
class NeglectOutcome:
    narrative: str
    effects: Dict[str, object] = field(default_factory=dict)


@dataclass
class Storylet:
    id: str
    location: List[str]
    location_tags: List[str]
    trigger_chance: float
    narrative: str
    preconditions: Dict[str, object]
    options: List[StoryletOption]
    scope: str = "player"
    resolution: str= "first_choice"
    speaker_npc: str = ""
    listener_npc: str = ""
    is_overheard: bool = False
    turns: List[Dict[str, str]] = field(default_factory=list)
    timer_seconds: int = 120
    blocking: bool = False
    neglect: Optional[NeglectOutcome] = None


@dataclass
class ActiveStorylet:
    storylet_id: str
    narrative: str
    options: List[StoryletOption]
    triggered_at: float = field(default_factory=time.time)
    resolved: bool = False
    room_id: str = ""
    timer_duration: int = 120
    timer_started_at: float = field(default_factory=time.time)
    speaker_npc: str = ""
    listener_npc: str = ""
    turns: List[Dict[str, str]] = field(default_factory=list)
    blocking: bool = False
    scope: str = "player"
    owner_username: str = ""
    expires_at: float = 0.0
    resolution_started: bool = False

def load_storylets(path: str) -> Dict[str, Storylet]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    storylets: Dict[str, Storylet] = {}
    for row in data.get("storylets", []):
        neglect_data = row.get("neglect")
        neglect = None
        if neglect_data:
            neglect = NeglectOutcome(
                narrative=neglect_data.get("narrative", "The moment passes."),
                effects=neglect_data.get("effects", {})
            )

        storylets[row["id"]] = Storylet(
            id=row["id"],
            location=row.get("location", []),
            location_tags=row.get("location_tags", []),
            trigger_chance=float(row.get("trigger_chance", 1.0)),
            narrative=row["narrative"],
            preconditions=row.get("preconditions", {}),
            options=[
                StoryletOption(
                    text=opt["text"],
                    effects=opt.get("effects", {}),
                    followup_storylet=opt.get("followup_storylet", ""),
                    disabled=opt.get("disabled", False),
                    disabled_reason=opt.get("disabled_reason", ""),
                    response_msg=opt.get("response_msg", "")
                )
                for opt in row.get("options", [])
            ],
            scope=row.get("scope", "player"),
            resolution=row.get("resolution", "first_choice:"),
            speaker_npc=row.get("speaker_npc", ""),
            listener_npc=row.get("listener_npc", ""),
            is_overheard=row.get("is_overheard", False),
            timer_seconds=row.get("timer_seconds", 120),
            turns=list(row.get("turns", [])),
            blocking=row.get("blocking", False),
            neglect=neglect,
        )
    return storylets


def load_narrative_chains(path: str) -> Dict[str, NarrativeChain]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    chains: Dict[str, NarrativeChain] = {}
    for row in data.get("narrative_chains", []):
        chains[row["id"]] = NarrativeChain(
            id=row["id"],
            trigger=row.get("trigger", "talk_to"),
            npc=row.get("npc", ""),
            precondition=row.get("precondition", {}),
            effects=row.get("effects", {}),
            feedback=row.get("feedback", ""),
        )
    return chains



class StoryletManager:
    def __init__(self, storylets: Dict[str, Storylet], narrative_chains: Dict[str, NarrativeChain] = None):
        self.storylets = storylets
        self.narrative_chains = narrative_chains or {}

    def _eligible(self, storylet: Storylet, player, shared) -> bool:
        from .constants import STORYLET_QUEUE_MAX
        if storylet.scope == "player" and len(player.active_storylets) >= STORYLET_QUEUE_MAX:
            return False
        if storylet.id in player.storylet_history:
            return False
        
        if getattr(player, 'in_tutorial', False) and storylet.id != "tutorial_choice":
            return False
        
        room = shared.world.get_room(player.current_room)
        if not room:
            return False
        if storylet.location and room.id not in storylet.location:
            return False
        if storylet.location_tags and not set(storylet.location_tags).intersection(room.tags):
            return False

        if storylet.is_overheard:
            if storylet.speaker_npc and storylet.speaker_npc not in room.npcs:
                return False
            if storylet.listener_npc and storylet.listener_npc not in room.npcs:
                return False
        elif storylet.speaker_npc and storylet.speaker_npc not in room.npcs:
            return False

        if storylet.scope == "room":
            if room.id in shared.active_room_storylets:
                existing = shared.active_room_storylets[room.id]
                if not existing.get("resolved", True):
                    return False

        pre = storylet.preconditions
        for flag in pre.get("flags_required", []):
            if flag not in player.flags:
                return False
        for flag in pre.get("flags_missing", []):
            if flag in player.flags:
                return False
        for item_id in pre.get("inventory_has", []):
            if item_id not in [item.id for item in player.inventory]:
                return False

        hour_range = pre.get("game_hour")
        if hour_range:
            hour = shared.game_time.minute // 60
            if hour < int(hour_range[0]) or hour > int(hour_range[1]):
                return False

        for trust_key, bounds in pre.get("trust_ranges", {}).items():
            from .trust import get_role_trust
            if "." in trust_key:
                faction, role = trust_key.split(".", 1)
                current = get_role_trust(player.trust, faction, role)
            else:
                current = get_role_trust(player.trust, trust_key)
            if current < int(bounds[0]) or current > int(bounds[1]):
                return False
        return True

    def maybe_trigger(self, shared) -> Optional[ActiveStorylet]:
        return None

    def maybe_trigger_for_player(self, player, shared) -> Optional[ActiveStorylet]:
        eligible = [storylet for storylet in self.storylets.values() if self._eligible(storylet, player, shared)]
        if not eligible:
            return None
        random.shuffle(eligible)
        for storylet in eligible:
            if random.random() < storylet.trigger_chance:
                narrative = storylet.narrative
                turns = list(storylet.turns)
                if storylet.is_overheard and storylet.speaker_npc:
                    speaker = shared.world.npcs.get(storylet.speaker_npc)
                    listener = shared.world.npcs.get(storylet.listener_npc) if storylet.listener_npc else None
                    speaker_name = speaker.name if speaker else storylet.speaker_npc
                    listener_name = listener.name if listener else storylet.listener_npc
                    if turns:
                        turns = [
                            {
                                "speaker_npc": turn.get("speaker_npc", ""),
                                "speaker": (shared.world.npcs.get(turn.get("speaker_npc", "")) or turn).name
                                if shared.world.npcs.get(turn.get("speaker_npc", ""))
                                else turn.get("speaker", turn.get("speaker_npc", "")),
                                "text": turn.get("text", ""),
                            }
                            for turn in turns
                        ]
                    elif listener:
                        listener_name = listener.name
                        narrative = f'{speaker_name} says to {listener_name}, "{narrative}"'
                    else:
                        narrative = f'{speaker_name} says, "{narrative}"'

                if storylet.scope == "room":
                    room = shared.world.get_room(player.current_room)
                    if room:
                        shared.active_room_storylets[room.id] = {
                            "storylet_id": storylet.id,
                            "triggered_at": time.time(),
                            "resolved": False,
                            "options": storylet.options,
                            "narrative": narrative,
                            "turns": turns,
                            "owner_username": player.username,
                            "expires_at": time.time() + storylet.timer_seconds,
                        }
                timer_started_at = time.time()
                active = ActiveStorylet(
                    storylet_id=storylet.id,
                    narrative=narrative,
                    options=storylet.options,
                    room_id=player.current_room,
                    timer_duration=storylet.timer_seconds,
                    timer_started_at=timer_started_at,
                    speaker_npc=storylet.speaker_npc,
                    listener_npc=storylet.listener_npc,
                    turns=turns,
                    blocking=storylet.blocking,
                    scope=storylet.scope,
                    owner_username=player.username,
                    expires_at=timer_started_at + storylet.timer_seconds,
                )
                player.active_storylets.append(active)
                return active

    def check_narrative_chain(self, npc_id: str, player, shared) -> Optional[NarrativeChain]:
        for chain in self.narrative_chains.values():
            if chain.trigger != "talk_to":
                continue
            if chain.npc != npc_id:
                continue
            if self._check_chain_preconditions(chain, player, shared):
                return chain
        return None

    def _check_chain_preconditions(self, chain: NarrativeChain, player, shared) -> bool:

        pre = chain.precondition
        trust_min = pre.get("trust_min", {})
        for faction, min_val in trust_min.items():
            from .trust import get_role_trust
            if "." in faction:
                faction_key, role = faction.split(".", 1)
                current = get_role_trust(player.trust, faction_key, role)
            else:
                current = get_role_trust(player.trust, faction)
            if current < min_val:
                return False
        
        for flag in pre.get("flags_required", []):
            if flag not in player.flags:
                return False
        
        for flag in pre.get("flags_missing", []):
            if flag in player.flags:
                return False
        
        return True
        return None