from enum import Enum
class MessageType(Enum):
    TUTORIAL = "tutorial"
    TUTORIAL_NPC = "tutorial_npc"
    NPC_DIALOGUE = "npc_dialogue"
    NPC_AMBIENT = "npc_ambient"
    ROOM_DESCRIPTION = "room_description"
    ROOM_TITLE = "room_title"
    ROOM_TAGS = "room_tags"
    ROOM_EXITS = "room_exits"
    ROOM_ITEMS = "room_items"
    ROOM_NPCS = "room_npcs"
    SYSTEM = "system"
    COMBAT = "combat"
    COMBAT_NARRATION = "combat_narration"
    SOCIAL = "social"
    EVENT = "event"
    AMBIENT = "ambient"
    PLAYER_ACTION = "player_action"
    PLAYER_STATUS = "player_status"
    DISCOVERY = "discovery"
    MAP_MENU = "map_menu"
    INTERNAL_MONOLOGUE = "internal_monologue"
    STORYLET_FRAME = "storylet_frame"
    WEATHER_RAIN = "weather_rain"
    WEATHER_STORM = "weather_storm"
    WEATHER_FOG = "weather_fog"
    WEATHER_SNOW = "weather_snow"
    WEATHER_CLEAR = "weather_clear"

CURFEW_MINUTE = 1200
EVENT_LOG_MAXLEN = 500
WORLD_EVENTS_MAXLEN = 50
CONVERSATION_HISTORY_MAXLEN = 20
NPC_MEMORY_MAXLEN = 30
HUNGER_DECAY_RATE = 0.05
HUNGER_HEALTH_DAMAGE = 1
LOW_HUNGER_THRESHOLD = 20
HUNGER_WARNING_THRESHOLD = 30

HUNGER_TIER_FULL = 80
HUNGER_TIER_SATISFIED = 50
HUNGER_TIER_HUNGRY = 20
HUNGER_TIER_STARVING = 1
HUNGER_TIER_FAMISHED = 0

INFLUENCE_THRESHOLD = 80
UNITY_INFLUENCE = 60
INFLUENCE_LEAD = 10
STATE_BROADCAST_INTERVAL = 3

EVENTS_PATH = "server/data/events.yaml"
TRUST_RULES_PATH = "server/data/trust_rules.yaml"
DISGUISES_PATH = "server/data/disguises.yaml"
STORYLETS_PATH = "server/data/storylets.yaml"
NARRATIVE_CHAINS_PATH = "server/data/narrative_chains.yaml"
OBITUARY_PATH = "server/data/obituary_templates.yaml"
CHARACTER_NAMES_PATH = "server/data/character_names.yaml"
MISSIONS_PATH = "server/data/missions.yaml"
MILESTONES_PATH = "server/data/milestones.yaml"
RUMORS_PATH = "server/data/custom/rumors.yaml"
RUMOR_WINDOW = 20
RUMOR_STEP = 3
AMBIENT_EVENTS_PATH = "server/data/ambient_events.yaml"

DISARM_CHANCE_CAP = 80 
STEALTH_KILL_BONUS = 25

HUNGER_DECAY_PER_HOUR = 3
HUNGER_DECAY_PER_HOUR_WINTER = 4.5
HEALTH_DECAY_HUNGRY = 2
MORALE_DECAY_PER_HOUR = 1
MORALE_WARNING_THRESHOLD = 40
MORALE_LOW_THRESHOLD = 30

STAT_GAIN_COURAGE_COMBAT = 1
STAT_GAIN_STEALTH_HIDE = 1
STAT_GAIN_STEALTH_TAIL = 1
STAT_GAIN_PERCEPTION_OBSERVE = 1
STAT_CAP = 100
MORALE_PENALTY_MAX = 20
COMBAT_GROWTH_FACTIONS = ("kempeitai", "gmd", "green_gang")

MORALE_MONOLOGUE_COOLDOWN_MINUTES = 120
STORYLET_FRAME_WIDTH = 78
DISPLAY_WRAP_WIDTH = 78

WEATHER_CLEAR = "clear"
WEATHER_RAIN = "rain"
WEATHER_FOG = "fog"
WEATHER_SNOW = "snow"
WEATHER_STORM = "storm"

WEATHER_STEALTH_MODIFIER = {"fog": 10, "snow": 5, "storm": 5, "rain": 0, "clear": 0}
WEATHER_PERCEPTION_MODIFIER = {"fog": -10, "snow": 0, "storm": 0, "rain": 0, "clear": 0}
WEATHER_SOUND_RANGE_MODIFIER = {"fog": 0.7, "snow": 1.0, "storm": 2.0, "rain": 0.6, "clear": 1.0}
WEATHER_HUNGER_MULTIPLIER = {"snow": 1.3, "rain": 1.0, "storm": 1.0, "fog": 1.0, "clear": 1.0}
WEATHER_MORALE_HOURLY = {"snow": -1, "rain": 0, "storm": -2, "fog": -1, "clear": 0}

WEAPON_TYPE_BASE_DAMAGE = {"firearm": 40, "stealth": 25, "melee": 20}
STEALTH_DAMAGE_BONUS = 10

TRUST_DECAY_PER_DAY = 2

PICKPOCKET_BASE = 5

VENDOR_WANTED_REFUSAL_THRESHOLD = 2
MEMORIAL_MAX = 20
MISSION_FABI_RANGE = (10, 50)

CURFEW_START_HOUR = 20
CURFEW_END_HOUR = 6
CURFEW_IMMUNITY_DURATION_MINUTES = 30  
WANTED_LEVEL_MAX = 3
WANTED_DECAY_INTERVAL_DAYS = 3  

UNITY_RANGE = 15

DEGRADE_RAIN_RATE = 1

SUSPICION_DECAY_PER_TICK = 2
SUSPICION_THRESHOLD_INVESTIGATE = 50
HIDDEN_DECAY_CHANCE = 0.1
PATROL_PERCEPTION_BASE = 35
SUSPICION_FAILED_STEALTH = 20
SUSPICION_INVESTIGATE_RELIEF = 10

DECISION_LEDGER_MAXLEN = 100
VENDOR_SHUTTER_TENSION = 60
VENDOR_REOPEN_TENSION = 40
DEFECTION_DISILLUSIONMENT_THRESHOLD = 70
DEFECTION_DAILY_CHANCE = 0.1
DISILLUSIONMENT_PER_TICK = 2

SEASONAL_FOOD_SHORTAGE = {"winter": 0.5, "summer": 0.8}
SEASONAL_PRICE_MULTIPLIER = {"winter": 1.5, "summer": 1.2, "spring": 1.0, "autumn": 1.0}

SEASONAL_MORALE_MODIFIER = {"winter": -1, "spring": 0, "summer": 0, "autumn": -0.5}
SEASONAL_STEALTH_MODIFIER = {"winter": 0, "spring": 0, "summer": -5, "autumn": 5}
SEASONAL_PERCEPTION_MODIFIER = {"winter": -5, "spring": 0, "summer": 0, "autumn": 5}
SEASONAL_PATROL_DENSITY = {"winter": 1.2, "spring": 1.0, "summer": 0.8, "autumn": 1.1}

SEASON_MONTHS = {"winter": [11, 0, 1], "spring": [2, 3, 4], "summer": [5, 6, 7], "autumn": [8, 9, 10]}

def get_season(game_day: int) -> str:
    month = (game_day // 30) % 12
    for season, months in SEASON_MONTHS.items():
        if month in months:
            return season
    return "spring" 

FOOD_RESTOCK_INTERVAL = 360
BLACK_MARKET_LISTING_EXPIRE_DAYS = 7
BLACK_MARKET_DETECTION_CHANCE = 30  
BLACK_MARKET_MULTIPLIER = 1.5

RICKSHAW_NPC_IDS = ["liu_wei", "rickshaw_ah_fook"]

STORYLET_QUEUE_MAX = 2

AUTOSAVE_INTERVAL_SECONDS = 300

FLAGS_HIDDEN_FROM_STATUS = frozenset({"tutorial_complete", "tutorial_skip", "tutorial_skip_pending"})

MAX_INVENTORY = 12

NPC_INTERACTIONS_PATH = "server/data/npc_interactions.yaml"
DISTRESS_WITNESS_INTERVAL_MINUTES = 15
DISTRESS_SOUND_BASE_RANGE = 2
DISTRESS_WANTED_INCREASE_CHANCE = 10


CRIME_SCENE_DURATION_DAYS = 2
CORPSE_DECAY_DAYS = 1

TENSION_HIGH_THRESHOLD = 120

YELL_THREAT_KEYWORDS = frozenset({"kill", "die", "destroy", "curse", "murder", "death"})
YELL_RESISTANCE_KEYWORDS = frozenset({"resistance", "freedom", "liberation", "revolution", "rebel", " ccp", "communist"})
YELL_WARNING_KEYWORDS = frozenset({"watch out", "danger", "run", "hide", "police", "patrol", "soldier", "kempeitai"})

RICE_BOWL_COST = 5
BAOZI_COST = 8
TEA_COST = 3
