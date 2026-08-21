import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .constants import MessageType
from .formatting import format_tutorial_text
from .world import Room

logger = logging.getLogger(__name__)

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
        "teaching_hint": "BUY FROM <NPC NAME> opens a vendor's shop. Not every NPC is a vendor.",
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
        "cue": "HIDE is deterministic. Room details show the Stealth requirement before you act: real cover requires 25 Stealth, ordinary rooms require 50, and exposed or authority-controlled areas require 75. Meet the requirement and HIDE succeeds. Once successfully hidden, patrols and observers do not overturn that success. This private tutorial has no live patrol, but in the main game patrols move through rooms and can limit how long you can safely remain and interact with people. Read the room before you hide.",
        "cue_speech": "Get out of sight before anyone comes through here. Look at the ground around you before choosing where to disappear. Some places give you real cover. Others leave you far more exposed.",
        "narration": "The alley remains quiet in this private lesson. You settle into cover. A successful HIDE remains secure.",
    },
    {
        "verb": "search",
        "target": "loose brick",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "SEARCH LOOSE BRICK",
        "cue": "Hidden objects and passages rarely reveal themselves on their own. SEARCH the right detail and your Perception determines what you notice.",
        "cue_speech": "While you were pressed against that wall, did you notice the brick beside your shoulder? Look again. It sits differently from the others, and the mortar around it has been disturbed more than once. Search the LOOSE BRICK and tell me what you find.",
        "narration": "You ease the loose brick free. A shallow hollow has been cut into the wall behind it. Inside rests a tarnished brass key and a folded scrap of paper, both wrapped in cloth to keep the damp away.",
        "journal_entry": "SEARCH can uncover hidden items, dead drops, and concealed passages. Behind a loose brick in the alley, I found a brass key and a folded note.",
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
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "blocked_exits": {"refugee_entry_back_alley": {"east": {"stage": 15, "message": "A locked gate blocks the eastern passage."}}},
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
        "verb": "wear",
        "target": "quilted_jacket",
        "alt_target": "wooden_club",
        "from_npc": "tutorial_old_gao",
        "hint_level": "explicit",
        "cmd_hint": "WEAR QUILTED JACKET",
        "cue_speech": "Do not just carry them around. Put the jacket on and keep the club ready. The jacket will not protect you folded under your arm, and the club will not help much buried with the rest of your things.",
        "narration": "Gao releases the brake on the nearest handcart and rolls it clear of the eastern lane.",
        "npc_msg": "The warehouse is east. One soldier inside, unless someone has joined him since Chen last checked. He usually watches the far door more closely than the market entrance. Do not take a turned back for an invitation. Look at what is in front of you before you decide what to do.",
        "sub_hints": {
            "market_wear_jacket": {
                "stage_id": "market_wear_jacket",
                "cmd_hint": "WEAR QUILTED JACKET",
                "hint_family": "wear",
                "required_item": "quilted_jacket",
                "state_check": "worn",
            },
            "market_equip_club": {
                "stage_id": "market_equip_club",
                "cmd_hint": "EQUIP WOODEN CLUB",
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
        "blocked_exits": {"refugee_entry_market_street": {"east": {"stage": 19, "message": "A loaded handcart stands crosswise in the eastern lane."}}},
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
        "cue": "The soldier turns toward you. His eyes settle on the club in your hand, then on your face. He reaches for the rifle beside him and steps between you and the safe. You have been made. Combat can kill you, and death is permanent. If you die, your journal remains where you fell, and the first finder can claim its knowledge once. Combat resolves in a single exchange: your Courage plus your equipped weapon is measured against the soldier's Authority. Meet or exceed it and you win the fight.",
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
        "blocked_exits": {"refugee_entry_warehouse": {"east": {"stage": 26, "message": "The eastern door remains barred from this side."}}},
    },
    {
        "verb": "none",
        "hint_level": "silent",
    },
]

_ROOM_OUTPOST = [
    {"room_id": "refugee_entry_outpost"},
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
        "verb": "tail",
        "target": "officer",
        "required_target": "tutorial_kempeitai_officer",
        "from_npc": "tutorial_fang_jie",
        "hint_level": "explicit",
        "cmd_hint": "TAIL OFFICER",
        "cue": "As the officer turns toward the stairwell, Fang Jie tilts her head after him. TAIL follows an NPC from room to room. The target checks your disguise when the tail begins and again every five minutes. Suspicion lets the tail continue, a challenge ends it but leaves your disguise intact, and exposure ends the tail and confiscates the disguise item.",
        "cue_speech": "He is moving. Keep him in sight until you know where he is going. Do not cut across the route or guess where he will turn.",
    },
    {
        "verb": "go",
        "target": "east",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "narration": "His footsteps climb the stairs ahead of you.",
        "blocked_exits": {"refugee_entry_outpost": {"east": {"stage": 30, "message": "The officer still occupies the route to the stairwell."}}},
    },
]

_ROOM_ROOFTOP = [
    {"room_id": "refugee_entry_rooftop"},
    {
        "verb": "none",
        "hint_level": "silent",
        "narration": "The stairs open onto the roof. The officer has stopped at the western parapet, watching the streets below.",
    },
    {
        "verb": "yell",
        "hint_level": "explicit",
        "cmd_hint": "YELL TOWARD THE ALLEY",
        "cue": "Laundry lifts between you and the parapet, and the western alley disappears beyond the roof edge. Sound travels between rooms: a yell carries about three rooms, while a gunshot carries four. A silencer cancels a gunshot's reach. Noise can draw nearby watchers, and this time that is exactly what you want. Yell toward the alley to draw the officer away from the eastern stairwell.",
        "journal_entry": "Sound propagates between rooms. A yell carries about three rooms. A gunshot carries four, while a silencer cancels its reach.",
    },
    {
        "verb": "remove",
        "target": "disguise",
        "hint_level": "explicit",
        "cmd_hint": "REMOVE DISGUISE",
        "cue": "The laundry settles around you. For the first time since the outpost, no uniformed eyes are watching.",
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "narration": "The eastern stairwell is clear.",
    },
    {
        "verb": "go",
        "target": "east",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "narration": "The eastern stairs descend through the smell of river water and damp timber.",
        "blocked_exits": {"refugee_entry_rooftop": {"east": {"stage": 35, "message": "The officer still commands the open roof between you and the eastern stairwell."}}},
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
        "msg": "MISSIONS shows your current work. MISSIONS AVAILABLE shows authored opportunities that are offered through NPC encounters. When an encounter presents a mission, you can Accept, Decline, or choose Not now. Accept commits you to that mission and locks the rival offers in the same dilemma. Decline permanently removes only the offer in front of you. Not now defers that offer until the next day. Objectives can ask you to collect an item, deliver something to someone, talk to a person, or visit a place. You can carry up to five missions at once, and higher trust with a faction unlocks more of its work.",
        "cue_speech": "Now that the kit is here, see what other work you have taken on. There is always more to do than there are people to do it.",
        "journal_entry": "MISSIONS shows your progress. MISSIONS AVAILABLE finds work. During an encounter, Accept commits you to the mission, Decline permanently removes that one offer, and Not now defers it until the next day.",
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
        "blocked_exits": {"refugee_entry_dock": {"east": {"stage": 41, "message": "The eastern passage is still secured from this side."}}},
    },
]

_ROOM_EXIT_AND_ORIENTATION = [
    [{"room_id": "refugee_entry_cellar"}, {"verb": "none", "narration": "A tram bell sounds beyond the brickwork, followed by the low murmur of traffic along the river."}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST"}],
    [{"room_id": "refugee_entry_bund_exit"}, {"verb": "none", "narration": "At the western barrier, a guard closes one passbook and reaches for the next.", "blocked_exits": {"refugee_entry_bund_exit": {"south": {"stage": 64, "message": "The southern esplanade stays closed until the staged route is complete."}}}}, {"verb": "go", "target": "west", "cmd_hint": "GO WEST", "narration": "You follow the railings west until the checkpoint barrier blocks the road ahead."}],
    [{"room_id": "refugee_entry_checkpoint"}, {"verb": "none", "narration": "At the southern side of the barrier, an auxiliary lifts the rope and waves the next group through."}, {"verb": "go", "target": "south", "cmd_hint": "GO SOUTH", "from_npc": "tutorial_uncle_liu", "cue_speech": "Not yet. Stand beside me until that group clears the barrier. The auxiliary is checking bundles as closely as faces. If you are wanted, or carrying contraband, a checkpoint can turn dangerous quickly. Keep your hands where they can see them, answer only what you are asked, and move when I move.", "narration": "The rope drops behind you. The southern lane climbs between shuttered offices toward a roof crowded with instruments."}],
    [{"room_id": "orientation_weather"}, {"verb": "talk to", "target": "meteorologist zhang", "from_npc": "orientation_meteorologist_zhang", "cmd_hint": "TALK TO METEOROLOGIST ZHANG", "cue": "Zhang finishes a line in the ledger, sets down the chalk, and looks toward you.", "cue_speech": "The pressure has been falling since dawn. Rain should reach this district before noon. Pay attention to the weather when you make your plans. Fog makes it easier to stay hidden, but harder to notice what is around you. Rain muffles sound, while a storm carries sound farther. Winter makes hunger drain faster. Look at the sky before you plan to spend a night outside.", "narration": "Zhang picks up the chalk again. Beyond the instrument tables, the eastern door stands clear.", "blocked_exits": {"orientation_weather": {"east": {"stage": 49, "message": "Zhang has set aside his chalk and is waiting for you to speak."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass between the instrument tables and through the eastern door."}],
    [{"room_id": "orientation_trust"}, {"verb": "trust", "from_npc": "orientation_elder_qian", "cmd_hint": "TRUST", "cue": "TRUST shows how each faction currently regards you. Trust runs from 0 to 100. Helpful acts raise it, hostile acts lower it, and neglected relationships decay slowly. Higher trust can improve prices, dialogue, and access to faction work.", "cue_speech": "Mrs. Lin's word helped you with Chen. Somewhere else, being known to Chen might work against you. Do not assume every faction sees you the same way, or that an old relationship still stands where you left it. Check where you stand before you rely on it.", "narration": "Beyond the eastern door, a narrow corridor is lined with official notices and photographs.", "blocked_exits": {"orientation_trust": {"east": {"stage": 51, "message": "Check your faction trust levels before continuing."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass through the eastern door and enter the notice-lined corridor."}],
    [{"room_id": "orientation_wanted"}, {"verb": "wanted", "from_npc": "orientation_inspector_park", "cmd_hint": "WANTED", "cue": "Before entering the market, check whether the police are looking for you. WANTED shows your Wanted level from 0 to 3. It rises when you are caught breaking the law and falls after days without further trouble. Each level makes arrest more likely and disguises easier to pierce, and at level 2 ordinary vendors refuse to serve you.", "cue_speech": "Before you walk into that market, know how much attention you are drawing. The police do not need your name to remember you. A coat, a voice, the direction you ran, the same description passed between two posts can be enough. If people in uniform are beginning to look twice when you pass, it may be time to keep a lower profile.", "narration": "Beyond the eastern door, the official notices thin out and the corridor narrows toward a shuttered alley.", "blocked_exits": {"orientation_wanted": {"east": {"stage": 53, "message": "Check your wanted status before entering the market."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You leave the notice-covered walls behind and pass into the shuttered alley."}],
    [{"room_id": "orientation_blackmarket"}, {"verb": "talk to", "target": "old mother jin", "from_npc": "orientation_mother_jin", "cmd_hint": "TALK TO OLD MOTHER JIN", "cue": "Old Mother Jin pauses over a tray of wrapped parcels and looks up as you enter.", "npc_msg": "The scribe is beyond the next partition. Wen. He hears more than he says, which is why people keep finding reasons to visit him. The patrols call this lane the black market. Customers who earn enough trust can reach the Back Room, but anything bought there is contraband, and checkpoints take an interest in that sort of thing. When you see Wen, let him finish what he is doing before you start asking questions. He remembers who is impatient.", "narration": "Jin grips the handcart by its handles and draws it closer to the wall, clearing the eastern passage.", "npc_first": True, "blocked_exits": {"orientation_blackmarket": {"east": {"stage": 55, "message": "Jin's handcart still narrows the eastern passage."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass the stacked crates and follow the smell of ink through the eastern partition."}],
    [{"room_id": "orientation_rumors"}, {"verb": "rumors", "from_npc": "orientation_scribe_wen", "cmd_hint": "RUMORS", "cue": "Copied notices lie in neat stacks across Wen's desk. A second pile of loose slips waits beside his brush. RUMORS opens your Rumours panel in two sections: Known Rumours you have gathered and Overheard Exchanges reaching you right now. Rumours can also surface through conversation, and asking people about what you hear may reveal more. As a rumour spreads, factions may alter the version that reaches you.", "cue_speech": "Those slips beside the brush are today's talk. Some describe the same event differently. Look at who passed each version along before you decide which one you believe.", "narration": "Wen turns a page and draws the folding screen closer to the wall. Beyond it, a corridor of closed doors leads toward the listening post.", "blocked_exits": {"orientation_rumors": {"east": {"stage": 57, "message": "The eastern corridor is still closed off by a folding screen."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass the row of closed doors and follow the corridor to the listening post."}],
    [{"room_id": "orientation_eavesdrop"}, {"verb": "talk to", "target": "old crane", "from_npc": "orientation_old_crane", "cmd_hint": "TALK TO OLD CRANE", "cue": "Old Crane lowers one hand from the listening pipe and studies you across the narrow room.", "npc_msg": "Keep your voice down. That brass pipe carries talk from the rooms below better than the open window carries anything from the street. Sit here long enough and you will hear arguments, bargains, names people should know better than to say aloud, and every so often something worth remembering. Drunk men exaggerate. Frightened men leave things out. Compare what you hear before you decide what to repeat.", "narration": "The exchanges carried through this room reach your Rumours panel as they are heard.", "msg": "Old Crane reaches past the worn chair and lifts the wooden latch from the eastern door. The passage beyond leads toward the Resistance Contact Point.", "npc_first": True, "blocked_exits": {"orientation_eavesdrop": {"east": {"stage": 59, "message": "Old Crane has not yet lifted the latch on the eastern door."}}}}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You leave the listening pipe behind and pass through the eastern door."}],
    [{"room_id": "orientation_contact"}, {"verb": "talk to", "target": "sister zhao", "from_npc": "orientation_sister_zhao", "cmd_hint": "TALK TO SISTER ZHAO", "cue": "Sister Zhao turns toward you as you enter and waits for you to speak.", "npc_msg": "The passage east is clear for now. It was not clear an hour ago, and it may not be clear later. Keep moving until you reach the river road. Once you are out there, look before you step into the open. No one here can tell you what is waiting around the next corner.", "narration": "Zhao sets down her cup, crosses to the eastern door and draws back the wooden bolt.", "npc_first": True, "blocked_exits": {"orientation_contact": {"east": {"stage": 62, "message": "Sister Zhao has not yet opened the eastern door."}}}}, {"verb": "bond", "target": "sister zhao", "from_npc": "orientation_sister_zhao", "hint_level": "explicit", "cmd_hint": "BOND SISTER ZHAO", "cue": "Zhao glances at the food you carry and waits. BOND shares a meal with an NPC to build friendship and indebtedness. Friendship can keep doors open after the work is done, and the person you share with will remember the kindness.", "cue_speech": "We share what we have in this house. Sit with me and eat before you go.", "journal_entry": "BOND shares food with an NPC to build friendship and indebtedness. Sister Zhao will remember the shared meal.", "narration": "You share the food with Sister Zhao. She nods once, and the eastern door stands ready."}, {"verb": "go", "target": "east", "cmd_hint": "GO EAST", "narration": "You pass through the eastern door and follow the narrow passage toward the river road."}],
    [{"room_id": "orientation_alley"}, {"verb": "look", "cmd_hint": "LOOK", "msg": "Beyond the southern mouth, the river road is open.", "blocked_exits": {"orientation_alley": {"south": {"stage": 64, "message": "Take stock of the alley before you step into the open street."}}}}, {"verb": "go", "target": "south", "cmd_hint": "GO SOUTH", "narration": "You leave the damp passage and step onto the broad road above the river."}],
]

_ROOM_ORDER = [
    _ROOM_TEA_HOUSE,
    _ROOM_BACK_ALLEY,
    _ROOM_MARKET_STREET,
    _ROOM_WAREHOUSE,
    _ROOM_OUTPOST,
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
    15: {"stage_id": "back_alley_go_east", "hint_family": "go"},
    16: {"stage_id": "market_status", "hint_family": "status"},
    17: {"stage_id": "market_buy", "hint_family": "buy_from"},
    18: {"stage_id": "market_equip_gear"},
    19: {"stage_id": "market_go_east", "hint_family": "go"},
    20: {"stage_id": "warehouse_assess", "hint_family": "assess"},
    21: {"stage_id": "warehouse_attack", "hint_family": "attack"},
    23: {"stage_id": "warehouse_open_safe", "hint_family": "open"},
    24: {"stage_id": "warehouse_take_from_safe", "hint_family": "take_from"},
    26: {"stage_id": "warehouse_go_east", "hint_family": "go"},
    28: {"stage_id": "outpost_disguise", "hint_family": "disguise_as"},
    29: {"stage_id": "outpost_tail", "hint_family": "tail"},
    30: {"stage_id": "outpost_go_east", "hint_family": "go"},
    32: {"stage_id": "rooftop_yell", "hint_family": "yell"},
    33: {"stage_id": "rooftop_remove_disguise", "hint_family": "remove_disguise"},
    35: {"stage_id": "rooftop_go_east", "hint_family": "go"},
    37: {"stage_id": "dock_give_kit", "hint_family": "give"},
    38: {"stage_id": "dock_missions", "hint_family": "missions"},
    39: {"stage_id": "dock_journal", "hint_family": "journal"},
    40: {"stage_id": "dock_claim", "hint_family": "claim"},
    41: {"stage_id": "dock_go_east", "hint_family": "go"},
    43: {"stage_id": "cellar_go_east", "hint_family": "go"},
    45: {"stage_id": "bund_exit_go_west", "hint_family": "go"},
    47: {"stage_id": "checkpoint_go_south", "hint_family": "go"},
    48: {"stage_id": "weather_talk", "hint_family": "talk_to"},
    49: {"stage_id": "weather_go_east", "hint_family": "go"},
    50: {"stage_id": "trust_check", "hint_family": "trust"},
    51: {"stage_id": "trust_go_east", "hint_family": "go"},
    52: {"stage_id": "wanted_check", "hint_family": "wanted"},
    53: {"stage_id": "wanted_go_east", "hint_family": "go"},
    54: {"stage_id": "blackmarket_talk", "hint_family": "talk_to"},
    55: {"stage_id": "blackmarket_go_east", "hint_family": "go"},
    56: {"stage_id": "rumors_check", "hint_family": "rumors"},
    57: {"stage_id": "rumors_go_east", "hint_family": "go"},
    58: {"stage_id": "eavesdrop_talk", "hint_family": "talk_to"},
    59: {"stage_id": "eavesdrop_go_east", "hint_family": "go"},
    60: {"stage_id": "contact_talk", "hint_family": "talk_to"},
    61: {"stage_id": "contact_bond", "hint_family": "bond"},
    62: {"stage_id": "contact_go_east", "hint_family": "go"},
    63: {"stage_id": "alley_look", "hint_family": "look"},
    64: {"stage_id": "alley_go_south", "hint_family": "go"},
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
                   "required_disguise", "required_target", "npc_first"):
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
    if room_id:
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
    action = STAGE_ACTIONS.get(stage)
    if not action:
        return
    if action.get("verb") == "none":
        await _advance_stage(ctx, stage, action)
        return

    if action.get("sub_hints"):
        return

    confirmation = _normalise_tutorial_value(action.get("confirm_on", ""))
    if confirmation:
        if _event_has_succeeded(player, action, TutorialEvent(verb, target, indirect, "")):
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


def _event_has_succeeded(player, action: dict, event: TutorialEvent) -> bool:
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


def blocked_exits_for_room(room_id: str, stage: int) -> dict:
    result: dict = {}
    for blocks in STAGE_BLOCKED_EXITS.values():
        room_blocks = blocks.get(room_id, {})
        for direction, info in room_blocks.items():
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
    payload = action.get("teaching_hint") or action.get("cmd_hint")
    if not payload:
        return
    player = ctx.session.player
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
    action = STAGE_ACTIONS.get(stage)
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

    topics = action.get("topics") or []
    if topics:
        from .npc import humanize_topic_key
        await _send_tutorial_payload(
            ctx,
            "Topics: " + ", ".join(humanize_topic_key(t) for t in topics),
            msg_type=MessageType.TUTORIAL,
        )

    if stage == 18:
        sub_hints = action.get("sub_hints") or {}
        worn_ok = _slot_holds_catalog_item(player, "worn_armour_id", "quilted_jacket")
        equip_ok = _slot_holds_catalog_item(player, "equipped_weapon_id", "wooden_club")
        active_sub = None
        if not worn_ok:
            active_sub = sub_hints.get("market_wear_jacket")
        elif not equip_ok:
            active_sub = sub_hints.get("market_equip_club")
        if active_sub:
            await _send_tutorial_hint(ctx, stage, active_sub, force_immediate=force_immediate)
        return

    await _send_tutorial_hint(ctx, stage, action, force_immediate=force_immediate)


async def record_tutorial_event(ctx, event: TutorialEvent) -> bool:
    player = ctx.session.player
    stage = getattr(player, "tutorial_stage", 0)
    action = STAGE_ACTIONS.get(stage)
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

    if stage == 18:
        sub_hints = action.get("sub_hints") or {}
        matched_sub = None
        for sub_id, sub in sub_hints.items():
            required = _normalise_tutorial_value(sub.get("required_item", ""))
            target_norm = _normalise_tutorial_value(event.target or "")
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
        completed = progress.setdefault("stage_18", set())
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
            families_done = progress.setdefault("stage_18_families", set())
            if family not in families_done:
                uses[family] = uses.get(family, 0) + 1
                families_done.add(family)

        worn_ok = _slot_holds_catalog_item(player, "worn_armour_id", "quilted_jacket")
        equip_ok = _slot_holds_catalog_item(player, "equipped_weapon_id", "wooden_club")
        if worn_ok and equip_ok:
            await _advance_stage(ctx, stage, action)
            return True

        await _emit_stage_entry(ctx)
        return True

    if not _event_has_succeeded(player, action, event):
        return False
    await _advance_stage(ctx, stage, action)
    return True


async def _advance_stage(ctx, stage: int, action: dict) -> None:
    player = ctx.session.player
    await _send_advance_message(ctx, stage, action)
    advance_tutorial_stage(player)
    while True:
        next_stage = getattr(player, "tutorial_stage", 0)
        next_action = STAGE_ACTIONS.get(next_stage)
        if not next_action or next_action.get("verb") != "none":
            break
        await _send_advance_message(ctx, next_stage, next_action)
        advance_tutorial_stage(player)
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
    action = STAGE_ACTIONS.get(stage)
    if not action:
        return False
    room_id = getattr(player, "current_room", "")
    return stage_accepts_event(
        action,
        TutorialEvent(verb=verb, target=target, indirect=indirect, room_id=room_id),
        player,
    )


def get_tutorial_hint(player) -> str:
    stage = getattr(player, "tutorial_stage", 0)
    action = STAGE_ACTIONS.get(stage)
    if not action:
        return ""
    return action.get("cmd_hint", "")


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
        "orientation_old_crane": "orientation_eavesdrop",
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
