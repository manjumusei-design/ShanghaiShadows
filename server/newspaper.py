import random
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from .ai_client import AIClient


NEWSPAPER_COST_FABI = 3
NEWSPAPER_MASTHEAD = "弄堂消息""
NEWSPAPER_SUBTITLE = "LONGTANG XIAOSHUO"
NEWSPAPER_DATE_FORMAT = "Day {day}" #todo: might need to add year as well


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


def _format_world_decision(decision: Dict[str, Any]) -> Optional[str]:
    decision_type = decision.get("decision_type", "")
    actor_npc_id = decision.get("actor_npc_id", "someone")
    effects = decision.get("effects", {})

    if decision_type == "npc_killed":
        victim = effects.get("victim_id", "someone")
        return f"Violence in the lanes. {victim.replace('_', ' ').title()} found dead."
    elif decision_type == "vendor_shutter":
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