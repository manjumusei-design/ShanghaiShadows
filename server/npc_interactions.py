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

