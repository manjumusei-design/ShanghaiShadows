from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import random
import yaml
from pathlib import Path


def _optional_nonnegative_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    return max(0, int(value))


@dataclass
class InteractionEffects:
    relationship_change: int = 0
    mood_change: Dict[str, str] = field(default_factory=dict)  
    courage_change: Dict[str, int] = field(default_factory=dict)  
    suspicion_increase: Dict[str, int] = field(default_factory=dict) 
    memory_exchange: bool = False
    rumor_propagation: bool = False
    shared_secret_created: bool = False
    goal_assigned: bool = False
    faction_influence: Dict[str, int] = field(default_factory=dict)
    visibility_change: Dict[str, str] = field(default_factory=dict)
    item_transfer: Dict[str, Any] = field(default_factory=dict) 


@dataclass
class InteractionPreconditions:
    min_world_tension: Optional[int] = None
    max_world_tension: Optional[int] = None
    opposite_factions: bool = False
    leader_status: bool = False
    min_relationship: Optional[int] = None
    max_relationship: Optional[int] = None
    requires_item: Optional[str] = None
    requires_goal: Optional[str] = None


@dataclass
class NpcInteraction:
    id: str
    action: List[str]
    narrative_templates: List[str]
    effects: InteractionEffects
    actor_faction: List[str] = field(default_factory=list)
    target_faction: List[str] = field(default_factory=list)
    districts: List[str] = field(default_factory=list)
    preconditions: Optional[InteractionPreconditions] = None
    weight: float = 1.0
    consequence_class: str = "ambient"
    consequence_category: str = ""
    consequence_duration: int = 0
    follow_up_key: Optional[str] = None
    consequence_cooldown: Optional[int] = None
    consequence_room_cap: Optional[int] = None
    consequence_district_cap: Optional[int] = None
    consequence_rumour: Optional[str] = None
    consequence_room_manifestation: Optional[str] = None
    consequence_ask_topic: Optional[str] = None
    consequence_ask_response: Optional[str] = None
    follow_up_delay: int = 30
    consequence_visibility: str = "local"
    follow_up_trust_ranges: Dict[str, List[int]] = field(default_factory=dict)


class NpcInteractionManager:
    def __init__(self):
        self._interactions: Dict[str, NpcInteraction] = {}
        self._action_index: Dict[str, List[str]] = {}
        self._faction_index: Dict[str, List[str]] = {}

    def load_interactions(self, path: str) -> None:
        yaml_path = Path(path)
        if not yaml_path.exists():
            return
        
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for interaction_data in data.get("interactions", []):
            interaction = self._parse_interaction(interaction_data)
            if interaction:
                self._interactions[interaction.id] interaction
                self._index_interaction(interaction)

    def _parse_interaction(self, data: Dict) -> Optional[NpcInteraction]:
        interaction_id = data.get("id")
        if not interaction_id:
            return None
        
        action = data.get("action", {})
        if isinstance(action, str):
            action = [action]

        effects_data = data.get("effects", {})
        effects = InteractionEffects(
            relationship_change=effects_data.get("relationship_change", 0),
            mood_change=effects_data.get("mood_change", {}),
            courage_change=effects_data.get("courage_change", {}),
            suspicion_increase=effects_data.get("suspicion_increase", {}),
            memory_exchange=effects_data.get("memory_exchange", False),
            rumor_propagation=effects_data.get("rumor_propagation", False),
            shared_secret_created=effects_data.get("shared_secret_created", False),
            goal_assigned=effects_data.get("goal_assigned", False),
            faction_influence=effects_data.get("faction_influence", {}),
            visibility_change=effects_data.get("visibility_change", {}),
            item_transfer=effects_data.get("item_transfer", {}),
        )

        preconditions = None
        precond_data = data.get("preconditions")
        if precond_data:
            preconditions = InteractionPreconditions(
                min_world_tension=precond_data.get("min_world_tension"),
                max_world_tension=precond_data.get("max_world_tension"),
                opposite_factions=precond_data.get("opposite_factions", False),
                leader_status=precond_data.get("leader_status", False),
                min_relationship=precond_data.get("min_relationship"),
                max_relationship=precond_data.get("max_relationship"),
                requires_item=precond_data.get("requires_item"),
                requires_goal=precond_data.get("requires_goal"), 
            )

        consequence_class = str(data.get("consequence_class", "ambient")).lower()
        if consequence_class not in {"ambient", "persistent", "actionable"}:
            consequence_class = "ambient"
        consequence_visibility = str(data.get("consequence_visibility", "local")).lower()
        if consequence_visibility not in {"local", "rumour", "hidden":
            consequence_visibility = "local"

        return NpcInteraction(
            id=interaction_id,
            action=action,
            narrative_templates=data.get("narrative_templates", []),
            effects=effects,
            actor_faction=data.get("actor_faction", []),
            target_faction=data.get("target_faction", []),
            districts=data.get("districts", []),
            preconditions=preconditions,
            weight=data.get("weight", 1.0),
            consequence_class=consequence_class,
            consequence_category=str(data.get("consequence_category", "")),
            consequence_duration=max(0, int(data.get("consequence_duration", 0) or 0)),
            follow_up_key=data.get("follow_up_key"),
            consequence_cooldown=_optional_nonnegative_int(data.get("consequence_cooldown")),
            consequence_room_cap=_optional_nonnegative_int(data.get("consequence_room_cap")),
            consequence_district_cap=_optional_nonnegative_int(data.get("consequence_district_cap")),
            consequence_rumour=data.get("consequence_rumour"),
            consequence_room_manifestation=data.get("consequence_room_manifestation"),
            consequence_ask_topic=data.get("consequence_ask_topic"),
            consequence_ask_response=data.get("consequence_ask_response"),
            follow_up_delay=max(0, int(data.get("follow_up_delay", 30) or 0)),
            consequence_visibility=consequence_visibility,
            follow_up_trust_ranges={key: list(bounds) for key, bounds in data.get("follow_up_trust_ranges", {}).items()},
        )
    
    def _index_interaction(self, interaction: NpcInteraction) -> None:
        for action in interaction.action:
            if action not in self._action_index:
                self._action_index[action] = []
            self._action_index[action].append(interaction.id)

        for faction in interaction.actor_faction:
            if faction not in self._faction_index:
                self._faction_index[faction] = []
            if interaction.id not in self._faction_index[faction]:
                self._faction_index[faction].append(interaction.id)

    def get_interactions_for_action(self, action: str) -> List[NpcInteraction]:
        ids = self._action_index.get(action, [])
        return [self._interactions[i] for i in ids if i in self._interactions]
    
    def get_interactions_for_faction(self, faction: str) -> List[NpcInteraction]:
        ids = self._faction_index.get(faction, [])
        return [self._interactions[i] for i in ids if i in self._interactions]
    
    def check_preconditions(self, interaction: NpcInteraction, actor, target,
                           world_state) -> bool:
        if interaction.districts and getattr(world_state, "district", "") not in interaction.districts:
            return False
        precond = interaction.preconditions
        if not precond:
            return True
        
        if precond.min_world_tension is not None:
            tension = getattr(world_state, 'world_tension', 0)
            if tension < precond.min_world_tension:
                return False
            
        if precond.max_world_tension is not None:
            tension = getattr(world_state, 'world_tension', 0)
            if tension > precond.max_world_tension:
                return False
            
        if precond.opposite_factions:
            if actor.faction == target.faction:
                return False

        if precond.leader_status:
            if not getattr(actor, 'faction_leader', False):
                return False

        if precond.min_relationship is not None:
            rel = actor.relationships.get(target.id)
            if not rel or rel.strength < precond.min_relationship:
                return False

        if precond.max_relationship is not None:
            rel = actor.relationships.get(target.id)
            if rel and rel.strength > precond.max_relationship:
                return False

        if precond.requires_item:
            if precond.requires_item not in getattr(actor, 'inventory', []):
                return False

        if precond.requires_goal:
            if precond.requires_goal not in getattr(actor, 'goals', []):
                return False

        return True
    
    def check_faction_filter(self, interaction: NpcInteraction, actor, target) -> bool:
        if interaction.actor_faction:
            if actor.faction not in interaction.actor_faction:
                return False
            
            if interaction.target_faction:
                if target.gaction not in interaction.target_faction:
                    return False
                
        return True
    
    def select__interaction(self, action: str, actor, target) -> Optional[NpcInteraction]:
        candidates = self.get_interactions_for_action(action)
        if not candidates:
            return None
        
        valid = []
        for interaction in candidates:
            if not self.check_faction_filter(interaction, actor, target):
                continue
            if not self.check_preconditions(interaction, actor, target, world_state):
                continue
            valid.append(interaction)

            if not valid:
                return None
            
            if len(valid) == 1:
                return valid[0]
            
            total_weight = sum(i.weight for i in valid)
            roll = random.random() * total_weight
            cumulative = 0.0
            for interaction in valid:
                cumulative += interaction.weight
                if roll <= cumulative:
                    return interaction
            
            return valid[-1]
        
    def render_narrative(self, interaction: NpcInteraction,  actor, target, extra_context: Optional[Dict] = None) -> str:
        template = random.choice(interaction.narrative_templates)

        direction = ""
        if extra_context:
            direction = extra_context.get("direction", "")

            rendered = template.format(
                actor=actor.name,
                target=target.name,
                actor_faction=actor.faction,
                target_faction=target.faction,
                direction=direction,
            )

            return rendered
        
    def get_interasction(self, interaction_id: str) -> Optional[NpcInteraction]:
        return self._interactions.get(interaction_id)
    
    def get_all_interactions(self) -> List[NpcInteraction]:
        return list(self._interactions.values())
    
    
npc_interaction_manager = NpcInteractionManager()


def load_npc_interactions(path: str = "server/data/npc_interactions.yaml") -> NpcInteractionManager:
    npc_interaction_manager.load_interactions(path)
    return npc_interaction_manager


from .constants import NPC_INTERACTIONS_PATH
load_npc_interactions(NPC_INTERACTIONS_PATH)