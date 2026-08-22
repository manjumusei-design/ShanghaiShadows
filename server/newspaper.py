import asyncio
import copy
import random
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime

from .economy import can_afford_fabi, spend_fabi_value

if TYPE_CHECKING:
    from .ai_client import AIClient


NEWSPAPER_COST_FABI = 3
NEWSPAPER_MASTHEAD = "弄堂消息"
NEWSPAPER_SUBTITLE = "LONGTANG XIAOSHUO"
NEWSPAPER_DATE_FORMAT = "Day {day}"


NEWSPAPER_INCIDENT_FRESHNESS_DAYS = 2


def _incident_is_fresh(day_value: Any, game_day: int) -> bool:
    try:
        event_day = int(day_value)
    except (TypeError, ValueError):
        return False
    return event_day >= 1 and game_day - NEWSPAPER_INCIDENT_FRESHNESS_DAYS < event_day <= game_day


def _get_district_display(district: str) -> str:
    district_names = {
        "bund": "the Bund",
        "french": "French Concession",
        "old_city": "Nanshi",
        "docks": "Yangtzepoo",
        "commercial": "Nanking Road",
        "residential": "the lanes",
        "warehouse": "the godowns",
        "hongkou": "Hongkou",
        "school": "the school district",
        "church": "Zikawei",
    }
    return district_names.get(district, district)


def _format_npc_death_record(record: Dict[str, Any]) -> str:
    victim = record.get("npc_name") or record.get("npc_id", "someone")
    return f"Violence in the lanes. {str(victim).replace('_', ' ').title()} found dead."


def _format_world_decision(decision: Dict[str, Any]) -> Optional[str]:
    decision_type = decision.get("decision_type", "")
    actor_npc_id = decision.get("actor_npc_id", "someone")
    effects = decision.get("effects", {})

    if decision_type == "vendor_shutter":
        return f"A shopkeeper on {_get_district_display(effects.get('district', 'unknown'))} closes early. Tension rises."
    elif decision_type == "defection":
        return f"Word is {actor_npc_id.replace('_', ' ').title()} has made new arrangements."
    elif decision_type == "extortion":
        return f"Protection money collected on {_get_district_display(effects.get('district', 'unknown'))}."
    return None


async def _ai_enhance_incident(ai_client: Optional["AIClient"], incident: str, game_day: int) -> str:
    if not ai_client:
        return incident
    
    prompt = f"""You are a newspaper editor in 1930s Shanghai. Enhance this brief incident report with atmospheric period detail. Keep it concise (1-2 sentences max). Maintain the original meaning but add flavor.

Original: {incident}

Enhanced version:"""

    try:
        enhanced = await ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=3.0)
        if enhanced and len(enhanced) < 300:
            return enhanced.strip()
    except Exception:
        pass
    return incident


async def _ai_enhance_rumor(ai_client: Optional["AIClient"], rumor: str, distortion_level: float = 0.3) -> str:
    if not ai_client:
        return _distort_rumor(rumor, distortion_level)
    
    prompt = f"""You are a gossip columnist for a Shanghai tabloid in the 1930s. Rewrite this rumor with an air of mystery and hearsay. Add phrases like "word is", "they say", "reportedly", or "some claim". Keep the core meaning but make it sound like whispered gossip. Stay under 40 words.

Original: {rumor}

Gossip version:"""

    try:
        enhanced = await ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=3.0)
        if enhanced and len(enhanced) < 250:
            return enhanced.strip()
    except Exception:
        pass
    return _distort_rumor(rumor, distortion_level)


def _distort_rumor(rumor_text: str, distortion_level: float = 0.3) -> str:
    words = rumor_text.split()
    if len(words) < 5:
        return rumor_text
    
    distortions = [
        ("says", "claims"),
        ("seen", "reportedly seen"),
        ("was", "may have been"),
        ("is", "is said to be"),
        ("took", "allegedly took"),
        ("found", "reportedly found"),
    ]
    
    distorted = words.copy()
    for i, word in enumerate(distorted):
        if random.random() < distortion_level:
            lower = word.lower().rstrip(".,")
            for old, new in distortions:
                if lower == old:
                    distorted[i] = new + (word[-1] if word[-1] in ".," else "")
                    break
    
    return " ".join(distorted)


def _select_rumors_for_newspaper(
    all_rumors: List[Dict[str, Any]],
    active_rumor_ids: List[str],
    player_district: str,
    max_rumors: int = 5,
) -> List[Dict[str, Any]]:
    if not all_rumors:
        return []
    
    scored_rumors = []
    for rumor in all_rumors:
        rumor_id = rumor.get("id", "")
        score = 0
        if rumor_id in active_rumor_ids:
            score += 10
        
        districts = rumor.get("districts", [])
        if player_district in districts:
            score += 5
        score += random.randint(0, 3)
        scored_rumors.append((score, rumor))
    scored_rumors.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored_rumors[:max_rumors]]


async def generate_newspaper(
    game_day: int,
    player_district: str,
    all_rumors: List[Dict[str, Any]],
    active_rumor_ids: List[str],
    world_decisions: List[Dict[str, Any]],
    rumour_mill: Dict[str, List[str]],
    ai_client: Optional["AIClient"] = None,
    named_npc_deaths: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    selected_rumors = _select_rumors_for_newspaper(
        all_rumors, active_rumor_ids, player_district, max_rumors=5
    )

    teahouse_talk = []
    for rumor in selected_rumors[:2]:
        original = rumor.get("text", "")
        enhanced = await _ai_enhance_rumor(ai_client, original, distortion_level=0.4)
        teahouse_talk.append(enhanced)

    notable_incidents = []
    for npc_id, record in sorted((named_npc_deaths or {}).items()):
        if not _incident_is_fresh(record.get("day"), game_day):
            continue
        incident = _format_npc_death_record(record)
        if incident and incident not in notable_incidents:
            enhanced = await _ai_enhance_incident(ai_client, incident, game_day)
            if enhanced and enhanced not in notable_incidents:
                notable_incidents.append(enhanced)
    for decision in world_decisions[-5:]:
        if not _incident_is_fresh(decision.get("day"), game_day):
            continue
        incident = _format_world_decision(decision)
        if incident and incident not in notable_incidents:
            enhanced = await _ai_enhance_incident(ai_client, incident, game_day)
            if enhanced and enhanced not in notable_incidents:
                notable_incidents.append(enhanced)
    notable_incidents = notable_incidents[:3]
    
    lane_whispers = []
    all_street_rumors = []
    for faction, rumors in rumour_mill.items():
        all_street_rumors.extend(rumors)
    
    if all_street_rumors:
        sampled = random.sample(all_street_rumors, min(3, len(all_street_rumors)))
        for rumor in sampled:
            enhanced = await _ai_enhance_rumor(ai_client, rumor, distortion_level=0.5)
            lane_whispers.append(f"Heard that {enhanced.lower()}")
    
    newspaper = {
        "day": game_day,
        "masthead": NEWSPAPER_MASTHEAD,
        "subtitle": NEWSPAPER_SUBTITLE,
        "date": NEWSPAPER_DATE_FORMAT.format(day=game_day),
        "teahouse_talk": teahouse_talk,
        "notable_incidents": notable_incidents,
        "lane_whispers": lane_whispers,
        "purchased_at": datetime.now().isoformat(),
    }
    return newspaper


async def _resolve_shared_edition(
    shared: Any,
    game_day: int,
    player_district: str,
    all_rumors: List[Dict[str, Any]],
    active_rumor_ids: List[str],
    world_decisions: List[Dict[str, Any]],
    rumour_mill: Dict[str, List[str]],
    ai_client: Optional["AIClient"],
    named_npc_deaths: Optional[Dict[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if shared is None:
        return await generate_newspaper(
            game_day=game_day,
            player_district=player_district,
            all_rumors=all_rumors,
            active_rumor_ids=active_rumor_ids,
            world_decisions=world_decisions,
            rumour_mill=rumour_mill,
            ai_client=ai_client,
            named_npc_deaths=named_npc_deaths,
        )

    edition_lock = getattr(shared, "_newspaper_edition_lock", None)
    if edition_lock is None:
        edition_lock = asyncio.Lock()
        shared._newspaper_edition_lock = edition_lock
    async with edition_lock:
        cached = getattr(shared, "newspaper_edition", None)
        if getattr(shared, "newspaper_edition_day", 0) == game_day and isinstance(cached, dict):
            return cached
        generated = await generate_newspaper(
            game_day=game_day,
            player_district=player_district,
            all_rumors=all_rumors,
            active_rumor_ids=active_rumor_ids,
            world_decisions=world_decisions,
            rumour_mill=rumour_mill,
            ai_client=ai_client,
            named_npc_deaths=named_npc_deaths,
        )
        if not generated:
            return None
        shared.newspaper_edition_day = game_day
        shared.newspaper_edition = generated
        return shared.newspaper_edition

    
async def purchase_newspaper(
    player: Any,
    game_day: int,
    player_district: str,
    all_rumors: List[Dict[str, Any]],
    active_rumor_ids: List[str],
    world_decisions: List[Dict[str, Any]],
    rumour_mill: Dict[str, List[str]],
    ai_client: Optional["AIClient"] = None,
    named_npc_deaths: Optional[Dict[str, Dict[str, Any]]] = None,
    active=None,
    shared=None,
) -> Optional[Dict[str, Any]]:
    player_lock = getattr(player, "_newspaper_purchase_lock", None)
    if player_lock is None:
        player_lock = asyncio.Lock()
        setattr(player, "_newspaper_purchase_lock", player_lock)
    async with player_lock:
        if player.last_newspaper_day == game_day:
            return None
        if not can_afford_fabi(player, NEWSPAPER_COST_FABI):
            return None
        if active is not None:
            from .commands import storylet_resolution_owned
            if not storylet_resolution_owned(active):
                return None
        edition = await _resolve_shared_edition(
            shared=shared,
            game_day=game_day,
            player_district=player_district,
            all_rumors=all_rumors,
            active_rumor_ids=active_rumor_ids,
            world_decisions=world_decisions,
            rumour_mill=rumour_mill,
            ai_client=ai_client,
            named_npc_deaths=named_npc_deaths,
        )
        if not edition:
            return None
        if active is not None:
            from .commands import storylet_resolution_owned
            if not storylet_resolution_owned(active):
                return None
        if not spend_fabi_value(player, NEWSPAPER_COST_FABI):
            return None
        owned_copy = copy.deepcopy(edition)
        player.newspapers.append(owned_copy)
        player.last_newspaper_day = game_day
        return owned_copy


def format_newspaper_for_display(newspaper: Dict[str, Any]) -> str:
    lines = []
    
    lines.append(f"  {newspaper['masthead']}")
    lines.append(f"  {newspaper['subtitle']}")
    lines.append(f"  {newspaper['date']}")
    lines.append("")
    
    if newspaper.get("teahouse_talk"):
        lines.append("TEAHOUSE TALK")
        for item in newspaper["teahouse_talk"]:
            lines.append(f"  • {item}")
        lines.append("")
    
    if newspaper.get("notable_incidents"):
        lines.append("NOTABLE INCIDENTS")
        for item in newspaper["notable_incidents"]:
            lines.append(f"  • {item}")
        lines.append("")
    
    if newspaper.get("lane_whispers"):
        lines.append("RUMORS FROM THE ALLEYS")
        for item in newspaper["lane_whispers"]:
            lines.append(f"  • {item}")
        lines.append("")
    
    
    return "\n".join(lines)
