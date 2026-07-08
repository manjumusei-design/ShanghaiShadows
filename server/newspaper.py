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


