from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging
import yaml

from .world import World, Room
from .constants import Messagetype

TUTORIAL_ROOM_IDS = [
    "refugee_entry_checkpoint",
    "refugee_entry_tea_house",
    "refugee_entry_back_alley",
    "refugee_entry_market_street",
    "refugee_entry_warehouse",
    "refugee_entry_outpost",
    "refugee_entry_rooftop",
    "refugee_entry_dock",
    "refugee_entry_cellar",
    "refugee_entry_bund_exit",
    "orientation_weather",
    "orientation_trust",
    "orientation_wanted",
    "orientation_blackmarket",
    "orientation_rumors",
    "orientation_eavesdrop",
    "orientation_contact",
    "orientation_alley",
]

ORIENTATION_ROOM_DEFS = {
    "orientation_weather": {
        "title": "Weather Station",
        "description": "The Weather Station is filled with instruments and charts. Barometers and wind gauges line the walls, tracking Shanghai's ever-shifting seasons.",
        "district": "orientation",
        "tags": ["tutorial", "orientation", "indoors"],
        "indoors": True,
    },
    "orientation_trust": {
        "title": "Safehouse Common Room",
        "description": "The Safehouse Common Room is warm and welcoming. Maps of faction territories cover the walls, showing the complex web of alliances and rivalries.",
        "district": "orientation",
        "tags": ["tutorial", "orientation", "indoors", "safe_room"],
        "indoors": True,
        "safe_room": True,
    },
    "orientation_wanted": {
        "title": "Police Checkpoint",
        "description": "The Police Checkpoint is stark and official. Wanted posters line the walls, showing faces of those the occupation authorities seek.",
        "district": "orientation",
        "tags": ["tutorial", "orientation", "indoors"],
        "indoors": True,
    },
    "orientation_blackmarket": {
        "title": "Black Market Alley",
        "description": "The Black Market Alley is dimly lit and smells of trade. Goods from every corner of the world pass through here, no questions asked.",
        "district": "orientation",
        "tags": ["tutorial", "orientation"],
        "indoors": False,
    },
    "orientation_rumors": {
        "title": "Information Broker's Den",
        "description": "The Information Broker's Den is lined with papers and secrets. Whispers become currency here, traded for favors and coin.",
        "district": "orientation",
        "tags": ["tutorial", "orientation", "indoors"],
        "indoors": True,
    },
    "orientation_eavesdrop": {
        "title": "Eavesdropper's Perch",
        "description": "The balcony overlooks the city. Every whisper from below rises to meet you. The perfect place to learn what others would rather keep hidden.",
        "district": "orientation",
        "tags": ["tutorial", "orientation", "indoors"],
        "indoors": True,
    },
    "orientation_contact": {
        "title": "Resistance Safehouse",
        "description": "The safehouse is warm despite the chill outside. A small fire crackles in the hearth. Here, the resistance plans its next moves.",
        "district": "orientation",
        "tags": ["tutorial", "orientation", "indoors", "safe_room", "ccp_safehouse"],
        "indoors": True,
        "safe_room": True,
    },
    "orientation_alley": {
        "title": "Dark Alley",
        "description": "The alley is dark and narrow. The smell of cheap wine and cigarette smoke hangs in the air. The gate to Shanghai awaits at the southern end.",
        "district": "orientation",
        "tags": ["tutorial", "orientation"],
        "indoors": False,
    },
}