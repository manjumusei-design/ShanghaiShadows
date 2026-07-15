from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import random
import yaml
from pathlib import Path


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
    preconditions: Optional[InteractionPreconditions] = None
    weight: float = 1.0


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

        return NpcInteraction(
            id=interaction_id,
            action=action,
            narrative_templates=data.get("narrative_templates", []),
            effects=effects,
            actor_faction=data.get("actor_faction", []),
            target_faction=data.get("target_faction", []),
            preconditions=preconditions,
            weight=data.get("weight", 1.0),
        )