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

ORIENTATION_ROOM_EXITS = { #My design here is that due to the limited amount of buckets on npcs and the lack of an invocation from the user to talk to the system or npc, i decided to code the tutorial with a hardcoded method of the system pretending it is the npc teaching them via system messages and then progressing via a flag, kthxbye. Also ill be numbering them so i can line them up with the tutorial steps i wrote in notepad
    "orientation_weather": {"east": "orientation_trust"},
    "orientation_trust": {"east": "orientation_wanted"},
    "orientation_wanted": {"east": "orientation_blackmarket"},
    "orientation_blackmarket": {"east": "orientation_rumors"},
    "orientation_rumors": {"east": "orientation_eavesdrop"},
    "orientation_eavesdrop": {"east": "orientation_contact"},
    "orientation_contact": {"east": "orientation_alley"},
    "orientation_alley": {"south": "bund_dawn"}, 
} 

_ROOM_TEA_HOUSE = [
    {"room_id": "refugee_entry_tea_house"},
    {"verb": "look", "hint_level": "explicit",
     "cmd_hint": "TALK TO MRS. LIN",
     "msg": "[Tutorial] \n\nThe tea house is quiet, steam rising from a kettle in the corner. A woman behind the counter watches you with careful eyes. Use LOOK to see what is here.\n\n If you fall, your next life begins anew but your journal will remain where you fell for your future self to find. It is the only thing that survives.",
     "journal_entry": "Death is permanent. When I die, my next character can recover my JOURNAL where I died."},

    # 1.2  Teaching TALK command
    {"verb": "talk to", "target": "mrs. lin", "hint_level": "explicit",
     "cmd_hint": "ASK MRS. LIN ABOUT WORK",
     "msg": "[Tutorial] The foundation of all interaction. Mrs. Lin wipes a cup and watches you approach. Type: TALK TO MRS. LIN to start a conversation. In the future, TALK TO <NPC NAME> opens dialogue with any character. Some will greet you warmly. Some may be cold, you never know until you try."},

    # 1.3 ASK MRS. LIN ABOUT WORK
    {"verb": "ask", "target": "work", "hint_level": "explicit",
     "cmd_hint": "BUY FROM MRS. LIN",
     "journal_entry": "Mrs. Lin told me about work: Comrade Chen in the back alley needs couriers.'",
     "reward": {"money_fabi": 50},
     "msg": "[Tutorial] Mrs. Lin sets down the cup. 'Work? There is always work for those who are not afraid.' She leans across the counter. 'Comrade Chen in the back alley needs couriers, if you are up to it.' Type: ASK MRS. LIN ABOUT WORK — ASK <NPC> ABOUT <topic> queries what they know. Some will answer, while some may lie."},

    # 1.4 BUY baozi
            {"verb": "buy", "target": "baozi", "from_npc": "tutorial_mrs_lin",
             "confirm_on": "purchase",
             "flag": "tutorial_purchased_baozi",
     "hint_level": "explicit",
     "cmd_hint": "TYPE EAT BAOZI",
     "msg": "[Tutorial] You have 50 fabi in your pocket — Chinese currency that spends in stalls, shops, and the hands of corrupt officials. Type: BUY FROM MRS. LIN to open her shop. In the future, BUY FROM <NPC NAME> opens any vendor's wares. Each vendor sells different goods — weapons, medicine, information. Get to know who sells what.",
     "note": "Advances when player purchases baozi from Mrs. Lin (via cmd_buy success like a flag typa mechanism)."},

    # 1.5 INVENTORY
    {"verb": "inventory", "hint_level": "explicit",
     "cmd_hint": "EAT BAOZI",
     "msg": "[Tutorial] Know what you carry at all times. Type: INVENTORY to see your items, money, and equipment. Use Q and E to navigate between sections and arrow keys to scroll through items. A full inventory means options. An empty one means desperation. Never let your pockets go bare in Shanghai."},

    # 1.6 EAT BAOZI
    {"verb": "eat", "target": "baozi", "alt_target": "baozi", "hint_level": "explicit",
     "cmd_hint": "GO EAST",
     "msg": "[Tutorial] Type: EAT BAOZI — hunger gnaws at your focus and health. EAT <FOOD ITEM> consumes food from your inventory, restoring hunger and a small amount of health. Without food, your morale drops, your courage falters, and the city becomes more dangerous. A full stomach is a survival tool."},

    # 1.7 GO EAST to Back Alley
    {"verb": "go", "target": "east", "hint_level": "explicit",
     "cmd_hint": "Type: TALK TO COMRADE CHEN",
     "msg": "[Tutorial] Time to move. Mrs. Lin nods toward the eastern door. 'Chen will be waiting. Do not keep him long,  the patrols change soon.' Type: GO EAST to walk to the Back Alley. Or use GO <Direction> to navigate. For longer journeys, use MAP to bring up the interactive overview — arrow keys to highlight a room, Enter to travel there automatically.",
     "blocked_exits": {"refugee_entry_tea_house": {"east": {"stage": 6, "message": 'A Japanese soldier blocks the east gate. "Pass required to go through here."'}}}},
]
