from dataclasses import dataclass, field
from typing import Any, Dict, list, Optional
import random


@dataclass
class PlayerMemory:
    player_name: str
    interactions: List[Dict[str, Any]] = field(default_factory=list)
    trust_mod: int = 0
    relationship_type: str = "neutral"
    last_interaction_day: int = 0
    remembered_events: List[str] = field(default_factory=list)
    origin_storylet: str = "" 
    origin_choice: int = 0  
    met_locations: List[str] = field(default_factory=list) 


@dataclass
class NpcRelationship:
    npc_id_1: str
    npc_id_2: str
    relationship_type: str
    strength: int
    shared_secrets: List[str] = field(default_factory=list)


class NpcMemorySystem:
    RELATIONSHIP_CHANGES = {
        'helped': ('friend', 10),
        'saved_life': ('friend', 30),
        'gave_gift': ('friend', 5),
        'protected': ('protector', 20),
        'spared': ('debtor', 15),

        'betrayed': ('enemy', -20),
        'attacked': ('enemy', -15),
        'threatened': ('enemy', -10),

        'traded': ('neutral', 1),
        'talked': ('neutral', 1),
        'shared_meal': ('friendly', 5),

        'witnessed_crime': ('hostile', -5),
        'witnessed_murder': ('enemy', -15),
        'witnessed_theft': ('hostile', -8),
        'witnessed_attack': ('hostile', -10),
        'witnessed_kill': ('hostile', -15),
        'caught_pickpocketing': ('enemy', -15),
        'spotted_tailing': ('hostile', -10),
        'spotted_hiding': ('hostile', -5),
        'observed_curfew_violation': ('hostile', -3),
        'observed_suspicious_behavior': ('hostile', -3),

        'harmed_friend': ('enemy', -15),
        'helped_against_enemy': ('friend', 10),

        'pickpocketed': ('hostile', -3),  
        'deceived': ('hostile', -8),
    }

    def record_interaction(self, npc, player_name: str, interaction_type: str,
                          details: Dict[str, Any], current_day: int) -> None:
        from .npc import Npc
        from .constants import NPC_MEMORY_MAXLEN

        if player_name not in npc.player_memories:
            npc.player_memories[player_name] = PlayerMemory(
                player_name=player_name,
                interactions=[],
                trust_mod=0,
                relationship_type="neutral",
                last_interaction_day=0,
                remembered_events=[],
                origin_storylet="",
                origin_choice=0,
                met_locations=[]
            )

            memory = npc.player_memories[player_name]
            memory.interactions.append({
            'type': interaction_type,
            'day': current_day,
            'details': details
        })
        memory.last_interaction_day = current_day

        if len(memory.interactions) > NPC_MEMORY_MAXLEN:
            memory.interactions = memory.interactions[-NPC_MEMORY_MAXLEN:]
        self._update_relationship(memory, interaction_type)

    def _update_relationship(self, memory: PlayerMemory, interaction_type: str) -> None:
        if interaction_type not in self.RELATIONSHIP_CHANGES:
            return
        
        new_type, mod = self.RELATIONSHIP_CHANGES[interaction_type]
        memory.trust_mod += mod

        if memory.trust_mod >= 30:
            memory.relationship_type = "friend"
        elif memory.trust_mod <= -30:
            memory.relationship_type = "enemy"
        elif memory.trust_mod >= 10:
            memory.relationship_type = "friendly"
        elif memory.trust_mod <= -10:
            memory.relationship_type = "hostile"

    def get_player_specific_dialogue(self, npc, player_name: str, bucket: str,
                                     current_day: int) -> List[str]:
        memory = npc.player_memories.get(player_name)

        if not memory:
            return npc.dialogue.get(bucket, [])
        
        recent = [i for i in memory.interactions if current_day - i['day'] < 7]

        contextual_lines = []
        for interaction in recent[-3:]:
            if interaction['type'] == 'helped':
                what = interaction['details'].get('what', 'something')
                contextual_lines.append(f"You helped me with {what} recently. I won't forget.")
            elif interaction['type'] == 'betrayed':
                contextual_lines.append("After what you did, I don't trust you.")
            elif interaction['type'] == 'saved_life':
                contextual_lines.append("You saved my life. I owe you everything.")
            elif interaction['type'] == 'gave_gift':
                gift = interaction['details'].get('item', 'something')
                contextual_lines.append(f"The {gift} you gave me was thoughtful.")

        bucket_for_relationship = self._get_bucket_for_relationship(memory.relationship_type, bucket)
        base_dialogue = npc.dialogue.get(bucket_for_relationship, npc.dialogue.get(bucket, []))

        return contextual_lines + base_dialogue