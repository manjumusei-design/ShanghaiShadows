from enum import Enum
class Messagetype(Enum):
    TUTORIAL = "tutorial"
    NPC_AMBIENT = "npc_ambient"
    NPC_DIALOGUE = "npc_dialogue"
    ROOM_DESCRIPTION = "room_description"
    ROOM_items = "room_items"
    ROOM_NPCS = "room_npcs"
    SYSTEM = "system"
    COMBAT = "combat"
    SOCIAL = "social"
    EVENT = "event"
    AMBIENT = "ambient"
    PLAYER_ACTION = "player_action"
    PLAYER_STATUS = "player_status"
    DISCOVERY = "discovery"

CURFEW_MINUTE = 1200
EVENT_LOG_MAXLEN = 500
WORLD_EVENTS_MAXLEN = 50
CONVERSATION_HISTORY_MAXLEN = 20
NPC_MEMORY_MAXLEN = 30
HUNGER_DECAY_RATE = 0.05
HUNGER_HEALTH_DAMAGE = 1
LOW_HUNGER_THRESHOLD = 20
HUNGER_WARNING_THRESHOLD = 30
INFLUENCE_THRESHOLD = 80
UNITY_INFLUENCE = 60
INFLUENCE_LEAD = 10
STATE_BROADCAST_INTERVAL = 5

EVENTS_PATH = "server/data/events.yaml"
TRUST_RULES_PATH = "server/data/trust_rules.yaml"
DISGUISES_PATH = "server/data/disguises.yaml"
STORYLETS_PATH = "server/data/storylets.yaml"
OBITUARY_PATH = "server/data/obituary_templates.yaml"
BACKGROUNDS_PATH = "server/data/character_backgrounds.yaml"
MISSIONS_PATH = "server/data/missions.yaml"
MILESTONES_PATH = "server/data/milestones.yaml"
RUMORS_PATH = "server/data/custom/rumors.yaml"
RUMOR_WINDOW = 20
RUMOR_STEP = 3

DISARM_CHANCE_CAP = 80
STEALTH_KILL_BONUS = 25

HUNGER_DECAY_PER_HOUR = 3
HEALTH_DECAY_HUNGRY = 2
MORALE_DECAY_PER_HOUR = 1

STAT_GAIN_COURAGE_COMBAT = 1
STAT_GAIN_STEALTH_HIDE = 1
STAT_GAIN_STEALTH_TAIL = 1
STAT_GAIN_PERCEPTION_OBSERVE = 1
STAT_CAP = 100
MORALE_LOW_THRESHOLD = 30
MORALE_PENALTY_MAX = 20
COMBAT_GROWTH_FACTIONS = ("kempeitai", "gmd", "green_gang")

WEAPON_TYPE_BASE_DAMAGE = {"firearm": 40, "stealth": 25, "melee": 20}
STEALTH_DAMAGE_BONUS = 10

TRUST_DECAY_PER_DAY = 2

RICE_BOWL_COST = 2
BAOZI_COST = 1
TEA_COST = 1
PICKPOCKET_BASE = 5
MISSION_FABI_RANGE = (10, 50)
NURSE_COST = 20
NURSE_HEAL = 30

CURFEW_START_HOUR = 20
CURFEW_END_HOUR = 6
WANTED_LEVEL_MAX = 3

DAY_LIBERATION = 2835
UNITY_RANGE = 15

DEGRADE_RAIN_RATE = 1

SUSPICION_DECAY_PER_TICK = 2
SUSPICION_THRESHOLD_INVESTIGATE = 50
HIDDEN_DECAY_CHANCE = 0.4
SUSPICION_FAILED_STEALTH = 20
SUSPICION_INVESTIGATE_RELIEF = 10

DECISION_LEDGER_MAXLEN = 100
VENDOR_SHUTTER_TENSION = 60
DEFECTION_DISILLUSIONMENT_THRESHOLD = 70
DEFECTION_DAILY_CHANCE = 0.1
DISILLUSIONMENT_PER_TICK = 2

SEASONAL_FOOD_SHORTAGE = {"winter": 0.5, "summer": 0.8}
SEASONAL_PRICE_MULTIPLIER = {"winter": 1.5, "summer": 1.2, "spring": 1.0, "autumn": 1.0}
SEASON_MONTHS = {"winter": [11, 0, 1], "spring": [2, 3, 4], "summer": [5, 6, 7], "autumn": [8, 9, 10]}

def get_season(game_day: int) -> str:
    month = (game_day // 30) % 12
    for season, months in SEASON_MONTHS.items():
        if month in months:
            return season
    return "spring" 

FOOD_RESTOCK_INTERVAL = 360
BLACK_MARKET_LISTING_EXPIRE_DAYS = 7