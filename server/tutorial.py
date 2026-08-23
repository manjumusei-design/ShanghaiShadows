import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .combat import strip_article
from .constants import MessageType
from .equipment import equipped_weapon
from .formatting import format_tutorial_text
from .player_data import PlayerData
from .world import Room

logger = logging.getLogger(__name__)

_ITEM_HINT_TOKEN = re.compile(r"\{item:([a-z0-9_]+)\}")


def _resolve_item_hint_name(item_id: str, item_catalog: Any, player: Any = None) -> str:
    for item in getattr(player, "inventory", None) or []:
        if getattr(item, "id", "") == item_id and getattr(item, "name", ""):
            return strip_article(item.name)
    item = (item_catalog or {}).get(item_id)
    if item is not None and getattr(item, "name", ""):
        return strip_article(item.name)
    raise ValueError(f"unresolved tutorial item token {{item:{item_id}}}")


def render_cmd_hint(hint: str, *, item_catalog: Any = None, player: Any = None) -> str:
    if not hint or "{item:" not in hint:
        return hint
    return _ITEM_HINT_TOKEN.sub(
        lambda match: _resolve_item_hint_name(match.group(1), item_catalog, player).upper(),
        hint,
    )


def render_stage_hint(action: dict, item_catalog: Any = None, player: Any = None) -> str:
    try:
        return render_cmd_hint(
            action.get("teaching_hint") or action.get("cmd_hint"),
            item_catalog=item_catalog,
            player=player,
        )
    except ValueError as exc:
        logger.error("tutorial command hint dropped: %s", exc)
        return ""


WAREHOUSE_ATTACK_STAGE_ID = "warehouse_attack"

_WAREHOUSE_ATTACK_CUE_TEMPLATE = (
    "The soldier turns toward you. Combat can kill you, and death is permanent. "
    "If you die, your journal remains where you fell for the first finder to claim its knowledge once. "
    "Your Courage is {courage}. Your {weapon} adds {bonus}, giving you {total} "
    "against the soldier's Authority of {authority}. {comparison} "
    "ATTACK resolves immediately, so be sure before you act."
)

_WAREHOUSE_ATTACK_CUE_FALLBACK = (
    "Your Courage and equipment determine whether an attack succeeds against the "
    "soldier's Authority. ATTACK resolves immediately, so check your situation before you act."
)


def warehouse_attack_cue_values(courage, weapon, hidden, morale, authority):
    from .combat import compute_effective_courage, courage_multiplier_for, resolve_attack

    multiplier = courage_multiplier_for(weapon)
    total, _parts, _defence, _morale = compute_effective_courage(
        courage,
        weapon,
        hidden,
        None,
        morale,
        courage_multiplier=multiplier,
    )
    outcome = resolve_attack(
        attacker_courage=courage,
        attacker_weapon=weapon,
        target_authority=authority,
        target_armour=None,
        attacker_hidden=hidden,
        attacker_morale=morale,
        courage_multiplier=multiplier,
    )
    comparison = ""
    if outcome.won:
        comparison = f"{total} meets or exceeds {authority}, so this attack will win the exchange."
    return {
        "courage": courage,
        "weapon": strip_article(weapon.name) if weapon else "",
        "bonus": getattr(weapon, "courage_bonus", 0) or 0,
        "total": total,
        "authority": authority,
        "comparison": comparison,
        "guaranteed": bool(outcome.won),
    }


def format_warehouse_attack_cue(template: str, values: dict) -> str:
    if not values.get("guaranteed"):
        logger.error(
            "tutorial %s invariant violated: courage=%s weapon=%s bonus=%s total=%s authority=%s",
            WAREHOUSE_ATTACK_STAGE_ID,
            values.get("courage"),
            values.get("weapon"),
            values.get("bonus"),
            values.get("total"),
            values.get("authority"),
        )
        return _WAREHOUSE_ATTACK_CUE_FALLBACK
    return template.format(
        **{key: value for key, value in values.items() if key != "guaranteed"}
    )


def runtime_warehouse_attack_values(ctx, action: dict) -> dict:
    player = ctx.session.player
    world = ctx.shared.world
    weapon = equipped_weapon(player)
    room = world.rooms.get(getattr(player, "current_room", ""))
    soldier_id = None
    if room and action.get("target"):
        from .commands import find_npc_by_name

        soldier_id = find_npc_by_name(ctx, action["target"], room.npcs)
    soldier = world.npcs.get(soldier_id) if soldier_id else None
    authority = getattr(soldier, "authority", 0)
    if weapon is None or soldier is None:
        logger.error(
            "tutorial %s state unresolved: weapon=%s soldier=%s room=%s",
            WAREHOUSE_ATTACK_STAGE_ID,
            getattr(weapon, "id", None),
            soldier_id,
            getattr(player, "current_room", ""),
        )
        return {
            "courage": player.courage,
            "weapon": "",
            "bonus": 0,
            "total": 0,
            "authority": authority,
            "comparison": "",
            "guaranteed": False,
        }
    return warehouse_attack_cue_values(
        player.courage, weapon, player.hidden, player.morale, authority
    )


def canonical_warehouse_attack_context():
    import copy

    from .world import World

    world = World()
    player = PlayerData()
    weapon = copy.deepcopy(world.item_catalog.get("wooden_club"))
    if weapon is not None:
        weapon.instance_id = f"transcript_{getattr(weapon, 'id', 'wooden_club')}"
        player.inventory.append(weapon)
        player.equipped_weapon_id = weapon.instance_id
    soldier = world.npcs.get("tutorial_kempeitai_soldier")
    return player, weapon, getattr(soldier, "authority", 0)


def warehouse_attack_transcript_cue() -> str:
    player, weapon, authority = canonical_warehouse_attack_context()
    values = warehouse_attack_cue_values(
        player.courage, weapon, player.hidden, player.morale, authority
    )
    return format_warehouse_attack_cue(_WAREHOUSE_ATTACK_CUE_TEMPLATE, values)

_ROOM_TEA_HOUSE = [
    {"room_id": "refugee_entry_tea_house"},
    {
        "verb": "look",
        "hint_level": "explicit",
        "cmd_hint": "LOOK",
        "cue": "LOOK shows you the room around you: who is here, what is nearby, and where you can go. Use it whenever you need to get your bearings or check what has changed.",
    },
    {
        "verb": "talk to",
        "target": "mrs. lin",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "TALK TO MRS. LIN",
        "teaching_hint": "TALK TO MRS. LIN to speak with her.",
        "cue": "Mrs. Lin sets down the tray and looks you over.",
        "cue_speech": "Come in. Do not stand in the doorway. Sit where I can see you. You are not from Shanghai, are you?",
        "npc_msg": "If you have come this far with only the road behind you, things must be bad where you came from. Sit. Tell me what you need. Food? Work? Or are you looking for something else?",
    },
    {
        "verb": "none",
    },
    {
        "verb": "ask",
        "from_npc": "tutorial_mrs_lin",
        "indirect_state": "present",
        "required_indirect": "work",
        "hint_level": "explicit",
        "cmd_hint": "TYPE ASK MRS. LIN, then use the topic list to choose what to ask about, such as ASK MRS. LIN ABOUT WORK",
        "teaching_hint": "ASK MRS. LIN ABOUT [TOPIC] lets you ask about something she knows. Press Tab after ABOUT to see available topics.",
        "topics": ["FOOD", "WORK", "THE CITY"],
        "npc_msg": "Chen is in the alley behind the tea house. He is a nervous man, but I sent word that you might come, so he should hear you out. If you are going to see him, buy a baozi before you leave. That alley is no place to discover you are hungry.",
    },
    {
        "verb": "buy",
        "target": "baozi",
        "from_npc": "tutorial_mrs_lin",
        "confirm_on": "purchase",
        "flag": "tutorial_purchased_baozi",
        "hint_level": "explicit",
        "cmd_hint": "BUY FROM MRS. LIN",
        "teaching_hint": "However, not every NPC is a vendor and has things for you to buy.",
        "cue": "BUY FROM opens a vendor's shop, where you can see what they sell and choose what to purchase.",
    },
    {
        "verb": "inventory",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "teaching_hint": "INVENTORY opens your inventory and shows what you are carrying. Use it whenever you want to check your items.",
        "cmd_hint": "INVENTORY",
        "cue": "INVENTORY shows the items you are currently carrying. Open it now and check that your baozi is there.",
        "cue_speech": "Before you leave, check that you still have the baozi. Better to notice something is missing here than outside. Space is limited, you can only carry 12 items at a time so choose what to bring with you wisely.",
    },
    {
        "verb": "eat",
        "target": "baozi",
        "alt_target": "baozi",
        "from_npc": "tutorial_mrs_lin",
        "teaching_hint": "EAT brings up consumables that you are in possession of, then choose your baozi with arrow keys and use the enter key to eat it. Try EAT BAOZI.",
        "hint_level": "explicit",
        "cmd_hint": "EAT BAOZI",
        "cue": "Hunger falls over time. Food restores hunger, and some foods can also restore morale. If hunger falls too low, it can weaken you and eventually cost you health.",
        "cue_speech": "Go on, eat it while it is still warm. Food does you no good sitting in your bag, and you do not want to discover how hungry you are once you are out in the street.",
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "cue": "A sharp shout carries in from the street. The Japanese soldier at the eastern doorway turns and steps outside, leaving the passage clear.",
        "cue_speech": "That is your chance. Chen should be in the alley by now. Go east and find him before the soldier comes back.",
        "blocked_exits": {"refugee_entry_tea_house": {"east": {"stage": 7, "message": "A Japanese soldier blocks the east gate."}}},
    },
]

_ROOM_BACK_ALLEY = [
    {"room_id": "refugee_entry_back_alley"},
    {
        "verb": "talk to",
        "target": "comrade chen",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "TALK TO COMRADE CHEN",
        "cue_speech": "Come closer. Keep your voice down.",
        "arrival_text": "The tea-house door closes behind you. A latch drops into place on the other side.",
        "cue": "Chen glances toward the mouth of the alley and beckons you closer, keeping one eye on the street.",
        "npc_msg": "Mrs. Lin sent word about you. She says you can carry a message. I know almost nothing about you, and for once that is useful. The patrols here have not learned your face yet. For one errand, I can make use of that. It does not mean I trust you with everything. Listen carefully. A patrol is due through this alley soon, and I would rather they pass without finding a reason to stop.",
        "journal_entry": "Mrs. Lin sent me to Comrade Chen in the alley. He appears to have connections with the Communists and warned me that a patrol would be passing through soon.",
        "blocked_exits": {"refugee_entry_back_alley": {"east": {"stage": 8, "message": "A locked gate blocks the eastern passage."}, "west": {"stage": 8, "message": "The tea-house door has been bolted from the other side."}}},
    },
    {
        "verb": "hide",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "HIDE",
        "cue": "HIDE is deterministic. Room details show the Stealth requirement before you act: real cover requires 25 Stealth, ordinary rooms require 50, and exposed or authority-controlled areas require 75. Meet the requirement and HIDE succeeds, and patrols do not overturn that success. HIDE holds while you watch and assess: looking around or checking what you know does not expose you. Acting on the world does. Moving, searching, taking something, speaking to someone, or similar successful actions leave cover. UNHIDE lets you step out deliberately.",
        "cue_speech": "Get out of sight before anyone comes through here. Look at the ground around you before choosing where to disappear. Some places give you real cover. Others leave you far more exposed.",
        "narration": "The alley remains quiet in this private lesson. You settle into cover. A successful HIDE remains secure.",
        "journal_entry": "HIDE holds while I watch and assess, and looking around or checking information keeps me concealed. Acting on the world ends it: moving, searching, taking, speaking, and similar successful actions leave cover. ATTACK uses my hidden advantage first and then consumes the hiding. UNHIDE steps out deliberately without going anywhere.",
    },
    {
        "verb": "search",
        "target": "loose brick",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "SEARCH LOOSE BRICK",
        "cue": "Hidden objects and passages never reveal themselves on their own. Searching acts on the world, so it draws you out of hiding as it works. SEARCH the right detail and your Perception determines what you notice. NPCs can give hints to where certain caches may reside waiting for you to uncover them.",
        "cue_speech": "While you were pressed against that wall, did you notice the brick beside your shoulder? Look again. It sits differently from the others, and the mortar around it has been disturbed more than once. Search the LOOSE BRICK and tell me what you find.",
        "narration": "You ease the loose brick free. A shallow hollow has been cut into the wall behind it. Inside rests a tarnished brass key and a folded scrap of paper, both wrapped in cloth to keep the damp away.",
        "journal_entry": "SEARCH can uncover hidden items, dead drops, and concealed passages. Searching acts on the world, so it ended my hiding and pulled me out of cover before it revealed the brick.",
    },
    {
        "verb": "take",
        "target": "tarnished brass key",
        "alt_target": "refugee_brass_key",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "TAKE TARNISHED BRASS KEY",
        "cue": "TAKE opens a chooser showing what is available to take. Take the tarnished brass key and keep it with you: a matching key is consumed when it opens the lock it fits.",
        "cue_speech": "Take the key with you. If someone went to the trouble of hiding it here, there is probably a lock somewhere that matters.",
        "narration": "The key is cold in your hand. The folded paper still lies in the hollow.",
    },
    {
        "verb": "take",
        "target": "crumpled note",
        "alt_target": "refugee_folded_note",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "TAKE CRUMPLED NOTE",
        "cue_speech": "And take the paper. Fold it up and keep it with you. A message hidden in a wall is only useful until someone else finds it.",
        "narration": "The paper is worn soft along the creases, small enough when folded to disappear into your palm.",
    },
    {
        "verb": "examine",
        "target": "crumpled note",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "EXAMINE CRUMPLED NOTE",
        "cue": "EXAMINE reveals more detail about an item. For readable items such as notes, it can also reveal what they say.",
        "cue_speech": "Do not carry a message you have not read. See what it actually says before you ASK ME about it.",
        "narration": "The note unfolds into cramped handwriting, the ink gone brown at the edges. It names a Doctor Li and mentions medicine being kept in a warehouse to the east.",
    },
    {
        "verb": "ask",
        "from_npc": "tutorial_comrade_chen",
        "required_indirect": "note",
        "requires_read_note": True,
        "hint_level": "explicit",
        "cmd_hint": "ASK COMRADE CHEN ABOUT NOTE",
        "npc_msg": "Doctor Li runs a clinic past the docks. The medicine is for his patients. You already have his name on that note, so there is no reason to write down anything more. Read what you find, remember what matters, and ask if something is unclear. The less unnecessary information you carry, the less you have to explain if a patrol searches you.",
        "narration": "Chen draws back the bolt. The east gate scrapes open.",
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "narration": "A broad-shouldered porter shoulders a stack of ration crates by the east door. He rolls his neck, ready for the walk to the market rows.",
        "stage_id": "back_alley_tail_intro",
        "hint_family": "tail",
        "from_npc": "tutorial_comrade_chen",
    },
    {
        "verb": "tail",
        "target": "market porter",
        "required_target": "tutorial_market_porter",
        "hint_level": "explicit",
        "cmd_hint": "TAIL MARKET PORTER",
        "cue": "Fang Jie tips her chin toward the porter. TAIL keeps you beside someone when they move, without typing every step. Stay with him and see how following works.",
        "cue_speech": "He runs that load to the market every morning. Walk with him once and the route will teach itself.",
        "journal_entry": "TAIL keeps me moving with someone else until I choose to STOP TAIL.",
    },
    {
        "verb": "stop",
        "action_room": "refugee_entry_market_street",
        "hint_level": "explicit",
        "cmd_hint": "STOP TAIL",
        "cue": "You break off as he angles toward his first delivery. STOP TAIL ends the follow cleanly, right where you stand.",
        "journal_entry": "STOP TAIL breaks off an active follow without fuss.",
    },
]

_ROOM_MARKET_STREET = [
    {"room_id": "refugee_entry_market_street"},
    {
    "teaching_hint": "Use STATUS to get a look at the current state of the world",
        "verb": "status",
        "from_npc": "tutorial_old_gao",
        "hint_level": "explicit",
        "cmd_hint": "STATUS",
    },
    {
        "verb": "buy",
        "target": "wooden_club",
        "alt_target": "quilted_jacket",
        "from_npc": "tutorial_old_gao",
        "confirm_on": "purchase",
        "flag": "tutorial_purchased_gear",
        "require_both": True,
        "required_targets": ["wooden_club", "quilted_jacket"],
        "hint_level": "explicit",
        "cmd_hint": "BUY FROM OLD GAO",
        "cue": "Gao taps the wooden club, then pinches the repaired shoulder of the jacket. The club is a weapon and the jacket is armour. They cost 12 and 18 fabi respectively.",
        "cue_speech": "Chen sent you? Then he should have told you the road east can be rough. Twelve for the club, eighteen for the jacket. Neither is much to look at, but both still do their job. If you mean to keep going, I would take both.",
    },
    {
        "verb": "equip",
        "target": "quilted_jacket",
        "alt_target": "wooden_club",
        "from_npc": "tutorial_old_gao",
        "hint_level": "explicit",
        "cmd_hint": "EQUIP {item:quilted_jacket}",
        "cue_speech": "Do not just carry them around. Put the jacket on and keep the club ready. The jacket will not protect you folded under your arm, and the club will not help much buried with the rest of your things.",
        "narration": "Gao releases the brake on the nearest handcart and rolls it clear of the eastern lane.",
        "npc_msg": "The warehouse is east. One soldier inside, unless someone has joined him since Chen last checked. He usually watches the far door more closely than the market entrance. Do not take a turned back for an invitation. Look at what is in front of you before you decide what to do.",
        "sub_hints": {
            "market_wear_jacket": {
                "stage_id": "market_wear_jacket",
                "cmd_hint": "EQUIP {item:quilted_jacket}",
                "hint_family": "equip",
                "required_item": "quilted_jacket",
                "state_check": "worn",
            },
            "market_equip_club": {
                "stage_id": "market_equip_club",
                "cmd_hint": "EQUIP {item:wooden_club}",
                "hint_family": "equip",
                "required_item": "wooden_club",
                "state_check": "equipped",
            },
        },
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_old_gao",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "blocked_exits": {"refugee_entry_market_street": {"east": {"stage": 21, "message": "A loaded handcart stands crosswise in the eastern lane."}}},
    },
]

_ROOM_WAREHOUSE = [
    {"room_id": "refugee_entry_warehouse"},
    {
        "verb": "assess",
        "target": "kempeitai soldier",
        "from_npc": "tutorial_kempeitai_soldier",
        "hint_level": "explicit",
        "cmd_hint": "ASSESS KEMPEITAI SOLDIER",
        "cue": "The soldier watches the far door, his back half-turned toward the market entrance. ASSESS shows a target's faction, role, Authority, Courage, and threat rating. Check it before you fight. Those details tell you what kind of opponent you are dealing with.",
    },
    {
        "verb": "attack",
        "target": "kempeitai soldier",
        "from_npc": "tutorial_kempeitai_soldier",
        "hint_level": "explicit",
        "cmd_hint": "ATTACK KEMPEITAI SOLDIER",
        "cue": _WAREHOUSE_ATTACK_CUE_TEMPLATE,
        "cue_speech": "Stop there. Put the club down.",
        "journal_entry": "ATTACK measures COURAGE plus my equipped weapon against the target's AUTHORITY. A curfew patrol arrest spends my one stored escape charge to move me through a legal exit; without that charge, I remain in custody until release.",
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "narration": "The soldier goes down. The warehouse falls quiet.",
    },
    {
        "verb": "open",
        "target": "rusted iron safe",
        "hint_level": "explicit",
        "cmd_hint": "OPEN RUSTED IRON SAFE",
        "cue": "The way to the rusted iron safe is clear. The brass key you found in the alley opens it. A matching key is consumed when it opens a lock, so use it here.",
    },
    {
        "verb": "take from",
        "target": "refugee_pistol",
        "alt_target": "refugee_coat",
        "source": "safe",
        "required_targets": ["refugee_pistol", "refugee_coat", "worn_medical_kit"],
        "hint_level": "explicit",
        "cmd_hint": "TAKE FROM RUSTED IRON SAFE",
        "journal_entry": "Recovered supplies for Dr. Li. Weapons and armour lose durability through use. Check their condition with INVENTORY.",
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "msg": "Weapons and armour wear with use. A broken weapon reduces your Courage, while broken armour no longer protects you. Check INVENTORY regularly to keep track of their condition.",
    },
    {
        "verb": "go",
        "target": "east",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "narration": "The eastern door groans open. Beyond it, a narrow passage leads toward the outpost.",
        "blocked_exits": {"refugee_entry_warehouse": {"east": {"stage": 28, "message": "The eastern door remains barred from this side."}}},
    },
]

_ROOM_OUTPOST = [
    {"room_id": "refugee_entry_outpost"},
    {
        "verb": "none",
        "hint_level": "silent",
        "narration": "The outpost is an inspection post. A desk sits beside the eastern stairwell, and the sergeant keeps the route beyond it under his eye.",
    },
    {
        "verb": "disguise as",
        "target": "japanese officer",
        "required_disguise": "japanese_officer",
        "from_npc": "tutorial_fang_jie",
        "hint_level": "explicit",
        "cmd_hint": "DISGUISE AS JAPANESE OFFICER",
        "cue": "Fang Jie catches your eye and briefly touches two fingers to her collar.",
        "cue_speech": "Before you go any farther, use what you took from the warehouse. A disguise only works if you own the exact disguise item. Watchers test their Perception against it, and every point of Wanted makes them more likely to see through you. If they pierce the disguise, the item is confiscated and they will fight you. Get changed now, while no one is paying enough attention to question it.",
    },
    {
        "verb": "go",
        "target": "west",
        "from_npc": "tutorial_fang_jie",
        "hint_level": "explicit",
        "stage_id": "checkpoint_go_west",
        "hint_family": "go",
        "cmd_hint": "GO WEST",
        "cue": "Not here. The sergeant holds this desk, and beyond it the stairwell to the roof.",
        "cue_speech": "Step back into the warehouse. Put some room between you, and give him a reason to leave his post. Follow, but let his footsteps measure the distance.",
    },
]

_ROOM_CHECKPOINT_CROSSING = [
    {"room_id": "refugee_entry_warehouse"},
    {
        "verb": "yell",
        "action_room": "refugee_entry_warehouse",
        "hint_level": "explicit",
        "stage_id": "checkpoint_yell",
        "hint_family": "yell",
        "cmd_hint": "YELL HEY",
        "require_npc_room": {"npc": "tutorial_kempeitai_officer", "room": "refugee_entry_outpost"},
        "cue": "The warehouse gives you room, and the sergeant still holds the checkpoint one room east. Sound carries between rooms: a yell reaches about three rooms, a gunshot four, and a silencer cancels the shot. Noise does not drive anyone away; it draws them toward its source. Shout something short from where you stand.",
        "journal_entry": "Sound propagates between rooms. A yell carries about three rooms. Guards who hear it move toward the source of the sound, never toward the words that were shouted.",
    },
    {
        "verb": "go",
        "target": "east",
        "action_room": "refugee_entry_warehouse",
        "hint_level": "explicit",
        "stage_id": "checkpoint_cross_outpost",
        "hint_family": "go",
        "cmd_hint": "GO EAST",
        "cue": "Boots hurry past on the market side, chasing the shout. The desk by the stairwell stands empty. Cross now, while his back is turned.",
        "blocked_exits": {"refugee_entry_warehouse": {"east": {
            "stage": 33,
            "live_window": 2,
            "message": "The sergeant still holds the checkpoint. Crossing now would put you straight through his hands.",
            "require_npc_room": {"npc": "tutorial_kempeitai_officer", "room": "refugee_entry_market_street"},
            "live_message": "The sergeant has not cleared the route yet. Wait until his search pulls him well away.",
        }}},
    },
    {
        "verb": "go",
        "target": "east",
        "action_room": "refugee_entry_outpost",
        "hint_level": "explicit",
        "stage_id": "checkpoint_cross_rooftop",
        "hint_family": "go",
        "cmd_hint": "GO EAST",
        "narration": "You cross the empty inspection post and climb the eastern stairwell.",
    },
]

_ROOM_ROOFTOP = [
    {"room_id": "refugee_entry_rooftop"},
    {
        "verb": "remove",
        "target": "disguise",
        "hint_level": "explicit",
        "cmd_hint": "REMOVE DISGUISE",
        "cue": "The roof is quiet. The sergeant is well off his post, pulled toward the market rows by a shout that never gave him a name. Up here you are only another figure among the laundry lines. The uniform has done its work; shed it before someone reads it too closely.",
    },
    {
        "verb": "go",
        "target": "east",
        "hint_level": "explicit",
        "stage_id": "rooftop_go_east",
        "hint_family": "go",
        "cmd_hint": "GO EAST",
        "narration": "The eastern stairs descend through the smell of river water and damp timber.",
        "blocked_exits": {"refugee_entry_rooftop": {"east": {"stage": 36, "message": "Move before the echo of your yell fades and he thinks to turn around."}}},
    },
]

_ROOM_DOCK = [
    {"room_id": "refugee_entry_dock"},
    {
        "verb": "none",
        "hint_level": "silent",
        "narration": "Doctor Li looks up from his bag. His eyes settle on the worn medical kit.",
    },
    {
        "verb": "give",
        "target": "worn_medical_kit",
        "from_npc": "tutorial_doctor_li",
        "hint_level": "explicit",
        "cmd_hint": "GIVE WORN MEDICAL KIT TO DOCTOR LI",
        "cue": "GIVE hands an item to an NPC. Delivering the right item to the right person can complete a mission objective.",
        "cue_speech": "You brought it. Good. There is a child upstairs whose fever has not broken since dawn, and his mother has been waiting for me to do something. Give me the kit. I can use what is inside.",
        "narration": "Doctor Li takes the kit. He opens the clasp with one thumb, checks the contents, then closes it and nods once.",
        "journal_entry": "GIVE hands items to NPCs. Delivering the right item to the right person can complete a mission objective.",
    },
    {
        "verb": "missions",
        "from_npc": "tutorial_doctor_li",
        "hint_level": "contextual",
        "cmd_hint": "MISSIONS",
        "msg": "MISSIONS lists the work you have already accepted, so this panel is empty until you take something on. In the city, work arrives through people: an encounter will offer you a task, and you will choose Accept, Decline, or Not now in that moment. Accept commits you to the job and locks the rival offers in the same dilemma. Decline permanently removes only the offer in front of you. Not now defers it until the next day. MISSIONS AVAILABLE reflects work your standing has unlocked, but only an encounter can put an offer in front of you. You can carry up to five jobs at once, and higher trust with a faction opens more of its work.",
        "cue_speech": "Now that the kit is here, see what other work you have taken on. There is always more to do than there are people to do it.",
        "journal_entry": "MISSIONS lists accepted work and stays empty until an encounter offers me a job. MISSIONS AVAILABLE reflects unlocked standing, but only an encounter can put an offer in front of me.",
    },
    {
        "verb": "journal",
        "hint_level": "contextual",
        "cmd_hint": "JOURNAL",
        "msg": "Your JOURNAL records names, clues, and unfinished business. Death is permanent, but the journal remains where you fell. The first finder claims its knowledge once, and later finders receive nothing. It is the record that can survive when your inventory does not.",
        "journal_entry": "Death is permanent. If I fall, my journal stays where I died, and the first finder claims its knowledge once.",
    },
    {
        "verb": "claim",
        "hint_level": "explicit",
        "cmd_hint": "CLAIM",
        "cue": "This shed can be made yours. CLAIM turns a safe room into your safehouse, and you can have only one safehouse per account. Visiting your claimed safehouse restores your one escape charge. If a curfew patrol arrests you, that charge is spent automatically to move you through a legal exit. Your stash is kept at your safehouse. This claim is practice for the lesson. In the city, gear left behind by a predecessor waits at the account safehouse, where a living successor can recover it with RETRIEVE.",
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_doctor_li",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "cue_speech": "The work here is done. The passage east runs beneath the Bund. Mind the steps. The brick stays wet even when the street above is dry.",
        "narration": "The eastern passage slopes beneath the Bund, its brickwork slick with river damp.",
        "blocked_exits": {"refugee_entry_dock": {"east": {"stage": 42, "message": "The eastern passage is still secured from this side."}}},
    },
]

_ROOM_EXIT_AND_ORIENTATION = [
    [{"room_id": "refugee_entry_cellar"}, {"verb": "none", "narration": "A tram bell sounds beyond the brickwork, followed by the low murmur of traffic along the river."}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST"}],
    [{"room_id": "refugee_entry_bund_exit"}, {"verb": "none", "narration": "At the western barrier, a guard closes one passbook and reaches for the next.", "blocked_exits": {"refugee_entry_bund_exit": {"south": {"stage": 65, "message": "The southern esplanade stays closed until the staged route is complete."}}}}, {"verb": "go", "target": "west", "cmd_hint": "GO WEST", "narration": "You follow the railings west until the checkpoint barrier blocks the road ahead."}],
    [{"room_id": "refugee_entry_checkpoint"}, {"verb": "none", "narration": "At the southern side of the barrier, an auxiliary lifts the rope and waves the next group through."}, {"verb": "go", "target": "south", "cmd_hint": "GO SOUTH", "from_npc": "tutorial_uncle_liu", "cue_speech": "Not yet. Stand beside me until that group clears the barrier. The auxiliary is checking bundles as closely as faces. If you are wanted, or carrying contraband, a checkpoint can turn dangerous quickly. Keep your hands where they can see them, answer only what you are asked, and move when I move.", "narration": "The rope drops behind you. The southern lane climbs between shuttered offices toward a roof crowded with instruments."}],
    [{"room_id": "orientation_weather"}, {"verb": "talk to", "target": "meteorologist zhang", "from_npc": "orientation_meteorologist_zhang", "cmd_hint": "TALK TO METEOROLOGIST ZHANG", "cue": "Zhang finishes a line in the ledger, sets down the chalk, and looks toward you.", "cue_speech": "The pressure has been falling since dawn. Rain should reach this district before noon. Pay attention to the weather when you make your plans. Fog makes it easier to stay hidden, but harder to notice what is around you. Rain muffles sound, while a storm carries sound farther. Winter makes hunger drain faster. Look at the sky before you plan to spend a night outside.", "narration": "Zhang picks up the chalk again. Beyond the instrument tables, the eastern door stands clear.", "blocked_exits": {"orientation_weather": {"east": {"stage": 50, "message": "Zhang has set aside his chalk and is waiting for you to speak."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass between the instrument tables and through the eastern door."}],
    [{"room_id": "orientation_trust"}, {"verb": "trust", "from_npc": "orientation_elder_qian", "cmd_hint": "TRUST", "cue": "TRUST shows how each faction currently regards you. Trust runs from 0 to 100. Helpful acts raise it, hostile acts lower it, and neglected relationships decay slowly. Higher trust can improve prices, dialogue, and access to faction work.", "cue_speech": "Mrs. Lin's word helped you with Chen. Somewhere else, being known to Chen might work against you. Do not assume every faction sees you the same way, or that an old relationship still stands where you left it. Check where you stand before you rely on it.", "narration": "Beyond the eastern door, a narrow corridor is lined with official notices and photographs.", "blocked_exits": {"orientation_trust": {"east": {"stage": 52, "message": "Check your faction trust levels before continuing."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass through the eastern door and enter the notice-lined corridor."}],
    [{"room_id": "orientation_wanted"}, {"verb": "wanted", "from_npc": "orientation_inspector_park", "cmd_hint": "WANTED", "cue": "Before entering the market, check whether the police are looking for you. WANTED shows your Wanted level from 0 to 3. It rises when you are caught breaking the law and falls after days without further trouble. Each level makes arrest more likely and disguises easier to pierce, and at level 2 ordinary vendors refuse to serve you.", "cue_speech": "Before you walk into that market, know how much attention you are drawing. The police do not need your name to remember you. A coat, a voice, the direction you ran, the same description passed between two posts can be enough. If people in uniform are beginning to look twice when you pass, it may be time to keep a lower profile.", "narration": "Beyond the eastern door, the official notices thin out and the corridor narrows toward a shuttered alley.", "blocked_exits": {"orientation_wanted": {"east": {"stage": 54, "message": "Check your wanted status before entering the market."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You leave the notice-covered walls behind and pass into the shuttered alley."}],
    [{"room_id": "orientation_blackmarket"}, {"verb": "talk to", "target": "old mother jin", "from_npc": "orientation_mother_jin", "cmd_hint": "TALK TO OLD MOTHER JIN", "cue": "Old Mother Jin pauses over a tray of wrapped parcels and looks up as you enter.", "npc_msg": "The scribe is beyond the next partition. Wen. He hears more than he says, which is why people keep finding reasons to visit him. The patrols call this lane the black market. Customers who earn enough trust can reach the Back Room, but anything bought there is contraband, and checkpoints take an interest in that sort of thing. When you see Wen, let him finish what he is doing before you start asking questions. He remembers who is impatient.", "narration": "Jin grips the handcart by its handles and draws it closer to the wall, clearing the eastern passage.", "npc_first": True, "blocked_exits": {"orientation_blackmarket": {"east": {"stage": 56, "message": "Jin's handcart still narrows the eastern passage."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass the stacked crates and follow the smell of ink through the eastern partition."}],
    [{"room_id": "orientation_rumors"}, {"verb": "rumors", "from_npc": "orientation_scribe_wen", "cmd_hint": "RUMORS", "cue": "Copied notices lie in neat stacks across Wen's desk, and his apprentice waits beside them with a fresh run of handbills. Their talk reached you the moment you stepped in: conversations appear on their own under Overheard Exchanges, and no command gathers them; standing in the room does. Information you have actually learned from people you have met settles separately under Known Rumours. RUMORS opens the panel so you can read both.", "cue_speech": "You arrived in the middle of a conversation. Good. Most of what this city knows is overheard, not told. The boy argues about grain prices because the press cannot keep its story straight. Read what reached you before you decide which version you believe.", "narration": "The exchange you overheard waits under Overheard Exchanges, and what you have learned from people you have met waits under Known Rumours.", "journal_entry": "RUMORS separates lasting information from conversations I overhear. Known Rumours keeps information I have learned; Overheard Exchanges keeps conversations that reached me in passing.", "blocked_exits": {"orientation_rumors": {"east": {"stage": 58, "message": "The eastern corridor is still closed off by a folding screen."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass the row of closed doors and follow the corridor to the listening post."}],
    [{"room_id": "orientation_eavesdrop"}, {"verb": "talk to", "target": "old crane", "from_npc": "orientation_old_crane", "cmd_hint": "TALK TO OLD CRANE", "cue": "Old Crane lowers one hand from the listening pipe. On the landing behind him, Widow Kang sets down her kettle, and the exchange you overheard between them as you climbed is already waiting under Overheard Exchanges in your Rumours panel. Presence alone brings the room's talk to you; no command gathers it.", "npc_msg": "You heard us on the stairs, so you already know how this works. What reaches you lands in the Rumours panel on its own. Drunk men exaggerate. Frightened men leave things out. Compare what you actually heard against what you are told before you decide what to repeat.", "narration": "The exchange you overheard between Old Crane and Widow Kang remains in your Rumours panel. Widow Kang collects the cups without hurry and takes her place by the eastern door.", "msg": "Old Crane nods once toward Widow Kang, who lifts the wooden latch from the eastern door. The passage beyond leads toward the Resistance Contact Point.", "journal_entry": "Room-local exchanges reach the Rumours panel automatically while I stand in the room. Old Crane taught me to compare overheard versions before repeating any of them.", "npc_first": True, "blocked_exits": {"orientation_eavesdrop": {"east": {"stage": 60, "message": "Old Crane has not yet lifted the latch on the eastern door."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You leave the listening pipe behind and pass through the eastern door."}],
    [{"room_id": "orientation_contact"}, {"verb": "talk to", "target": "sister zhao", "from_npc": "orientation_sister_zhao", "cmd_hint": "TALK TO SISTER ZHAO", "cue": "Sister Zhao turns toward you as you enter and waits for you to speak.", "npc_msg": "The passage east is clear for now. It was not clear an hour ago, and it may not be clear later. Keep moving until you reach the river road. Once you are out there, look before you step into the open. No one here can tell you what is waiting around the next corner.", "narration": "Zhao sets down her cup, crosses to the eastern door and draws back the wooden bolt.", "npc_first": True, "blocked_exits": {"orientation_contact": {"east": {"stage": 63, "message": "Sister Zhao has not yet opened the eastern door."}}}}, {"verb": "bond", "target": "sister zhao", "from_npc": "orientation_sister_zhao", "hint_level": "explicit", "cmd_hint": "BOND SISTER ZHAO", "cue": "Zhao gestures toward the food on the table and waits. BOND shares a meal with an NPC to build friendship and indebtedness. Friendship can keep doors open after the work is done, and the person you share with will remember the kindness. If you carry no food, TAKE the baozi beside the kettle first.", "cue_speech": "We share what we have in this house. Sit with me and eat before you go.", "journal_entry": "BOND shares food with an NPC to build friendship and indebtedness. Sister Zhao will remember the shared meal.", "narration": "You share the food with Sister Zhao. She nods once, and the eastern door stands ready."}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass through the eastern door and follow the narrow passage toward the river road."}],
    [{"room_id": "orientation_alley"}, {"verb": "look", "hint_level": "explicit", "cmd_hint": "LOOK", "teaching_hint": "LOOK reveals details in your current location before you move on.", "cue": "The last sheltered lesson happens here. LOOK takes in your surroundings: who shares the alley with you and which way out lies open.", "msg": "Beyond the southern mouth, the river road is open.", "blocked_exits": {"orientation_alley": {"south": {"stage": 65, "message": "Take stock of the alley before you step into the open street."}}}}, {"verb": "go", "target": "south", "cmd_hint": "GO SOUTH", "narration": "You leave the damp passage and step onto the broad road above the river."}],
]

_ROOM_ORDER = [
    _ROOM_TEA_HOUSE,
    _ROOM_BACK_ALLEY,
    _ROOM_MARKET_STREET,
    _ROOM_WAREHOUSE,
    _ROOM_OUTPOST,
    _ROOM_CHECKPOINT_CROSSING,
    _ROOM_ROOFTOP,
    _ROOM_DOCK,
    *_ROOM_EXIT_AND_ORIENTATION,
]

_STAGE_DEFS = []
for _block in _ROOM_ORDER:
    _STAGE_DEFS.extend(_block)

STAGE_ACTIONS: Dict[int, dict] = {}
STAGE_TARGETS: Dict[int, str] = {}
STAGE_BLOCKED_EXITS: Dict[int, dict] = {}
ROOM_FOR_STAGE: Dict[int, str] = {}

_STAGE_META: Dict[int, Dict[str, str]] = {
    0: {"stage_id": "tea_house_look", "hint_family": "look"},
    1: {"stage_id": "tea_house_talk", "hint_family": "talk_to"},
    3: {"stage_id": "tea_house_ask", "hint_family": "ask_about"},
    4: {"stage_id": "tea_house_buy", "hint_family": "buy_from"},
    5: {"stage_id": "tea_house_inventory", "hint_family": "inventory"},
    6: {"stage_id": "tea_house_eat", "hint_family": "eat"},
    7: {"stage_id": "tea_house_go_east", "hint_family": "go"},
    8: {"stage_id": "back_alley_talk", "hint_family": "talk_to"},
    9: {"stage_id": "back_alley_hide", "hint_family": "hide"},
    10: {"stage_id": "back_alley_search", "hint_family": "search"},
    11: {"stage_id": "back_alley_take_key", "hint_family": "take_item"},
    12: {"stage_id": "back_alley_take_note", "hint_family": "take_item"},
    13: {"stage_id": "back_alley_examine_note", "hint_family": "examine"},
    14: {"stage_id": "back_alley_ask_note", "hint_family": "ask_about"},
    15: {"stage_id": "back_alley_tail_intro", "hint_family": "tail"},
    16: {"stage_id": "back_alley_tail_follow", "hint_family": "tail"},
    17: {"stage_id": "back_alley_tail_break_off", "hint_family": "stop"},
    18: {"stage_id": "market_status", "hint_family": "status"},
    19: {"stage_id": "market_buy", "hint_family": "buy_from"},
    20: {"stage_id": "market_equip_gear"},
    21: {"stage_id": "market_go_east", "hint_family": "go"},
    22: {"stage_id": "warehouse_assess", "hint_family": "assess"},
    23: {"stage_id": "warehouse_attack", "hint_family": "attack"},
    25: {"stage_id": "warehouse_open_safe", "hint_family": "open"},
    26: {"stage_id": "warehouse_take_from_safe", "hint_family": "take_from"},
    28: {"stage_id": "warehouse_go_east", "hint_family": "go"},
    30: {"stage_id": "outpost_disguise", "hint_family": "disguise_as"},
    31: {"stage_id": "checkpoint_go_west", "hint_family": "go"},
    32: {"stage_id": "checkpoint_yell", "hint_family": "yell"},
    33: {"stage_id": "checkpoint_cross_outpost", "hint_family": "go"},
    34: {"stage_id": "checkpoint_cross_rooftop", "hint_family": "go"},
    35: {"stage_id": "rooftop_remove_disguise", "hint_family": "remove_disguise"},
    36: {"stage_id": "rooftop_go_east", "hint_family": "go"},
    38: {"stage_id": "dock_give_kit", "hint_family": "give"},
    39: {"stage_id": "dock_missions", "hint_family": "missions"},
    40: {"stage_id": "dock_journal", "hint_family": "journal"},
    41: {"stage_id": "dock_claim", "hint_family": "claim"},
    42: {"stage_id": "dock_go_east", "hint_family": "go"},
    44: {"stage_id": "cellar_go_east", "hint_family": "go"},
    46: {"stage_id": "bund_exit_go_west", "hint_family": "go"},
    48: {"stage_id": "checkpoint_go_south", "hint_family": "go"},
    49: {"stage_id": "weather_talk", "hint_family": "talk_to"},
    50: {"stage_id": "weather_go_east", "hint_family": "go"},
    51: {"stage_id": "trust_check", "hint_family": "trust"},
    52: {"stage_id": "trust_go_east", "hint_family": "go"},
    53: {"stage_id": "wanted_check", "hint_family": "wanted"},
    54: {"stage_id": "wanted_go_east", "hint_family": "go"},
    55: {"stage_id": "blackmarket_talk", "hint_family": "talk_to"},
    56: {"stage_id": "blackmarket_go_east", "hint_family": "go"},
    57: {"stage_id": "rumors_check", "hint_family": "rumors"},
    58: {"stage_id": "rumors_go_east", "hint_family": "go"},
    59: {"stage_id": "eavesdrop_talk", "hint_family": "talk_to"},
    60: {"stage_id": "eavesdrop_go_east", "hint_family": "go"},
    61: {"stage_id": "contact_talk", "hint_family": "talk_to"},
    62: {"stage_id": "contact_bond", "hint_family": "bond"},
    63: {"stage_id": "contact_go_east", "hint_family": "go"},
    64: {"stage_id": "alley_look", "hint_family": "look"},
    65: {"stage_id": "alley_go_south", "hint_family": "go"},
}

_stage_idx = 0
for _block in _ROOM_ORDER:
    _room_id = ""
    for _stage_def in _block:
        if "room_id" in _stage_def:
            _room_id = _stage_def["room_id"]
            continue
        if _room_id:
            ROOM_FOR_STAGE[_stage_idx] = _room_id
        _stage_idx += 1

_stage_idx = 0
for _d in _STAGE_DEFS:
    if "room_id" in _d:
        continue
    _action = {"verb": _d["verb"], "stage": _stage_idx}
    for _k in ("target", "source", "cmd_hint", "teaching_hint", "journal_entry",
                   "alt_verb", "alt_target", "alt_source", "reward",
                   "confirm_on", "from_npc", "npc_msg", "indirect_state",
                   "required_indirect", "requires_read_note", "note", "require_both", "flag", "narration",
                   "stage_id", "hint_family", "cue", "cue_speech", "topics",
                   "arrival_text", "required_targets", "sub_hints",
                   "required_disguise", "required_target", "npc_first",
                   "require_npc_room"):
        if _d.get(_k):
            _action[_k] = _d[_k]
    if _d.get("msg"):
        _action["advance_message"] = _d["msg"]
    if _d.get("response_msg"):
        _action["response_message"] = _d["response_msg"]
    if _d.get("hint_level"):
        _action["hint_level"] = _d["hint_level"]
    if _d.get("narration"):
        _action["narration"] = _d["narration"]
    room_id = ROOM_FOR_STAGE.get(_stage_idx)
    if _d.get("action_room"):
        _action["room_id"] = _d["action_room"]
    elif room_id:
        _action["room_id"] = room_id

    sid = _d.get("stage_id") or _STAGE_META.get(_stage_idx, {}).get("stage_id", "")
    fam = _d.get("hint_family") or _STAGE_META.get(_stage_idx, {}).get("hint_family", "")
    if sid:
        _action["stage_id"] = sid
    if fam:
        _action["hint_family"] = fam

    STAGE_ACTIONS[_stage_idx] = _action
    if _d.get("target"):
        STAGE_TARGETS[_stage_idx] = _d["target"]
    if "blocked_exits" in _d:
        STAGE_BLOCKED_EXITS[_stage_idx] = _d["blocked_exits"]
    _stage_idx += 1

TUTORIAL_ROOM_IDS: List[str] = [
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


CONTACT_BOND_FOOD_ITEM_ID = "baozi"
_CONTACT_BOND_STAGE_IDS = ("contact_talk", "contact_bond")

ROOFTOP_REMOVE_DISGUISE_STAGE_ID = "rooftop_remove_disguise"
FANG_JIE_TUTORIAL_NPC_ID = "tutorial_fang_jie"
FANG_JIE_ENCOUNTER_STAGE_IDS = frozenset({
    "outpost_disguise",
    "checkpoint_go_west",
    "checkpoint_yell",
    "checkpoint_cross_outpost",
    "checkpoint_cross_rooftop",
})

_FANG_JIE_HELD_NARRATION = (
    "Fang Jie's gaze lingers on the uniform a moment longer than is comfortable, then moves on."
)
_FANG_JIE_HELD_HINT = (
    "Your disguise held this time. Observant characters may still see through a disguise."
)
_FANG_JIE_EXPOSED_NARRATION = "Fang Jie looks from the coat to your face."
_FANG_JIE_EXPOSED_SPEECH = "Clothes can fool a sentry. They cannot fool everyone."
_FANG_JIE_EXPOSED_HINT = (
    "Fang Jie saw through your disguise. Exposure can end the identity you were presenting."
)

_EXPOSED_ROOFTOP_OVERRIDE = {
    "verb": "status",
    "target": "",
    "cmd_hint": "STATUS",
    "hint_family": "status",
    "cue": (
        "The roof is quiet. The uniform got you past the sentry, but not past Fang Jie's eyes. "
        "The borrowed rank ended at her glance; see your situation plainly before you move on."
    ),
    "teaching_hint": (
        "Exposure ends the identity you were presenting. "
        "Use STATUS to confirm that you are no longer disguised."
    ),
}

_EXPOSED_ROOFTOP_ACTION: Optional[dict] = None


def exposed_rooftop_action() -> dict:
    global _EXPOSED_ROOFTOP_ACTION
    if _EXPOSED_ROOFTOP_ACTION is None:
        for action in STAGE_ACTIONS.values():
            if action.get("stage_id") == ROOFTOP_REMOVE_DISGUISE_STAGE_ID:
                variant = dict(action)
                variant.update(_EXPOSED_ROOFTOP_OVERRIDE)
                _EXPOSED_ROOFTOP_ACTION = variant
                break
    return _EXPOSED_ROOFTOP_ACTION or {}


def stage_action_for(player: Any, stage: int) -> dict:
    action = STAGE_ACTIONS.get(stage) or {}
    if action.get("stage_id") != ROOFTOP_REMOVE_DISGUISE_STAGE_ID:
        return action
    if getattr(player, "disguise", ""):
        return action
    return exposed_rooftop_action()


async def note_tutorial_disguise_pierce(ctx, npc, pierce_stage: Any) -> None:
    from .stealth import PierceStage

    player = ctx.session.player
    if not getattr(player, "in_tutorial", False):
        return
    npc_id = str(getattr(npc, "id", ""))
    if not npc_id.endswith(FANG_JIE_TUTORIAL_NPC_ID):
        return
    action = STAGE_ACTIONS.get(getattr(player, "tutorial_stage", 0)) or {}
    if action.get("stage_id") not in FANG_JIE_ENCOUNTER_STAGE_IDS:
        return
    exposed = pierce_stage == PierceStage.EXPOSED
    marker = "fang_jie_disguise_exposed" if exposed else "fang_jie_disguise_held"
    emitted = getattr(player, "tutorial_entries_emitted", None)
    if emitted is None:
        emitted = set()
        player.tutorial_entries_emitted = emitted
    if marker in emitted:
        return
    emitted.add(marker)
    if exposed:
        await ctx.session.send_display(
            _FANG_JIE_EXPOSED_NARRATION, msg_type=MessageType.TUTORIAL
        )
        await ctx.session.send_npc_speech(
            npc_id, getattr(npc, "name", "Fang Jie"), _FANG_JIE_EXPOSED_SPEECH
        )
        payload = _FANG_JIE_EXPOSED_HINT
    else:
        await ctx.session.send_display(
            _FANG_JIE_HELD_NARRATION, msg_type=MessageType.TUTORIAL
        )
        payload = _FANG_JIE_HELD_HINT
    await ctx.session.send_hint(
        hint_id=marker,
        stage_id=marker,
        payload=payload,
        immediate=True,
        room_id=getattr(player, "current_room", ""),
    )


@dataclass(frozen=True)
class TutorialEvent:

    verb: str
    target: str = ""
    indirect: str = ""
    room_id: str = ""
    succeeded: bool = True


def _normalise_tutorial_value(value: str) -> str:
    tokens = (value or "").lower().replace("_", " ").split()
    return " ".join(t.rstrip(".") for t in tokens)


def stage_accepts_event(action: dict, event: TutorialEvent, player: Any = None) -> bool:
    if not action or not event.succeeded or action.get("verb") == "none":
        return False
    expected_room = action.get("room_id", "")
    if expected_room and event.room_id != expected_room and not event.room_id.endswith(f"_{expected_room}"):
        return False
    if action.get("requires_read_note") and (
        player is None or not getattr(player, "tutorial_read_note", False)
    ):
        return False
    sub_hints = action.get("sub_hints") or {}
    if sub_hints:
        event_verb = _normalise_tutorial_value(event.verb)
        event_target = _normalise_tutorial_value(event.target or "")
        for _sid, sub in sub_hints.items():
            sub_family = sub.get("hint_family", "")
            sub_item = _normalise_tutorial_value(sub.get("required_item", ""))
            if _normalise_tutorial_value(sub_family) == event_verb and sub_item == event_target:
                return True
        return False

    expected_verb = _normalise_tutorial_value(action.get("event", action.get("verb", "")))
    if expected_verb != _normalise_tutorial_value(event.verb):
        return False
    required_targets = action.get("required_targets", [])
    if required_targets:
        if _normalise_tutorial_value(event.target) not in {
            _normalise_tutorial_value(target) for target in required_targets
        }:
            return False
        if player is None:
            return False
        progress = getattr(player, "tutorial_progress", None)
        if progress is None:
            progress = {}
            player.tutorial_progress = progress
        key = f"stage_{action.get('stage', id(action))}"
        required_normalized = {_normalise_tutorial_value(target) for target in required_targets}
        completed = progress.setdefault(key, set())
        completed.add(_normalise_tutorial_value(event.target))
        gathered = {
            _normalise_tutorial_value(entry)
            for entry in completed
            if _normalise_tutorial_value(entry) in required_normalized
        }
        return len(gathered) == len(required_normalized)
    expected_target = _normalise_tutorial_value(action.get("target", ""))
    if expected_target:
        return _normalise_tutorial_value(event.target) in {
            expected_target,
            _normalise_tutorial_value(action.get("alt_target", "")),
        }
    required_indirect = _normalise_tutorial_value(action.get("required_indirect", ""))
    if required_indirect and _normalise_tutorial_value(event.indirect) != required_indirect:
        return False
    return True


def tutorial_set_confirmation(player, stage: int, verb: str) -> None:
    confirmations = getattr(player, "tutorial_confirmation", None)
    if confirmations is None:
        confirmations = {}
        player.tutorial_confirmation = confirmations
    confirmed = confirmations.setdefault(f"stage_{stage}", [])
    confirmed.append(_normalise_tutorial_value(verb))
    progress = getattr(player, "tutorial_progress", None)
    if progress is None:
        progress = {}
        player.tutorial_progress = progress
    progress.setdefault(f"stage_{stage}", set()).add(_normalise_tutorial_value(verb))


def advance_tutorial_stage(player) -> None:
    player.tutorial_stage = getattr(player, "tutorial_stage", 0) + 1


async def advance_tutorial(
    ctx,
    verb: str,
    target: str,
    indirect: str,
    raw_verb: str = "",
) -> None:
    player = ctx.session.player
    stage = getattr(player, "tutorial_stage", 0)
    action = stage_action_for(player, stage)
    if not action:
        return
    if action.get("verb") == "none":
        await _advance_stage(ctx, stage, action)
        return

    if action.get("sub_hints"):
        return

    confirmation = _normalise_tutorial_value(action.get("confirm_on", ""))
    if confirmation:
        if _event_has_succeeded(player, action, TutorialEvent(verb, target, indirect, ""), ctx.shared):
            await _advance_stage(ctx, stage, action)
        else:
            await _emit_stage_entry(ctx)
        return

    if stage_accepts_event(
        action,
        TutorialEvent(verb, target, indirect, getattr(player, "current_room", "")),
        player,
    ):
        await _advance_stage(ctx, stage, action)

def _slot_holds_catalog_item(player, slot_attr: str, item_id: str) -> bool:
    slot = getattr(player, slot_attr, "") or ""
    if not slot:
        return False
    if slot == item_id:
        return True
    from .equipment import equipped_item
    item = equipped_item(player, slot)
    return item is not None and item.id == item_id


def _event_has_succeeded(player, action: dict, event: TutorialEvent, shared=None) -> bool:
    stage = getattr(player, "tutorial_stage", 0)
    if action.get("sub_hints"):
        return False
    confirmation = _normalise_tutorial_value(action.get("confirm_on", ""))
    if confirmation:
        required_targets = action.get("required_targets") or []
        if required_targets:
            progress = getattr(player, "tutorial_progress", None) or {}
            purchased = progress.get(f"stage_{stage}", set())
            needed = set(required_targets)
            return needed.issubset(purchased)

        confirmed = getattr(player, "tutorial_confirmation", {}).get(
            f"stage_{stage}", []
        )
        required = 2 if action.get("require_both") else 1
        return len(confirmed) >= required

    required_disguise = action.get("required_disguise", "")
    if required_disguise:
        return getattr(player, "disguise", "") == required_disguise

    if event.verb == "go":
        return event.room_id != getattr(player, "current_room", "")
    if event.verb == "hide":
        return bool(getattr(player, "hidden", False))
    if event.verb == "remove":
        return not bool(getattr(player, "disguised_as", None))
    if event.verb == "take":
        expected = {
            _normalise_tutorial_value(action.get("target", "")),
            _normalise_tutorial_value(action.get("alt_target", "")),
        }
        return any(
            _normalise_tutorial_value(getattr(item, "id", "")) in expected
            or _normalise_tutorial_value(getattr(item, "name", "")) in expected
            for item in getattr(player, "inventory", [])
        )
    req = action.get("require_npc_room")
    if req and shared is not None:
        req_npc = req["npc"]
        req_room = req["room"]
        if getattr(player, "in_tutorial", False):
            instance_id = getattr(player, "tutorial_instance_id", "")
            req_npc = f"tut_{instance_id}_{req_npc}"
            req_room = get_cloned_room_id(instance_id, req_room, shared)
        if getattr(shared.world, "npc_locations", {}).get(req_npc) != req_room:
            return False
    if event.verb == "yell":
        if shared is None:
            return True
        target_room = getattr(player, "current_room", "")
        for npc in getattr(shared.world, "npcs", {}).values():
            if getattr(npc, "faction", "") != "kempeitai":
                continue
            if int(getattr(npc, "hp", 100)) <= 0:
                continue
            blackboard = getattr(npc, "_blackboard", None)
            heard = (blackboard.get("last_heard_sound") if blackboard else None) or {}
            if (
                heard.get("investigator_target_room_id") == target_room
                or heard.get("room_id") == target_room
            ):
                return True
        return False
    return True


def tutorial_dialogue_for_stage(player, npc_id: str, world, topic: str = "") -> list:
    npc = world.npcs.get(npc_id) if world else None
    if npc is None:
        return []
    td = getattr(npc, "tutorial_dialogue", None) or {}
    stage = getattr(player, "tutorial_stage", 0)
    if topic:
        topic_key = f"stage_{stage}_{_normalise_tutorial_value(topic).replace(' ', '_')}"
        topic_lines = td.get(topic_key)
        if isinstance(topic_lines, list) and topic_lines:
            strings = [line for line in topic_lines if isinstance(line, str) and line.strip()]
            if strings:
                return strings
    lines = td.get(f"stage_{stage}")
    if isinstance(lines, list) and lines:
        strings = [line for line in lines if isinstance(line, str) and line.strip()]
        if strings:
            return strings
    any_lines = td.get("stage_any")
    if isinstance(any_lines, list):
        strings = [line for line in any_lines if isinstance(line, str) and line.strip()]
        if strings:
            return strings
    return []


def tutorial_blocks_world_events(player) -> bool:
    return getattr(player, "tutorial_choice_pending", False) or getattr(
        player, "in_tutorial", False
    )


def normalize_to_actionable_stage(player) -> int:
    stage = getattr(player, "tutorial_stage", 0)
    for _ in range(len(STAGE_ACTIONS) + 1):
        action = STAGE_ACTIONS.get(stage)
        if not action or action.get("verb") != "none":
            break
        stage += 1
    if stage != getattr(player, "tutorial_stage", 0):
        player.tutorial_stage = stage
    return stage


DISGUISE_REMOVAL_BLOCKED_STAGE_IDS = frozenset({
    "outpost_disguise",
    "checkpoint_go_west",
    "checkpoint_yell",
    "checkpoint_cross_outpost",
})


def stage_blocks_disguise_removal(player) -> bool:
    stage = getattr(player, "tutorial_stage", 0)
    action = STAGE_ACTIONS.get(stage) or {}
    return action.get("stage_id") in DISGUISE_REMOVAL_BLOCKED_STAGE_IDS


def live_npc_exit_blocks(player, shared, room_id: str) -> dict:
    stage = getattr(player, "tutorial_stage", 0)
    instance_id = getattr(player, "tutorial_instance_id", "")
    result: dict = {}
    if not instance_id:
        return result
    for blocks in STAGE_BLOCKED_EXITS.values():
        for direction, info in blocks.get(room_id, {}).items():
            req = info.get("require_npc_room")
            if not req:
                continue
            release_gate = info.get("stage", 0)
            window = release_gate + info.get("live_window", 99)
            if stage < release_gate or stage > window:
                continue
            npc_id = f"tut_{instance_id}_{req['npc']}"
            required_room = get_cloned_room_id(instance_id, req["room"], shared)
            if shared.world.npc_locations.get(npc_id) != required_room:
                result[direction] = info.get(
                    "live_message",
                    info.get("message", "Complete the current objective first."),
                )
    return result


def blocked_exits_for_room(room_id: str, stage: int) -> dict:
    result: dict = {}
    for blocks in STAGE_BLOCKED_EXITS.values():
        room_blocks = blocks.get(room_id, {})
        for direction, info in room_blocks.items():
            if info.get("require_npc_room"):
                continue
            release = info.get("stage", 0)
            if stage < release:
                result[direction] = info.get(
                    "message", "Complete the current objective first."
                )
    return result


def hint_family_for(action: dict) -> str:
    return action.get("hint_family") or action.get("verb") or ""


async def _send_tutorial_payload(ctx, text: str, *, msg_type: MessageType = MessageType.TUTORIAL) -> None:
    if not text:
        return
    await ctx.session.send_display(text, msg_type=msg_type.value)


async def _send_tutorial_hint(ctx, stage: int, action: dict, force_immediate: bool = False) -> None:
    player = ctx.session.player
    payload = render_stage_hint(
        action,
        getattr(ctx.shared.world, "item_catalog", None),
        player=player,
    )
    if not payload:
        return
    family = hint_family_for(action)
    hint_id = action.get("stage_id") or f"stage_{stage}"
    emitted = getattr(player, "tutorial_emitted_hints", None)
    if emitted is None:
        emitted = set()
        player.tutorial_emitted_hints = emitted
    if hint_id in emitted and not force_immediate:
        return
    emitted.add(hint_id)
    uses = getattr(player, "tutorial_command_uses", None) or {}
    immediate = bool(force_immediate or uses.get(family, 0) == 0)
    await ctx.session.send_hint(
        hint_id=hint_id,
        stage_id=hint_id,
        payload=payload,
        immediate=immediate,
        room_id=getattr(player, "current_room", ""),
    )


async def _emit_stage_entry(ctx, replay_only: bool = False, force_immediate: bool = False) -> None:
    player = ctx.session.player
    stage = normalize_to_actionable_stage(player)
    action = stage_action_for(player, stage)
    if not action or getattr(player, "tutorial_stage", 0) >= len(STAGE_ACTIONS):
        return

    entries_emitted = getattr(player, "tutorial_entries_emitted", None)
    if entries_emitted is None:
        entries_emitted = set()
        player.tutorial_entries_emitted = entries_emitted
    hint_id = action.get("stage_id") or f"stage_{stage}"
    first_emit = hint_id not in entries_emitted

    if not replay_only and first_emit:
        cue = action.get("cue", "")
        if cue and action.get("stage_id") == WAREHOUSE_ATTACK_STAGE_ID:
            cue = format_warehouse_attack_cue(
                cue, runtime_warehouse_attack_values(ctx, action)
            )
        if cue:
            await _send_tutorial_payload(ctx, cue, msg_type=MessageType.TUTORIAL)
        from_npc = action.get("from_npc", "")
        if from_npc:
            npc = ctx.shared.world.npcs.get(from_npc)
            if npc:
                cue_speech = action.get("cue_speech", "")
                if cue_speech:
                    await ctx.session.send_npc_speech(from_npc, npc.name, cue_speech)
        entries_emitted.add(hint_id)
    if action.get("hint_level") == "explicit" or force_immediate:
        await _send_tutorial_hint(ctx, stage, action, force_immediate=True)

    topics = action.get("topics") or []
    if topics:
        from .npc import humanize_topic_key
        await _send_tutorial_payload(
            ctx,
            "Topics: " + ", ".join(humanize_topic_key(t) for t in topics),
            msg_type=MessageType.TUTORIAL,
        )


async def _advance_stage(ctx, stage: int, action: dict) -> None:
    player = ctx.session.player
    await _send_advance_message(ctx, stage, action)
    advance_tutorial_stage(player)
    while True:
        next_stage = getattr(player, "tutorial_stage", 0)
        next_action = stage_action_for(player, next_stage)
        if not next_action or next_action.get("verb") != "none":
            break
        await _send_advance_message(ctx, next_stage, next_action)
        advance_tutorial_stage(player)
    new_stage = getattr(player, "tutorial_stage", 0)
    new_action = stage_action_for(player, new_stage)
    if new_action.get("stage_id") == "back_alley_tail_break_off":
        _run_porter_choreography(ctx)
    if getattr(player, "tutorial_stage", 0) >= len(STAGE_ACTIONS):
        await complete_tutorial(ctx)
        return
    if not action.get("sub_hints"):
        uses = getattr(player, "tutorial_command_uses", None)
        if uses is None:
            uses = {}
            player.tutorial_command_uses = uses
        family = hint_family_for(action)
        if family:
            uses[family] = uses.get(family, 0) + 1
    await _emit_stage_entry(ctx)


async def complete_tutorial(ctx) -> None:
    await graduate_tutorial_player(ctx, "Tutorial complete. Welcome to Shanghai.")


async def _send_graduation_cue(ctx, message: str) -> None:
    await ctx.session.send_display(
        f"{message} LOOK around and choose a direction.",
        msg_type=MessageType.TUTORIAL.value,
    )


async def graduate_tutorial_player(ctx, message: str, *, send_handoff: bool = True) -> None:
    player = ctx.session.player
    tutorial_room = ctx.shared.world.get_room(player.current_room)
    if tutorial_room and player.username in tutorial_room.players:
        tutorial_room.players.remove(player.username)
    if "tutorial_complete" not in player.flags:
        player.flags.append("tutorial_complete")
    instance_id = getattr(player, "tutorial_instance_id", "")
    if instance_id:
        destroy_tutorial_clones_for_player(instance_id, ctx.shared)
        player.tutorial_instance_id = ""
    player.in_tutorial = False
    player.tutorial_choice_pending = False
    player.tutorial_stage = len(STAGE_ACTIONS)
    player.tutorial_confirmation = {}
    player.tutorial_progress = {}
    player.tutorial_resume_room_id = ""
    player.tutorial_revealed_rooms = []
    player.tutorial_vendor_depletion = {}
    player.tutorial_social_exchanges = {}
    player.current_room = "bund_dawn"
    player.map_revealed = ["bund_dawn"]
    bund_room = ctx.shared.world.get_room(player.current_room)
    if bund_room and player.username not in bund_room.players:
        bund_room.players.append(player.username)
    manager = getattr(ctx, "session_manager", None)
    if manager:
        manager._strip_to_rice(player)
        if send_handoff and hasattr(manager, "_send_map_data"):
            await manager._send_map_data(ctx.session)
    await ctx.session.send_hint_clear()
    try:
        from .auth import set_tutorial_complete
        set_tutorial_complete(ctx.session.username)
    except Exception:
        logger.exception("Failed to persist tutorial completion for %s", ctx.session.username)

    for attr in ("claimed_safehouse_id",):
        if hasattr(player, attr):
            try:
                setattr(player, attr, "")
            except Exception:
                pass

    from .popup_payloads import close_popup_if_kind
    await close_popup_if_kind(ctx, "stash", "invalid")
    if send_handoff:
        await _send_graduation_cue(ctx, message)

async def record_tutorial_event(ctx, event: TutorialEvent, action: Optional[dict] = None) -> bool:
    try:
        return await _record_tutorial_event_inner(ctx, event, action)
    finally:
        _ensure_contact_bond_food(ctx.session.player, ctx.shared)


async def _record_tutorial_event_inner(
    ctx, event: TutorialEvent, action: Optional[dict] = None
) -> bool:
    player = ctx.session.player
    stage = getattr(player, "tutorial_stage", 0)
    if action is None:
        action = stage_action_for(player, stage)
    if action and action.get("confirm_on") == "purchase" and event.verb == "buy":
        tutorial_set_confirmation(player, stage, verb="purchase")
        if event.target:
            progress = getattr(player, "tutorial_progress", None)
            if progress is None:
                progress = {}
                player.tutorial_progress = progress
            progress.setdefault(f"stage_{stage}", set()).add(event.target)
    if not action or not stage_accepts_event(action, event, player):
        return False

    if action.get("sub_hints") and event.verb == "equip":
        sub_hints = action.get("sub_hints") or {}
        target_norm = _normalise_tutorial_value(event.target or "")
        matched_sub = None
        for sub_id, sub in sub_hints.items():
            required = _normalise_tutorial_value(sub.get("required_item", ""))
            if required == target_norm:
                matched_sub = sub
                break

        if not matched_sub:
            return False

        state_check = matched_sub.get("state_check", "")
        if state_check == "worn":
            state_ok = _slot_holds_catalog_item(player, "worn_armour_id", matched_sub.get("required_item", ""))
        elif state_check == "equipped":
            state_ok = _slot_holds_catalog_item(player, "equipped_weapon_id", matched_sub.get("required_item", ""))
        else:
            state_ok = True

        if not state_ok:
            return False

        progress = getattr(player, "tutorial_progress", None)
        if progress is None:
            progress = {}
            player.tutorial_progress = progress
        completed = progress.setdefault(f"stage_{stage}", set())
        completed.add(matched_sub.get("required_item", ""))

        sub_family = matched_sub.get("hint_family", "")
        if sub_family:
            uses = getattr(player, "tutorial_command_uses", None)
            if uses is None:
                uses = {}
                player.tutorial_command_uses = uses
            family = sub_family
            if matched_sub.get("required_item", "") not in completed or len(completed) == 1:
                uses[family] = uses.get(family, 0)
            families_done = progress.setdefault(f"stage_{stage}_families", set())
            if family not in families_done:
                uses[family] = uses.get(family, 0) + 1
                families_done.add(family)

        required_items = {
            sub.get("state_check"): sub.get("required_item")
            for sub in sub_hints.values()
        }
        worn_ok = _slot_holds_catalog_item(
            player, "worn_armour_id", required_items.get("worn")
        ) if required_items.get("worn") else True
        equip_ok = _slot_holds_catalog_item(
            player, "equipped_weapon_id", required_items.get("equipped")
        ) if required_items.get("equipped") else True
        if worn_ok and equip_ok:
            await _advance_stage(ctx, stage, action)
            return True

        await _emit_stage_entry(ctx)
        return True

    if not _event_has_succeeded(player, action, event, ctx.shared):
        return False
    await _advance_stage(ctx, stage, action)
    return True


def _run_porter_choreography(ctx) -> None:
    from .curfew import game_clock_total_minutes
    from .law import wanted_consequences

    player = ctx.session.player
    instance_id = getattr(player, "tutorial_instance_id", "")
    clock = getattr(ctx.session_manager, "world_clock", None)
    if not instance_id or clock is None:
        return
    porter_id = f"tut_{instance_id}_tutorial_market_porter"
    alley_id = get_cloned_room_id(instance_id, "refugee_entry_back_alley", ctx.shared)
    market_id = get_cloned_room_id(instance_id, "refugee_entry_market_street", ctx.shared)
    if ctx.shared.world.npc_locations.get(porter_id) != alley_id:
        return
    if not ctx.shared.world.rooms.get(market_id):
        return
    clock._move_npc_between_rooms(porter_id, alley_id, market_id, "east")
    tail = getattr(player, "tailing_state", None)
    if not tail or tail.target_npc_id != porter_id:
        return
    from .equipment import advance_tail_clock, resolve_tail_step
    from .constants import get_season
    total = game_clock_total_minutes(ctx.shared.game_time)
    advance_tail_clock(player, total)
    target = ctx.shared.world.npcs.get(porter_id)
    resolve_tail_step(
        player,
        target,
        tail,
        clock.stealth,
        clock.disguises,
        wanted_bonus=wanted_consequences(player.wanted_level).disguise_perception_bonus,
        current_room=ctx.shared.world.get_room(player.current_room),
        target_room=market_id,
        season=get_season(ctx.shared.game_time.day),
    )


def _dispatch_choreography_sound(ctx, original_room_id: str) -> None:
    player = ctx.session.player
    instance_id = getattr(player, "tutorial_instance_id", "")
    clock = getattr(ctx.session_manager, "world_clock", None)
    if not instance_id or clock is None:
        return
    clone_room_id = get_cloned_room_id(instance_id, original_room_id, ctx.shared)
    if clone_room_id == original_room_id or not ctx.shared.world.rooms.get(clone_room_id):
        return
    clock._dispatch_world_sound(clone_room_id, 2, "distant disturbance")


async def _send_advance_message(ctx, stage: int, action: dict) -> None:
    is_go_stage = action.get("verb") == "go"
    narration = action.get("narration", "")
    advance_msg = action.get("advance_message", "")
    npc_msg = action.get("npc_msg", "")
    if action.get("npc_first"):
        if npc_msg:
            from_npc = action.get("from_npc", "")
            npc = ctx.shared.world.npcs.get(from_npc) if from_npc else None
            if npc:
                await ctx.session.send_npc_speech(from_npc, npc.name, npc_msg)
        if narration and not is_go_stage:
            await _send_tutorial_payload(ctx, narration, msg_type=MessageType.ROOM_DESCRIPTION)
        if advance_msg:
            await _send_tutorial_payload(ctx, advance_msg, msg_type=MessageType.TUTORIAL)
    else:
        if narration and not is_go_stage:
            await _send_tutorial_payload(ctx, narration, msg_type=MessageType.ROOM_DESCRIPTION)
        if advance_msg:
            await _send_tutorial_payload(ctx, advance_msg, msg_type=MessageType.TUTORIAL)
        if npc_msg:
            from_npc = action.get("from_npc", "")
            npc = ctx.shared.world.npcs.get(from_npc) if from_npc else None
            if npc:
                await ctx.session.send_npc_speech(from_npc, npc.name, npc_msg)

    journal_entry = action.get("journal_entry", "")
    if journal_entry:
        from .journal import record_tutorial_journal_lesson
        stage_key = action.get("stage_id") or f"stage_{stage}"
        record_tutorial_journal_lesson(ctx.session.player, stage_key, journal_entry)

def _try_stage_match(stage: int, verb: str, target: str, indirect: str, action: dict = None) -> bool:
    if action is None:
        action = STAGE_ACTIONS.get(stage)
    if not action:
        return False

    expected_verb = action.get("verb", "")
    expected_target = action.get("target", "")
    expected_source = action.get("source", "")
    alt_verb = action.get("alt_verb", "")
    alt_target = action.get("alt_target", "")

    verb_match = (verb == expected_verb) or (alt_verb and verb == alt_verb)
    if not verb_match:
        return False

    if expected_target:
        target_match = (target == expected_target) or (alt_target and target == alt_target)
        if not target_match:
            return False

    if expected_source and indirect:
        if indirect != expected_source:
            return False

    indirect_state = action.get("indirect_state", "")
    if indirect_state == "empty" and indirect:
        return False
    if indirect_state == "present" and not indirect:
        return False
    required_indirect = _normalise_tutorial_value(action.get("required_indirect", ""))
    if required_indirect and _normalise_tutorial_value(indirect) != required_indirect:
        return False

    return True


def check_tutorial_progress(player, verb: str, target: str = "", indirect: str = "") -> bool:
    stage = getattr(player, "tutorial_stage", 0)
    action = stage_action_for(player, stage)
    if not action:
        return False
    room_id = getattr(player, "current_room", "")
    return stage_accepts_event(
        action,
        TutorialEvent(verb=verb, target=target, indirect=indirect, room_id=room_id),
        player,
    )


def get_tutorial_hint(player, shared=None) -> str:
    stage = getattr(player, "tutorial_stage", 0)
    action = stage_action_for(player, stage)
    if not action:
        return ""
    catalog = getattr(getattr(shared, "world", None), "item_catalog", None)
    try:
        return render_cmd_hint(action.get("cmd_hint", ""), item_catalog=catalog, player=player)
    except ValueError as exc:
        logger.error("tutorial command hint dropped: %s", exc)
        return ""


def restart_tutorial(player, shared) -> None:
    from .economy import set_wallet_fabi_value

    player.tutorial_stage = 0
    player.in_tutorial = True
    player.tutorial_choice_pending = False
    player.tutorial_confirmation = {}
    player.tutorial_progress = {}
    player.tutorial_read_note = False
    player.tutorial_last_room = ""
    player.tutorial_resume_room_id = ""
    player.tutorial_revealed_rooms = []
    player.tutorial_vendor_depletion = {}
    player.tutorial_social_exchanges = {}
    player.tutorial_command_uses = {}
    player.tutorial_emitted_hints = set()
    player.tutorial_entries_emitted = set()
    player.tutorial_death_warning_shown = False

    if "tutorial_complete" in player.flags:
        player.flags.remove("tutorial_complete")

    if hasattr(player, "tutorial_instance_id") and player.tutorial_instance_id:
        destroy_tutorial_clones_for_player(player.tutorial_instance_id, shared)

    instance_id = clone_tutorial_rooms_for_player(shared.world, id(player), shared)
    player.tutorial_instance_id = instance_id

    player.current_room = get_cloned_room_id(instance_id, "refugee_entry_tea_house", shared)
    player.map_revealed = [player.current_room]
    player.tutorial_resume_room_id = "refugee_entry_tea_house"
    player.tutorial_revealed_rooms = ["refugee_entry_tea_house"]
    set_wallet_fabi_value(player, 50)

    logger.info("Tutorial restarted for player %s (instance=%s)", id(player), instance_id)


def get_cloned_room_id(instance_id: str, original_room_id: str, shared) -> str:
    clone_map = shared.tutorial_room_clones.get(instance_id, {})
    return clone_map.get(original_room_id, original_room_id)


def get_original_tutorial_room_id(instance_id: str, room_id: str, shared) -> str:
    clone_map = shared.tutorial_room_clones.get(instance_id, {})
    for original_room_id, cloned_room_id in clone_map.items():
        if cloned_room_id == room_id:
            return original_room_id
    return room_id


def get_canonical_tutorial_npc_id(instance_id: str, npc_id: str) -> str:
    prefix = f"tut_{instance_id}_"
    if npc_id.startswith(prefix):
        return npc_id[len(prefix):]
    return npc_id


def update_tutorial_resume_state(player, shared) -> None:
    if not getattr(player, "in_tutorial", False):
        return
    instance_id = getattr(player, "tutorial_instance_id", "")
    current_room = get_original_tutorial_room_id(
        instance_id, getattr(player, "current_room", ""), shared,
    )
    if current_room in TUTORIAL_ROOM_IDS:
        player.tutorial_resume_room_id = current_room
    revealed_rooms = []
    for room_id in getattr(player, "map_revealed", []) or []:
        original_room_id = get_original_tutorial_room_id(instance_id, room_id, shared)
        if original_room_id in TUTORIAL_ROOM_IDS and original_room_id not in revealed_rooms:
            revealed_rooms.append(original_room_id)
    if player.tutorial_resume_room_id and player.tutorial_resume_room_id not in revealed_rooms:
        revealed_rooms.append(player.tutorial_resume_room_id)
    player.tutorial_revealed_rooms = revealed_rooms


def record_tutorial_vendor_depletion(player, vendor_id: str, item_id: str) -> None:
    depleted = getattr(player, "tutorial_vendor_depletion", None)
    if depleted is None:
        depleted = {}
        player.tutorial_vendor_depletion = depleted
    item_ids = depleted.setdefault(vendor_id, [])
    if item_id not in item_ids:
        item_ids.append(item_id)


def _tutorial_vendor_item_id(item_data) -> str:
    if isinstance(item_data, dict):
        return item_data.get("item_id") or item_data.get("id") or ""
    return str(item_data)


def restore_tutorial_vendor_depletion(player, shared) -> None:
    instance_id = getattr(player, "tutorial_instance_id", "")
    for canonical_vendor, item_ids in getattr(player, "tutorial_vendor_depletion", {}).items():
        vendor_id = f"tut_{instance_id}_{canonical_vendor}"
        vendor = shared.world.npcs.get(vendor_id)
        if not vendor:
            continue
        vendor.shop_inventory = [
            item_data for item_data in getattr(vendor, "shop_inventory", []) or []
            if _tutorial_vendor_item_id(item_data) not in item_ids
        ]


def ensure_tutorial_instance_for_player(player, shared) -> None:
    if not getattr(player, "in_tutorial", False):
        return
    instance_id = getattr(player, "tutorial_instance_id", "")
    if instance_id and shared.tutorial_room_clones.get(instance_id):
        return
    current_room = getattr(player, "current_room", "")
    if (
        not getattr(player, "tutorial_resume_room_id", "")
        and current_room not in TUTORIAL_ROOM_IDS
        and shared.world.get_room(current_room)
    ):
        return
    instance_id = clone_tutorial_rooms_for_player(shared.world, id(player), shared)
    player.tutorial_instance_id = instance_id
    canonical_room = getattr(player, "tutorial_resume_room_id", "") or "refugee_entry_tea_house"
    player.current_room = get_cloned_room_id(instance_id, canonical_room, shared)
    revealed_rooms = getattr(player, "tutorial_revealed_rooms", []) or [canonical_room]
    player.map_revealed = [
        get_cloned_room_id(instance_id, room_id, shared)
        for room_id in revealed_rooms
        if room_id in TUTORIAL_ROOM_IDS
    ]
    if player.current_room not in player.map_revealed:
        player.map_revealed.append(player.current_room)
    restore_tutorial_vendor_depletion(player, shared)
    _apply_resume_semantics(player, shared)


def _ensure_contact_bond_food(player, shared) -> None:
    instance_id = getattr(player, "tutorial_instance_id", "")
    if not instance_id:
        return
    stage = getattr(player, "tutorial_stage", 0)
    stage_id = (STAGE_ACTIONS.get(stage) or {}).get("stage_id", "")
    if stage_id not in _CONTACT_BOND_STAGE_IDS:
        return
    room_id = get_cloned_room_id(instance_id, "orientation_contact", shared)
    room = shared.world.rooms.get(room_id)
    if not room:
        return
    if any(getattr(item, "food_value", 0) > 0 for item in getattr(player, "inventory", [])):
        return
    if any(getattr(item, "id", "") == CONTACT_BOND_FOOD_ITEM_ID for item in room.items):
        return
    template = shared.world.item_catalog.get(CONTACT_BOND_FOOD_ITEM_ID)
    if not template:
        return
    from copy import deepcopy
    room.items.append(deepcopy(template))


def _apply_resume_semantics(player, shared) -> None:
    stage = getattr(player, "tutorial_stage", 0)
    action = STAGE_ACTIONS.get(stage) or {}
    stage_id = action.get("stage_id", "")
    instance_id = getattr(player, "tutorial_instance_id", "")
    if not instance_id:
        return
    porter_id = f"tut_{instance_id}_tutorial_market_porter"
    officer_id = f"tut_{instance_id}_tutorial_kempeitai_officer"

    def place(npc_suffix, original_room):
        npc_id = f"tut_{instance_id}_{npc_suffix}"
        room_id = get_cloned_room_id(instance_id, original_room, shared)
        if npc_id in shared.world.npcs and shared.world.rooms.get(room_id):
            shared.world.npc_locations[npc_id] = room_id

    if stage_id == "back_alley_tail_break_off":
        place("tutorial_market_porter", "refugee_entry_market_street")
        market = get_cloned_room_id(instance_id, "refugee_entry_market_street", shared)
        player.current_room = market
    elif stage_id in ("checkpoint_yell",):
        place("tutorial_kempeitai_officer", "refugee_entry_outpost")
        place("tutorial_market_porter", "refugee_entry_warehouse")
    elif stage_id in ("checkpoint_cross_outpost", "checkpoint_cross_rooftop",
                      "rooftop_remove_disguise", "rooftop_go_east"):
        place("tutorial_kempeitai_officer", "refugee_entry_market_street")
        place("tutorial_market_porter", "refugee_entry_market_street")

    if stage_id in _CONTACT_BOND_STAGE_IDS:
        _ensure_contact_bond_food(player, shared)


def clone_tutorial_rooms_for_player(world, player_id: int, shared_state) -> str:
    import uuid
    instance_id = str(uuid.uuid4())[:8]

    clone_map: Dict[str, str] = {}
    for room_id in TUTORIAL_ROOM_IDS:
        original_room = world.rooms.get(room_id)
        if not original_room:
            continue
        cloned_id = f"tut_{instance_id}_{room_id}"
        cloned_room = world.clone_room(room_id, cloned_id)
        if cloned_room:
            world.rooms[cloned_id] = cloned_room
            clone_map[room_id] = cloned_id
            shared_state.cloned_tutorial_rooms[cloned_id] = cloned_room

    npc_clones: List[str] = []
    for original_id, cloned_id in clone_map.items():
        cloned_room = world.rooms.get(cloned_id)
        if not cloned_room:
            continue
        remapped_exits: Dict[str, str] = {}
        for direction, dest_id in cloned_room.exits.items():
            if dest_id in clone_map:
                remapped_exits[direction] = clone_map[dest_id]
            else:
                remapped_exits[direction] = dest_id
        cloned_room.exits = remapped_exits

        private_npcs = []
        for npc_id in cloned_room.npcs:
            npc = world.npcs.get(npc_id)
            if not npc:
                continue
            from copy import deepcopy
            cloned_npc_id = f"tut_{instance_id}_{npc_id}"
            cloned_npc = deepcopy(npc)
            cloned_npc.id = cloned_npc_id
            cloned_npc.schedule = {}
            world.npcs[cloned_npc_id] = cloned_npc
            world.npc_locations[cloned_npc_id] = cloned_id
            private_npcs.append(cloned_npc_id)
            npc_clones.append(cloned_npc_id)
        cloned_room.npcs = private_npcs

    _canonical_roster = {
        "tutorial_mrs_lin": "refugee_entry_tea_house",
        "tutorial_comrade_chen": "refugee_entry_back_alley",
        "tutorial_old_gao": "refugee_entry_market_street",
        "tutorial_kempeitai_soldier": "refugee_entry_warehouse",
        "tutorial_fang_jie": "refugee_entry_outpost",
        "tutorial_kempeitai_officer": "refugee_entry_outpost",
        "tutorial_doctor_li": "refugee_entry_dock",
        "tutorial_uncle_liu": "refugee_entry_checkpoint",
        "orientation_meteorologist_zhang": "orientation_weather",
        "orientation_elder_qian": "orientation_trust",
        "orientation_inspector_park": "orientation_wanted",
        "orientation_mother_jin": "orientation_blackmarket",
        "orientation_scribe_wen": "orientation_rumors",
        "orientation_apprentice_shen": "orientation_rumors",
        "orientation_old_crane": "orientation_eavesdrop",
        "orientation_widow_kang": "orientation_eavesdrop",
        "orientation_sister_zhao": "orientation_contact",
        "orientation_alley_drunk_merchant": "orientation_alley",
        "orientation_patrol_guard": "orientation_alley",
    }
    for canonical_npc_id, original_room_id in _canonical_roster.items():
        cloned_room_id = clone_map.get(original_room_id)
        cloned_room = world.rooms.get(cloned_room_id) if cloned_room_id else None
        if not cloned_room:
            continue
        cloned_npc_id = f"tut_{instance_id}_{canonical_npc_id}"
        if cloned_npc_id not in world.npcs:
            from copy import deepcopy
            canonical_npc = world.npcs.get(canonical_npc_id)
            if not canonical_npc:
                continue
            cloned_npc = deepcopy(canonical_npc)
            cloned_npc.id = cloned_npc_id
            cloned_npc.schedule = {}
            world.npcs[cloned_npc_id] = cloned_npc
            npc_clones.append(cloned_npc_id)
        if cloned_npc_id not in cloned_room.npcs:
            cloned_room.npcs.append(cloned_npc_id)
        world.npc_locations[cloned_npc_id] = cloned_room_id

    _safe_original = world.item_catalog.get("refugee_iron_safe")
    if _safe_original:
        _warehouse_clone_id = clone_map.get("refugee_entry_warehouse")
        _warehouse_clone = world.rooms.get(_warehouse_clone_id) if _warehouse_clone_id else None
        if _warehouse_clone:
            from copy import deepcopy
            _safe = deepcopy(_safe_original)
            _safe.locked = True
            _safe.container_items = []
            for _cid in ("refugee_pistol", "refugee_coat", "worn_medical_kit"):
                _tmpl = world.item_catalog.get(_cid)
                if _tmpl:
                    _safe.container_items.append(deepcopy(_tmpl))
            _warehouse_clone.items.append(_safe)

    _alley_clone_id = clone_map.get("refugee_entry_back_alley")
    _alley_clone = world.rooms.get(_alley_clone_id) if _alley_clone_id else None
    if _alley_clone:
        from .world import Item as _TutorialItem
        _key = _TutorialItem(
            id="refugee_brass_key",
            name="a tarnished brass key",
            description="A tarnished brass key with a worn square bow, kept wrapped in cloth.",
            takeable=True,
            is_key=True,
            key_id="refugee_brass_key",
        )
        _alley_clone.dead_drops.append({"signal": "loose brick", "recipient": "", "item": _key})
        _note = _TutorialItem(
            id="refugee_folded_note",
            name="a crumpled note",
            description="A scrap of paper folded small, the ink gone brown at the edges.",
            takeable=True,
            is_note=True,
            durability=1,
            max_durability=1,
            note_text="Doctor Li at the harbour dock. Medicine held in the warehouse to the east.",
        )
        _alley_clone.items.append(_note)

        _dock_clone_id = clone_map.get("refugee_entry_dock")
        _dock_clone = world.rooms.get(_dock_clone_id) if _dock_clone_id else None
        if _dock_clone:
            _dock_clone.safe_room = True

    shared_state.tutorial_room_clones[instance_id] = clone_map
    shared_state.tutorial_npc_clones[instance_id] = npc_clones
    logger.info("Cloned %d tutorial rooms for player %s (instance=%s)",
                len(clone_map), player_id, instance_id)
    return instance_id


def destroy_tutorial_clones_for_player(instance_id: str, shared) -> None:
    clone_map = shared.tutorial_room_clones.pop(instance_id, {})
    for cloned_id in clone_map.values():
        shared.cloned_tutorial_rooms.pop(cloned_id, None)
        shared.world.rooms.pop(cloned_id, None)
    for npc_id in shared.tutorial_npc_clones.pop(instance_id, []):
        shared.world.npcs.pop(npc_id, None)
        shared.world.npc_locations.pop(npc_id, None)
    count = len(clone_map)
    if count:
        logger.info("Destroyed %d cloned rooms for instance %s", count, instance_id)
