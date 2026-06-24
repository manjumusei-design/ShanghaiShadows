from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import random


@dataclass
class PlayerMemory:
    player_name: str
    interactions: List[Dict[str, Any]] = field(default_factory=list)
    trust_mod: int = 0
    relationship_type: str = "neutral"
    last_interaction_day: int = 0
    remembered_events: List[str] = field(default_factory=list)


@dataclass
class NPCRelationship:
    npc_id_1: str
    npc_id_2: str
    relationship_type: str # Here the possible strings are family, friend, rival, enemy, colleague
    strength: int
    shared_secrets: List[str] = field(default_factory=list)


class NpcMemorySystem:
    RELATIONSHIP_CHANGES = {
        'helped': ('friend', 10),
        'saved_life': ('friend', 30),
        'gave_gift': ('friend', 5),
        'betrayed': ('enemy', -20),
        'attacked': ('enemy', -15),
        'threatened': ('enemy', -10),
        'traded': ('neutral', 1),
        'talked': ('neutral', 1),
        'spared': ('debtor', 15),
        'protected': ('protector', 20),
    }

    def record_interaction(self, npc, player_name: str, interaction_type: str,
                          details: Dict[str, Any], current_day: int) -> None:
        from .npc import Npc
        from .constants import NPC_MEMORY_MAXLEN

        if player_name not in npc.player_memories:
            npc.player_memories not in npc.player_memories:
            npc.player_memories[player_name] = PlayerMemory(
                player_name=player_name,
                interactions=[],
                trust_mod=0,
                relationship_type="neutral",
                last_interaction_day=0,
                remembered_events=[]
            )
        memory = npc.player_memories[player_name]
        memory.interactions.append({
            'type': interaction_type,
            'day': current_day,
            'details': details
        })
        memory.last_interaction_day = current_day

        if len(*memory.interactions) > NPC_MEMORY_MAXLEN: #kept on filling up server resources and crashing lol
            memory.interactions = memory.interactionsp[-NPC_MEMORY_MAXLEN:]
        self._update_relationship(memory, interaction_type)

    def _update_relationship(self, memory: PlayerMemory, interaction_type: str) -> None:
        if interaction_type not in self.RELATIONSHIP_CHANGES:
            return
        
        new_type, mod = self.RELATIONSHIP_CHANGES