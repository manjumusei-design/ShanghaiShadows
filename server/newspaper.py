import asyncio
import copy
import logging
import random
import uuid
import uuid
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime

from .economy import can_afford_fabi, spend_fabi_value

if TYPE_CHECKING:
    from .ai_client import AIClient


logger = logging.getLogger(__name__)


NEWSPAPER_COST_FABI = 3
NEWSPAPER_GENERATION_TIMEOUT_SECONDS = 8.0
NEWSPAPER_MASTHEAD = "弄堂消息"
NEWSPAPER_SUBTITLE = "LONGTANG NEWS"
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


async def _ai_enhance_incident(
    ai_client: Optional["AIClient"],
    incident: str,
    game_day: int,
    *,
    generation_id: str = "direct",
) -> str:
    if not ai_client:
        _log_enhancement_result("incident", "fallback", "ai_client_unavailable", generation_id=generation_id)
        return incident
    
    prompt = f"""You are a newspaper editor in 1930s Shanghai. Enhance this brief incident report with atmospheric period detail. Keep it concise (1-2 sentences max). Maintain the original meaning but add flavor.

Original: {incident}

Enhanced version:"""

    try:
        enhanced = await ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=3.0)
        if enhanced and len(enhanced) < 300:
            _log_enhancement_result("incident", "endpoint", "accepted", len(enhanced), generation_id)
            return enhanced.strip()
    except Exception:
        _log_enhancement_result("incident", "fallback", "exception", generation_id=generation_id)
        return incident
    _log_enhancement_result("incident", "fallback", "response_rejected", len(enhanced or ""), generation_id)
    return incident


async def _ai_enhance_rumor(
    ai_client: Optional["AIClient"],
    rumor: str,
    distortion_level: float = 0.3,
    *,
    generation_id: str = "direct",
) -> str:
    if not ai_client:
        fallback = _distort_rumor(rumor, distortion_level)
        _log_enhancement_result("rumor", "fallback", "ai_client_unavailable", len(fallback), generation_id)
        return fallback
    
    prompt = f"""You are editing a short rumor for a serious newspaper or street-rumor column in 1930s Shanghai. Rewrite the supplied rumor as restrained, natural hearsay.

Preserve the source's factual meaning and uncertainty. Do not invent people, motives, danger, conspiracies, secrets, supernatural elements, or events unsupported by the source. Avoid playful, whimsical, sensational, or melodramatic language. Do not use stock openings such as "Word is", "They say", "Some claim", "Heard that", or "Rumor has it", and do not force a fixed rhetorical pattern.

Return only concise, grammatically complete rumor prose. Keep capitalization and punctuation natural. No heading, bullet, explanation, or label. Stay under 40 words.

Original: {rumor}

Rewritten rumor:"""

    try:
        enhanced = await ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=3.0)
        if enhanced and len(enhanced) < 250:
            _log_enhancement_result("rumor", "endpoint", "accepted", len(enhanced), generation_id)
            return enhanced.strip()
    except Exception:
        fallback = _distort_rumor(rumor, distortion_level)
        _log_enhancement_result("rumor", "fallback", "exception", len(fallback), generation_id)
        return fallback
    fallback = _distort_rumor(rumor, distortion_level)
    _log_enhancement_result("rumor", "fallback", "response_rejected", len(enhanced or ""), generation_id)
    return fallback


def _log_enhancement_result(
    content_type: str,
    source: str,
    reason: str,
    response_chars: int = 0,
    generation_id: str = "direct",
) -> None:
    logger.info(
        "Newspaper enhancement generation_id=%s content_type=%s source=%s reason=%s response_chars=%s",
        generation_id,
        content_type,
        source,
        reason,
        response_chars,
    )


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


async def _generate_newspaper(
    game_day: int,
    player_district: str,
    all_rumors: List[Dict[str, Any]],
    active_rumor_ids: List[str],
    world_decisions: List[Dict[str, Any]],
    rumour_mill: Dict[str, List[str]],
    ai_client: Optional["AIClient"] = None,
    named_npc_deaths: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    generation_id = uuid.uuid4().hex[:12]
    logger.info(
        "Newspaper generation started generation_id=%s day=%s ai_enabled=%s",
        generation_id,
        game_day,
        bool(ai_client),
    )
    selected_rumors = _select_rumors_for_newspaper(
        all_rumors, active_rumor_ids, player_district, max_rumors=5
    )

    teahouse_talk = []
    for rumor in selected_rumors[:2]:
        original = rumor.get("text", "")
        enhanced = await _ai_enhance_rumor(
            ai_client,
            original,
            distortion_level=0.4,
            generation_id=generation_id,
        )
        teahouse_talk.append(enhanced)

    notable_incidents = []
    for npc_id, record in sorted((named_npc_deaths or {}).items()):
        if not _incident_is_fresh(record.get("day"), game_day):
            continue
        incident = _format_npc_death_record(record)
        if incident and incident not in notable_incidents:
            enhanced = await _ai_enhance_incident(ai_client, incident, game_day, generation_id=generation_id)
            if enhanced and enhanced not in notable_incidents:
                notable_incidents.append(enhanced)
    for decision in world_decisions[-5:]:
        if not _incident_is_fresh(decision.get("day"), game_day):
            continue
        incident = _format_world_decision(decision)
        if incident and incident not in notable_incidents:
            enhanced = await _ai_enhance_incident(ai_client, incident, game_day, generation_id=generation_id)
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
            enhanced = await _ai_enhance_rumor(
                ai_client,
                rumor,
                distortion_level=0.5,
                generation_id=generation_id,
            )
            lane_whispers.append(enhanced)
    
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
    logger.info("Newspaper generation completed generation_id=%s", generation_id)
    return newspaper


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
    return await _generate_newspaper(
        game_day=game_day,
        player_district=player_district,
        all_rumors=all_rumors,
        active_rumor_ids=active_rumor_ids,
        world_decisions=world_decisions,
        rumour_mill=rumour_mill,
        ai_client=ai_client,
        named_npc_deaths=named_npc_deaths,
    )


async def generate_deterministic_newspaper(**kwargs) -> Dict[str, Any]:
    kwargs["ai_client"] = None
    return await _generate_newspaper(**kwargs)


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
    deterministic: bool = False,
) -> Optional[Dict[str, Any]]:
    generator = generate_deterministic_newspaper if deterministic else generate_newspaper
    if shared is None:
        return await generator(
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
            logger.info("Newspaper edition cache hit day=%s", game_day)
            return cached
        generated = await generator(
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


def _scripted_tutorial_edition(game_day: int) -> Dict[str, Any]:
    return {
        "day": game_day,
        "masthead": NEWSPAPER_MASTHEAD,
        "subtitle": NEWSPAPER_SUBTITLE,
        "date": NEWSPAPER_DATE_FORMAT.format(day=game_day),
        "teahouse_talk": [
            "The rice queue at the Nanking Road ration post formed before first light, and the ledger ran short before the ninth name was called.",
            "A messenger from the tea houses says the new checkpoint count takes longer each day, and the lane keepers have learned the patrols' hours by heart.",
        ],
        "notable_incidents": [
            "Municipal notice: the Nanking Road checkpoint will search every handcart crossing into the district, and vendors are advised to keep their papers on their persons.",
        ],
        "lane_whispers": [
            "Someone in the lanes is paying good money for old passbooks, and no one will say who.",
            "The market sellers claim the price of printed papers has doubled since the hospital wards stopped answering letters.",
        ],
        "purchased_at": datetime.now().isoformat(),
    }


async def _resolve_edition_with_fallback(
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
    try:
        edition = await asyncio.wait_for(
            _resolve_shared_edition(
                shared=shared,
                game_day=game_day,
                player_district=player_district,
                all_rumors=all_rumors,
                active_rumor_ids=active_rumor_ids,
                world_decisions=world_decisions,
                rumour_mill=rumour_mill,
                ai_client=ai_client,
                named_npc_deaths=named_npc_deaths,
            ),
            timeout=NEWSPAPER_GENERATION_TIMEOUT_SECONDS,
        )
        if edition:
            return edition
    except Exception as error:
        logger.warning(
            "Newspaper generation source=fallback reason=%s",
            type(error).__name__,
        )
    logger.info("Newspaper generation source=fallback reason=deterministic_retry")
    return await _resolve_shared_edition(
        shared=shared,
        game_day=game_day,
        player_district=player_district,
        all_rumors=all_rumors,
        active_rumor_ids=active_rumor_ids,
        world_decisions=world_decisions,
        rumour_mill=rumour_mill,
        ai_client=None,
        named_npc_deaths=named_npc_deaths,
        deterministic=True,
    )


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
        if getattr(player, "in_tutorial", False):
            edition = _scripted_tutorial_edition(game_day)
        else:
            edition = await _resolve_edition_with_fallback(
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
