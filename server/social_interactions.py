from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, mapping

import yaml

from .npc_memory import NpcRelationship
from .victory import _update_district_control



SOCIAL_INTERVAL_MINUTES = (20, 40)
SOCIAL_ACTIONS_PER_TICK = 4
DAILY_DISTRICT_INFLUENCE_CAP = 10
ARCHETYPE_FALLBACKS = {
    "vendor": "Prices change before the sun is properly up",
    "merchant": "Trade survives by keeping its accounts close",
    "worker": "There is work enough for anyone who can keep their footing",
    "default": "The day has its own business",
}


@dataclass
class SocialSchedule:
    next_action_minute: int
    
    @classmethod
    def initial_for(cls, npc_id: str, current_minute: int) -> "SocialSchedule":
        offset = int(hashlib.sha256(npc_id.encode("utf-8")).hexdigest()[:8], 16) % 30
        return cls(next_action_minute=current_minute + offset)
    
    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


def due_npc_ids(schedules: Mapping[str, Mapping[str, int]], current_minute: int, limit: int = SOCIAL_ACTIONS_PER_TICK) -> list[str]:
    due = [npc_id for npc_id, schedule in schedules.items() if int(schedule.get("next_action_minute", 0)) <= current_minute]
    return sorted(due)[:limit]


def reset_social_state(shared) -> None:
    shared.npc_social_schedules = {}
    shared.social_influence_ledger = {}


class SocialDialogueComposer:

    def __init__(self, voice_sheets: Mapping[str, Mapping[str, Any]], dialogue_pools: Mapping[str, Mapping[str, Any]] | None = None):
        self.voice_sheets = voice_sheets
        self.dialogue_pools = dialogue_pools or self._load_dialogue_pools()

    @staticmethod
    def _load_dialogue_pools() -> Mapping[str, Mapping[str, Any]]:
        path = Path(__file__).parent / "data" / "npc_dialogue_pools.yaml"
        return (load_strict_yaml(path) or {}).get("pools", {})

    def compose(self, actor, target, action: str, context: Mapping[str, Any]) -> str:
        return "\n".join(
            f'{turn["speaker"]}: "{turn["text"]}"'
            for turn in self.compose_turns(actor, target, action, context)
        )

    def compose_turns(self, actor, target, action: str, context: Mapping[str, Any]) -> list[Dict[str, Any]]:
        absolute_minute = int(context.get("absolute_minute", 0))
        authored = self._authored_turns(actor, target, absolute_minute)
        if authored:
            return authored
        actor_sheet = self.voice_sheets.get(actor.id, {})
        target_sheet = self.voice_sheets.get(target.id, {})
        actor_line = self._line_for(actor, actor_sheet, action, context)
        target_line = self._reply_for(target, target_sheet, action, context)
        return [
            {"speaker": actor.name, "text": actor_line, "delay_ms": 900},
            {"speaker": target.name, "text": target_line, "delay_ms": 900},
        ]

    def _authored_turns(self, actor, target, absolute_minute: int) -> list[Dict[str, Any]]:
        from .npc import get_npc_archetype

        archetypes = [get_npc_archetype(actor), get_npc_archetype(target)]
        pool = next((candidate for candidate in self.dialogue_pools.values() if isinstance(candidate, Mapping) and candidate.get("archetypes") == archetypes), None)
        if pool is None:
            pool = next((candidate for candidate in self.dialogue_pools.values() if isinstance(candidate, Mapping) and candidate.get("archetypes") == list(reversed(archetypes))), None)
        exchanges = pool.get("exchanges", []) if pool else []
        if not isinstance(exchanges, list) or not exchanges:
            return []
        pool_length = len(exchanges)
        identity = ":".join(sorted((str(actor.id), str(target.id))))
        seed = hashlib.sha256(f"{identity}:{pool_length}".encode("utf-8")).digest()
        exchange_index = (int.from_bytes(seed[:8], "big") + int(absolute_minute)) % pool_length
        exchange = exchanges[exchange_index]
        if not isinstance(exchange, Mapping):
            return []
        lines = exchange.get("lines", [])
        if not isinstance(lines, list) or len(lines) < 4 or not all(isinstance(line, str) and line.strip() for line in lines):
            return []
        actor_line = " ".join(lines[::2])
        target_line = " ".join(lines[1::2])
        return [
            {"speaker": actor.name, "text": actor_line, "delay_ms": 900},
            {"speaker": target.name, "text": target_line, "delay_ms": 900},
        ]

    @staticmethod
    def _line_for(npc, sheet: Mapping[str, Any], action: str, context: Mapping[str, Any]) -> str:
        fingerprints = sheet.get("verbal_fingerprints", [])
        fingerprint = fingerprints[0] if fingerprints else SocialDialogueComposer._archetype_line(npc)
        weather = context.get("weather", "clear")
        if action in {"gossip", "trade_gossip", "exchange_rumors", "share_news"}:
            return f"{fingerprint}. Have you heard how the {weather} has changed the streets?"
        if action in {"argue", "intimidate_rival"}:
            return f"{fingerprint}. Do not mistake caution for agreement."
        return f"{fingerprint}. We should mind the work in front of us."

    @staticmethod
    def _archetype_line(npc) -> str:
        role = (getattr(npc, "role", "") or "").lower()
        if "vendor" in role or "shop" in role:
            return ARCHETYPE_FALLBACKS["vendor"]
        if "merchant" in role or "trader" in role:
            return ARCHETYPE_FALLBACKS["merchant"]
        if "worker" in role or "labor" in role:
            return ARCHETYPE_FALLBACKS["worker"]
        return ARCHETYPE_FALLBACKS["default"]

    @staticmethod
    def _reply_for(npc, sheet: Mapping[str, Any], action: str, context: Mapping[str, Any]) -> str:
        habits = sheet.get("speaking_habits", [])
        habit = habits[0] if habits else "keeps their voice low"
        if action in {"argue", "intimidate_rival"}:
            return "Then say what you mean, and do not make the room guess."
        return f"{npc.name} {habit}, then answers, 'That is enough talk for one day.'"


class SocialInteractionResolver:
    def apply(self, interaction, actor, target, shared, district: str) -> None:
        effects = interaction.effects
        self._apply_relationship(actor, target, effects.relationship_change)
        if effects.memory_exchange:
            self._exchange_memory(actor, target)
        self._apply_mood(effects.mood_change, actor, target)
        self._apply_numeric(effects.courage_change, actor, target, "courage")
        self._apply_numeric(effects.suspicion_increase, actor, target, "suspicion")
        if effects.shared_secret_created:
            self._create_shared_secret(actor, target, interaction.id)
        self._apply_visibility(effects.visibility_change, actor, target)
        self._apply_item_transfer(effects.item_transfer, actor, target)
        self._apply_goal(effects.goal_assigned, actor, target, interaction.id)
        self._apply_district_influence(effects.faction_influence, actor, shared, district)

    @staticmethod
    def _apply_relationship(actor, target, change: int) -> None:
        if not change:
            return
        relationship = actor.relationships.get(target.id)
        if relationship is None:
            relationship = NpcRelationship(actor.id, target.id, "acquaintance", 10, [])
            actor.relationships[target.id] = relationship
            target.relationships[actor.id] = relationship
        relationship.strength = max(0, min(100, relationship.strength + change))
        if relationship.strength >= 80:
            relationship.relationship_type = "close_friend"
        elif relationship.strength >= 60:
            relationship.relationship_type = "friend"
        elif relationship.strength <= 20:
            relationship.relationship_type = "enemy"
        elif relationship.strength <= 40:
            relationship.relationship_type = "rival"

    @staticmethod
    def _exchange_memory(actor, target) -> None:
        if actor.memory:
            memory = actor.memory[-1]
            if memory not in target.memory:
                target.memory.append(memory)
        if target.memory:
            memory = target.memory[-1]
            if memory not in actor.memory:
                actor.memory.append(memory)

    @staticmethod
    def _apply_mood(values: Mapping[str, str], actor, target) -> None:
        for role, mood in values.items():
            npc = actor if role == "actor" else target if role == "target" else None
            if npc:
                npc.mood = mood

    @staticmethod
    def _apply_numeric(values: Mapping[str, int], actor, target, attribute: str) -> None:
        for role, change in values.items():
            npc = actor if role == "actor" else target if role == "target" else None
            if npc:
                setattr(npc, attribute, max(0, min(100, getattr(npc, attribute, 50) + int(change))))

    @staticmethod
    def _create_shared_secret(actor, target, interaction_id: str) -> None:
        relationship = actor.relationships.get(target.id)
        if relationship is None:
            relationship = NpcRelationship(actor.id, target.id, "acquaintance", 10, [])
            actor.relationships[target.id] = relationship
            target.relationships[actor.id] = relationship
        if interaction_id not in relationship.shared_secrets:
            relationship.shared_secrets.append(interaction_id)

    @staticmethod
    def _apply_visibility(values: Mapping[str, str], actor, target) -> None:
        for role, value in values.items():
            npc = actor if role == "actor" else target if role == "target" else None
            if npc:
                npc.social_visibility = value

    @staticmethod
    def _apply_item_transfer(values: Mapping[str, Any], actor, target) -> None:
        item_id = values.get("item_id") if values else None
        direction = values.get("direction", "actor_to_target") if values else ""
        if not item_id:
            return
        source, recipient = (actor, target) if direction == "actor_to_target" else (target, actor)
        for item in list(source.inventory):
            if (item.get("id") if isinstance(item, dict) else getattr(item, "id", None)) == item_id:
                source.inventory.remove(item)
                recipient.inventory.append(item)
                return

    @staticmethod
    def _apply_goal(enabled: bool, actor, target, interaction_id: str) -> None:
        if enabled:
            target.goals.append({"source": interaction_id, "assigned_by": actor.id})

    @staticmethod
    def _apply_district_influence(values: Mapping[str, int], actor, shared, district: str) -> None:
        for faction_key, amount in values.items():
            faction = actor.faction if faction_key == "actor_faction" else faction_key
            if faction not in {"ccp", "gmd"}:
                continue
            ledger = getattr(shared, "social_influence_ledger", None)
            if ledger is None:
                ledger = shared.social_influence_ledger = {}
            key = f"{shared.game_time.day}:{district}:{faction}"
            already_applied = int(ledger.get(key, 0))
            remaining = max(0, DAILY_DISTRICT_INFLUENCE_CAP - already_applied)
            applied = min(max(0, int(amount)), remaining)
            if not applied:
                continue
            district_values = shared.district_influence.setdefault(district, {})
            district_values[faction] = max(0, min(100, district_values.get(faction, 0) + applied))
            _update_district_control(district, shared)
            ledger[key] = already_applied + applied
