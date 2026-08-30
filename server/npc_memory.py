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

    def _get_bucket_for_relationship(self, relationship_type: str, requested_bucket: str) -> str:
        if relationship_type == "friend":
            return "friendly"
        elif relationship_type == "enemy":
            return "hostile"
        elif relationship_type == "debtor" or relationship_type == "protector":
            return "friendly"
        elif relationship_type == "friendly":
            return "friendly"
        elif relationship_type == "hostile":
            return "hostile"
        return requested_bucket

    def get_trust_mod_for_player(self, npc, player_name: str) -> int:
        memory = npc.player_memories.get(player_name)
        if memory:
            return memory.trust_mod
        return 0


class NpcRelationshipSystem:

    def load_relationships(self, relationships_data: List[Dict], npcs: Dict) -> None:
        from .npc import Npc

        for rel_data in relationships_data:
            npc1_id = rel_data.get('npc_1')
            npc2_id = rel_data.get('npc_2')

            if npc1_id not in npcs or npc2_id not in npcs:
                continue

            npc1 = npcs[npc1_id]
            npc2 = npcs[npc2_id]

            relationship = NpcRelationship(
                npc_id_1=npc1_id,
                npc_id_2=npc2_id,
                relationship_type=rel_data.get('type', 'acquaintance'),
                strength=rel_data.get('strength', 50),
                shared_secrets=rel_data.get('shared_secrets', [])
            )

            npc1.relationships[npc2_id] = relationship
            npc2.relationships[npc1_id] = relationship

    def process_npc_interaction(self, npc1, npc2, interaction_type: str) -> None:
        from .npc import Npc

        if npc2.id not in npc1.relationships:
            relationship = NpcRelationship(
                npc_id_1=npc1.id,
                npc_id_2=npc2.id,
                relationship_type="acquaintance",
                strength=10,
                shared_secrets=[]
            )
            npc1.relationships[npc2.id] = relationship
            npc2.relationships[npc1.id] = relationship

        relationship = npc1.relationships[npc2.id]

        strength_changes = {
            'helped': 5,
            'argued': -10,
            'shared_secret': 15,
            'gossip': 2,
            'fought': -20,
        }

        if interaction_type in strength_changes:
            relationship.strength = max(0, min(100,
                relationship.strength + strength_changes[interaction_type]))

        if relationship.strength >= 80:
            relationship.relationship_type = "close_friend"
        elif relationship.strength >= 60:
            relationship.relationship_type = "friend"
        elif relationship.strength <= 20:
            relationship.relationship_type = "enemy"
        elif relationship.strength <= 40:
            relationship.relationship_type = "rival"

    def get_relationship(self, npc_id_1: str, npc_id_2: str) -> Optional[NpcRelationship]:
        from .game_world import SharedWorldState
        npc1 = None
        if hasattr(self, '_npcs'):
            npc1 = self._npcs.get(npc_id_1)
        if npc1 and npc_id_2 in npc1.relationships:
            return npc1.relationships[npc_id_2]
        return None

    async def npc_react_to_player_action(self, player_name: str, action: str,
                                         target_npc, witnesses: List,
                                         memory_system: NpcMemorySystem,
                                         current_day: int) -> None:
        for witness in witnesses:
            if target_npc.id not in witness.relationships:
                continue

            rel = witness.relationships[target_npc.id]

            if rel.relationship_type in ["friend", "family", "close_friend"]:
                memory_system.record_interaction(
                    witness, player_name, "harmed_friend",
                    {'friend': target_npc.id, 'action': action},
                    current_day
                )
            elif rel.relationship_type in ["enemy", "rival"]:
                # Witness is pleased or neutral
                memory_system.record_interaction(
                    witness, player_name, "helped_against_enemy",
                    {'enemy': target_npc.id, 'action': action},
                    current_day
                )

    def _adjust_relationship(self, npc_a: str, npc_b: str, delta: int, shared) -> None:
        npc = shared.world.npcs.get(npc_a)
        if npc and npc_b in npc.relationships:
            rel = npc.relationships[npc_b]
            rel.strength = max(-100, min(100, rel.strength + delta))

    def evolve_relationships(self, npc_id: str, event_type: str, context: dict, shared) -> None:
        if event_type == "npc_killed":
            victim_id = context.get("victim_id")
            killer_id = context.get("killer_id")
            if not victim_id or not killer_id:
                return
            for npc in shared.world.npcs.values():
                if victim_id not in npc.relationships:
                    continue
                rel = npc.relationships[victim_id]
                if rel.strength >= 30:
                    self._adjust_relationship(npc.id, killer_id, -30, shared)
                elif rel.strength <= -20:
                    self._adjust_relationship(npc.id, killer_id, 20, shared)

        elif event_type == "defection":
            defector_id = context.get("npc_id")
            old_faction = context.get("old_faction")
            if not defector_id or not old_faction:
                return
            for npc in shared.world.npcs.values():
                if npc.id == defector_id:
                    continue
                if defector_id not in npc.relationships:
                    continue
                if getattr(npc, 'faction', '') == old_faction:
                    self._adjust_relationship(defector_id, npc.id, -20, shared)


class NpcBehaviorSystem:
    def generate_goals(self, npc, world_state) -> List[str]:
        goals = []

        if npc.hp < 50:
            goals.append("seek_medical_help")

        world_tension = (getattr(world_state, 'ccp_influence', 0) + getattr(world_state, 'gmd_influence', 0)) / 2
        kempeitai_power = getattr(world_state, 'kempeitai_influence', 20)
        gang_power = getattr(world_state, 'gang_influence', 15)

        if npc.faction == "kempeitai":
            goals.append("patrol_territory")
            if world_tension > 40:
                goals.append("tighten_security")
            if kempeitai_power > 60:
                goals.append("conduct_raid")
            if getattr(npc, 'suspicion', 0) > 50:
                goals.append("investigate_suspicion")
        elif npc.faction == "ccp":
            goals.append("build_resistance_network")
            if world_tension > 50:
                goals.append("recruit_sympathizers")
            if kempeitai_power > 70:
                goals.append("avoid_detection")
            if gang_power < 20:
                goals.append("forge_gang_alliance")
        elif npc.faction == "gmd":
            goals.append("coordinate_with_chungking")
            if world_tension > 60:
                goals.append("prepare_operation")
            if kempeitai_power < 40:
                goals.append("expand_influence")
        elif npc.faction == "green_gang":
            goals.append("maintain_territory")
            if gang_power > 25:
                goals.append("expand_racket")
            if world_tension > 50:
                goals.append("protect_operations")
            if kempeitai_power > 60:
                goals.append("bribe_authority")
        elif npc.faction == "civilian":
            if world_tension > 50 and getattr(npc, 'courage', 50) < 40:
                goals.append("avoid_danger_areas")
            if getattr(npc, 'role', '') == "vendor":
                if world_tension > 60:
                    goals.append("consider_shuttering")
                else:
                    goals.append("restock_shop")

        for npc_id, relationship in npc.relationships.items():
            if hasattr(relationship, 'relationship_type'):
                rel_type = relationship.relationship_type
                strength = getattr(relationship, 'strength', 50)
                if rel_type in ["family", "close_friend"] and strength < 30:
                    goals.append(f"help_{npc_id}")
                elif rel_type == "enemy" and random.random() < 0.3:
                    goals.append(f"undermine_{npc_id}")

        for player_name, memory in npc.player_memories.items():
            if hasattr(memory, 'relationship_type'):
                rel_type = memory.relationship_type
                trust_mod = getattr(memory, 'trust_mod', 0)
                if rel_type == "debtor":
                    goals.append(f"repay_debt_to_{player_name}")
                elif rel_type == "enemy" and trust_mod < -20:
                    goals.append(f"avoid_{player_name}")
                elif rel_type == "trusted_contact" and trust_mod > 30:
                    goals.append(f"share_intel_with_{player_name}")

        return goals[:5]

    def create_plan(self, goal: str, npc, world_state) -> str:
        goal_plans = {
            "seek_medical_help": "go_to_clinic",
            "patrol_territory": "follow_schedule",
            "investigate_suspicion": "visit_last_crime_scene",
            "build_resistance_network": "talk_to_potential_recruits",
            "maintain_territory": "collect_protection_money",
            "tighten_security": "increase_patrol_frequency",
            "conduct_raid": "move_to_target_area",
            "recruit_sympathizers": "seek_disgruntled_civilians",
            "avoid_detection": "stay_in_safehouse",
            "forge_gang_alliance": "approach_gang_contact",
            "coordinate_with_chungking": "check_dead_drop",
            "prepare_operation": "gather_supplies",
            "expand_influence": "visit_new_district",
            "expand_racket": "identify_new_targets",
            "protect_operations": "move_assets",
            "bribe_authority": "seek_kempeitai_contact",
            "avoid_danger_areas": "stay_in_safe_zone",
            "consider_shuttering": "evaluate_tension",
            "restock_shop": "visit_supplier",
        }

        if goal.startswith("help_"):
            return f"visit_{goal[5:]}"
        elif goal.startswith("undermine_"):
            return f"spread_rumor_about_{goal[9:]}"
        elif goal.startswith("repay_debt_to_"):
            return f"seek_{goal[14:]}"
        elif goal.startswith("avoid_"):
            return "flee_to_safe_location"
        elif goal.startswith("share_intel_with_"):
            return "wait_for_contact"

        return goal_plans.get(goal, "follow_schedule")


npc_memory_system = NpcMemorySystem()
npc_relationship_system = NpcRelationshipSystem()
npc_behavior_system = NpcBehaviorSystem()