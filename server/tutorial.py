import logging
from typing import Any, Dict, List, Optional

from .constants import MessageType
from .formatting import format_tutorial_text
from .world import Room

logger = logging.getLogger(__name__)

_ROOM_TEA_HOUSE = [
    {"room_id": "refugee_entry_tea_house"},
    {
        "verb": "look",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "TALK TO MRS. LIN",
        "msg": "The room is humid with a faint scent of tea emitted from a kettle that never quite stops emitting steam, while a woman behind the counter dries a cup while she watches the entrance with caution. Use LOOK whenever you want to take in where you stand: what is here, who is here, and which way the exits go.\nIf you begin a command and press the Tab key, the game will finish the word for you, so try typing T and then pressing Tab to see it work and use arrow keys to navigate your choices.\n And a disclaimer, if you die in this city you begin again with nothing and will be a stranger to yourself. Only your journal remains, lying at the place you died for whoever you become next to find.",
        "journal_entry": "Death is permanent. When I die, my next character can recover my JOURNAL where I died.",
    },
    {
        "verb": "talk to",
        "target": "mrs. lin",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "TALK TO MRS. LIN",
        "msg": "This is your first command. Type TALK TO MRS. LIN to begin speaking with her. Use TALK TO <NPC NAME> in the future.",
        "npc_msg": "Well, come on in. Don't just stand there! If you want to know something from me, you will need to ASK me ABOUT it. But you do not have to guess every time, just type ASK MRS. LIN ABOUT by itself and I will tell you what possible information on topics I know, the more you get closer to a NPC, the more information you might get from their topics or dialogue.",
    },
    {
        "verb": "ask",
        "from_npc": "tutorial_mrs_lin",
        "indirect_state": "empty",
        "hint_level": "explicit",
        "cmd_hint": "ASK MRS. LIN ABOUT",
        "msg": "The topics Mrs. Lin will discuss appear in her reply automatically. You can now pick one and ask about it. Different NPCs will have different bucket topics depending on your relationship with them. For now, type ASK MRS LIN ABOUT THE CITY",
    },
    {
        "verb": "ask",
        "from_npc": "tutorial_mrs_lin",
        "indirect_state": "present",
        "hint_level": "explicit",
        "cmd_hint": "ASK MRS. LIN ABOUT THE CITY",
        "msg": "",
        "npc_msg": "Before the war, Shanghai called herself the Paris of the East. The Bund sparkled, dance halls stayed open until dawn filled with noise, and fortunes changed hands over cups of tea. Now sandbags line the streets, refugees from the Northern plains of China sleep in temple courtyards and the streets, while the damn Kempeitai can stop a man for the look on his face. Still, I am able to pour hot water over good leaves from better times, and the taste reminds me of better days. And for that I am eternally grateful.",
    },
    {
        "verb": "buy",
        "target": "baozi",
        "from_npc": "tutorial_mrs_lin",
        "confirm_on": "purchase",
        "flag": "tutorial_purchased_baozi",
        "hint_level": "explicit",
        "cmd_hint": "BUY FROM MRS. LIN",
        "msg": "Type BUY FROM MRS. LIN to open her shop. A tray of goods appears for you to choose from.\nUsing BUY FROM <NPC NAME> will open their shop if they are a vendor. Use the arrow keys to navigate the popup and buy yourself a Baozi",
        "npc_msg": "First things first, you must be hungry! Everyone coming in from the river or off the trains into this desolate city wears the same look: tired, frightened, and half-starved or all three. BUY something from me. A baozi is cheap, though not as cheap as it was last month. Prices rise faster than wages these days, and nobody knows what next week's market will bring. Here, take 50 fabi. Spend it wisely, if there is one thing which has stayed the same, it is that Shanghai has a way of emptying your pockets before you notice.",
        "note": "Advances when player purchases baozi from Mrs. Lin.",
    },
    {
        "verb": "inventory",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "Type INVENTORY to keep stock of what you carry.",
        "msg": "Take a look at your INVENTORY. It shows everything you carry such as your belongings, your money, and whatever you're wearing such as a disguise or what you have equipped. You can carry no more than twelve items. When your inventory reads 12/12, your hands will be full, and anything else you find will have to stay where it is until you drop something.",
    },
    {
        "verb": "eat",
        "target": "baozi",
        "alt_target": "baozi",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "TYPE "EAT BAOZI" to eat the Baozi you just bought",
        "msg": "EAT BAOZI while it is still warm in your hand. Hunger wears you down by degrees, while a meal pushes that decline for a while. If you let your hunger bar run out entirely and you will begin to take DOT damage to your healthbar.",
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_mrs_lin",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "msg": "A soldier holds the eastern exit door shut until your tutorial here is finished,  so type GO EAST to the BACK ALLEY .\nYou can also use the MAP command to see a full overview of every room you have visited, grouped by district, with your current location and available exits shown on a grid. MAP does not replace GO; it helps you decide where to go next by showing you the layout of the city. As well for fast travel purposes which is enabled in this playthrough",
        "npc_msg": "Go on now, east into the Back Alley, where you'll see a man called Chen waiting for you. GO EAST to walk there yourself, or click your destination on the MAP and let it carry you the longer way around if you would prefer.",
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
        "npc_msg": "Hush, keep your voice down and keep walking, if you have something to say then TALK TO me, but lower your voice. The people I answer to never ever put their business out in the open, and neither should you if you mean to last. Mrs. Lin has vouched for you, which buys you this one conversation. When the patrols come through, use HIDE and stay low until they pass.",
        "journal_entry": "Comrade Chen is CCP. He warned me about the patrols and told me to keep my head down.",
        "blocked_exits": {"refugee_entry_back_alley": {"east": {"stage": 8, "message": "A locked gate blocks the eastern passage."}, "west": {"stage": 8, "message": "A locked door blocks your return."}}},
    },
    {
        "verb": "hide",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "HIDE",
        "msg": "Patrols work on two rules. First, every district has a patrol interval, measured in minutes, that determines how often a patrol checks that area. High-security districts like Hongkou and the Bund get patrolled more often, while the Back Alleys and the Old City get less attention. Second, patrol routes are not entirely random, a patrol enters a room, checks it, and moves to an adjacent room along the street network. It does not teleport. It walks the same way you do, and you can track its path by listening for the direction of its footsteps. During curfew, between eight in the evening and six in the morning, patrol frequency doubles and the soldiers shoot on sight rather than stopping to ask questions.",
        "npc_msg": "The Kempeitai patrol is upon us, so keep your head down and use HIDE, quickly now. When you are hidden they walk straight past as though you were never here, provided you can remain undetected as per your STEALTH stat. When the street is yours again you UNHIDE and step back out, and remember that cover and foul weather both make the hiding easier. You have thirty seconds before they round the corner.",
    },
    {
        "verb": "search",
        "target": "loose brick",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "SEARCH LOOSE BRICK",
        "msg": "SEARCH looks for hidden objects in a specific place you name. Type SEARCH LOOSE BRICK to examine the brick Chen pointed out.",
        "npc_msg": "They are gone, good, you can breathe again. Do you see that brick, the one darker than its neighbours with the mortar worked loose around it? SEARCH LOOSE BRICK. This city hides things in plain sight, and people like me leave things for people like you in gaps exactly like that one, so in the future, ask people about the room, they may know some things that you dont.",
        "journal_entry": "SEARCH finds hidden items, dead drops, and secret passages. I found a brass key and a note behind a loose brick.",
    },
    {
        "verb": "take",
        "target": "tarnished brass key",
        "alt_target": "refugee_brass_key",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "TAKE A TARNISHED BRASS KEY",
        "msg": "First use SEARCH LOOSE BRICK to reveal what is hidden. Then type TAKE A TARNISHED BRASS KEY to pick it up. Items you find do not enter your inventory on their own.\nThe brick pulls free in your hand, and in the hollow behind it sits a brass key gone dark with age, with a fold of paper tucked beside it. Finding something is not the same as keeping it, so TAKE A TARNISHED BRASS KEY to move it from the wall into your pocket.",
    },
    {
        "verb": "take",
        "target": "crumpled note",
        "alt_target": "refugee_folded_note",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "TAKE A CRUMPLED NOTE",
        "msg": "The key was not alone in there, for a note sits beneath it, folded small and worn soft at the creases from handling. TAKE A CRUMPLED NOTE as well, and learn to empty drops all the way to the bottom, because there is very often a second thing waiting quietly under the first.",
    },
    {
        "verb": "examine",
        "target": "crumpled note",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "EXAMINE A CRUMPLED NOTE",
        "msg": "EXAMINE A CRUMPLED NOTE, and look at it properly. In the hand it is only creased paper, but held close the writing turns cramped and deliberate, and the words do not quite mean what they seem to say. Things in this city almost always carry more than their surface, and to EXAMINE them is how the second meaning shows itself.",
    },
    {
        "verb": "ask",
        "target": "letter",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "ASK COMRADE CHEN ABOUT LETTER",
        "msg": "",
        "npc_msg": "You have read it now, so ASK me ABOUT the letter and I will tell you what lies under the plain words. I could not have explained any of it before you held the thing yourself, because some meanings only settle once a person has seen them with their own eyes. The note itself reads that there is a safe loaded with vital medicine needing transport to Dr Li for operating. GO EAST when you are ready, Old Gao is waiting.",
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_comrade_chen",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "msg": "Chen presses the folded note back into your hand and turns his face away, done with you for now, and the way east lies open. GO EAST.",
        "npc_msg": "The market is east of here, so go and find Old Gao among the stalls. Mind yourself once you are past them, because there is a soldier ahead who does not yet know you exist, and that is an advantage you will want to keep. GO EAST.",
        "blocked_exits": {"refugee_entry_back_alley": {"east": {"stage": 15, "message": "A locked gate blocks the eastern passage."}}},
    },
]

_ROOM_MARKET_STREET = [
    {"room_id": "refugee_entry_market_street"},
    {
        "verb": "status",
        "from_npc": "tutorial_old_gao",
        "hint_level": "explicit",
        "cmd_hint": "STATUS",
        "msg": "The market a blur of noise all rolled into one, prices shouted over one another, a loose chicken chased by children between the stalls, someone haggling hard over almost nothing. Before you find Old Gao, read your STATUS, which lays out your health, your hunger, your stealth, your money, and how each faction perceieves you. All of it shifts from hour to hour due to environmental differences, and knowing where you stand is half of staying alive.",
    },
    {
        "verb": "buy",
        "target": "broken wooden club",
        "alt_target": "tattered leather vest",
        "from_npc": "tutorial_old_gao",
        "confirm_on": "purchase",
        "flag": "tutorial_purchased_gear",
        "require_both": True,
        "hint_level": "explicit",
        "cmd_hint": "BUY FROM OLD GAO",
        "msg": "",
        "npc_msg": "Chen sent you? Then you must be the refugee he was talking about. My name is Old Gao. I run this stall, and I know what people need before they do. If you want to see what I'm selling, use BUY FROM <NPC NAME>. Before you head east, buy both the broken wooden club and the tattered leather vest. Don't be stingy, you can always earn more fabi but you only have one set of ribs.",
        "note": "Advances when player purchases BOTH club AND vest.",
    },
    {
        "verb": "wear",
        "target": "tattered leather vest",
        "alt_target": "broken wooden club",
        "from_npc": "tutorial_old_gao",
        "confirm_on": "equip",
        "flag": "tutorial_equipped_gear",
        "require_both": True,
        "hint_level": "explicit",
        "cmd_hint": "WEAR",
        "msg": "What you have bought does you no good sitting in your bag, so use WEAR to bring up the overlay to wear the vest and do the same for the EQUIP popup for the club to equip it in your hand. Each has its own slot, armour on the body and weapon in your grip.",
        "note": "Tut advances when player equips BOTH vest AND club.",
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_old_gao",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "msg": "Old Gao watches you cinch the vest tight, then turns without another word to his next customer like nothing ever happened, the eastern way now stands open. Type GO EAST or use the MAP and navigate to the WAREHOUSE.",
        "npc_msg": "The warehouse is due east, there is a lone soldier inside it is not expecting a living soul to appear, so keep it that way for as long as you possibly can. GO EAST to the WAREHOUSE.",
        "blocked_exits": {"refugee_entry_market_street": {"east": {"stage": 19, "message": "The eastern path is blocked."}}},
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
        "msg": "The warehouse opens up cold and cavernous around you, and a single soldier stands at the far wall, rifle shouldered, his mind drifting plainly somewhere else entirely. Before you do anything, TYPE ASSESS KEMPEITAI SOLDIER. It shows you his AUTHORITY and the threat he carries,  the number your own will have to match or beat with your COURAGE. Learn that number before you decide anything. Never after.",
        "npc_msg": "Cold as a tomb in this warehouse, and nobody said a word about drafts when they posted me here. Three weeks I've had that transfer request sitting on some captain's desk, and not so much as an answer. At this rate the rifle will rust off my shoulder before headquarters remembers I exist.",
    },
    {
        "verb": "attack",
        "target": "kempeitai soldier",
        "from_npc": "tutorial_kempeitai_soldier",
        "hint_level": "explicit",
        "cmd_hint": "ATTACK KEMPEITAI SOLDIER",
        "msg": "Combat is decided by a single roll: your COURAGE plus the bonus from your EQUIPPED weapon against your target's AUTHORITY. Meet or beat that value and your attack kills instantly. Fall short, and your target strikes back just as decisively as you consume a FLEE charge to escape the encounter. Here, the dead don't get back up.\n\nType ATTACK KEMPEITAI SOLDIER to try it now, and in the future use ATTACK <NPC NAME>, while he still hasn't noticed you. If a fight turns against you, FLEE spends one escape charge to pull you back to your claimed safehouse.\n\nA few things are worth remembering. Melee items kill quietly, but a gunshot can be heard five rooms away via propogation, drawing any nearby Kempeitai patrols to investigate. Kill someone where others witness it and your wanted level rises immediately, NPCS remember faces, and word of mouth travels quickly. Kill in an empty place instead, and only the body remains, disappearing after one game day. Every death also weakens the victim's faction in that district, and surviving members may remember who was responsible and be more cautious.",
        "npc_msg": "Oi! Who's—",
        "journal_entry": "ATTACK measures COURAGE plus weapon against AUTHORITY. FLEE spends one escape charge to return to my safehouse.",
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "msg": "Containers answer to three commands. OPEN gets one unlocked. PUT IN stores something inside it. TAKE FROM lifts something back out. Anything that locks can be locked up again with CLOSE and LOCK commands.",
    },
    {
        "verb": "open",
        "target": "rusted iron safe",
        "from_npc": "tutorial_kempeitai_soldier",
        "hint_level": "explicit",
        "cmd_hint": "OPEN RUSTED IRON SAFE",
        "msg": "The warehouse has gone quiet. Against the far wall, half-hidden behind a stack of crates, sits a rusted iron safe. OPEN RUSTED IRON SAFE. If you're carrying the right key, it will be used automatically.\n\nContainers use a handful of simple commands. OPEN lets you look inside. TAKE FROM removes an item, while PUT IN stores one. If a container can be secured, CLOSE shuts it, and LOCK seals it again with the matching key.\n\nSafehouses have containers of their own for storing valuables. Not every locked box in Shanghai is worth opening, but the ones that need a key usually hold something worth finding.",
    },
    {
        "verb": "take from",
        "target": "rusted Mauser pistol",
        "alt_target": "bloodstained officer coat",
        "source": "safe",
        "from_npc": "tutorial_kempeitai_soldier",
        "confirm_on": "take_from",
        "flag": "tutorial_took_from_safe",
        "require_both": True,
        "hint_level": "explicit",
        "cmd_hint": "TAKE FROM RUSTED IRON SAFE",
        "msg": "The safe swings open to reveal a Mauser pistol, an officer's coat gone stiff with old blood, and a sealed medical package tucked into the corner. TAKE the pistol and the coat. The pistol is your first real weapon, and the coat will let you pass the checkpoint ahead. As you search the safe, you also recover the medical package. Keep hold of it. Dr. Li has been waiting for those supplies.\n\nEquipment doesn't last forever. Every successful attack wears down your weapon's durability, and every blow you take wears down your armour. A weapon reduced to zero durability may jam in the middle of a fight, while armour at zero offers no protection at all. Check the condition of your gear with INVENTORY. Vendors can replace worn equipment, and carrying a spare is often the difference between surviving a fight and dying in one.",
        "journal_entry": "Recovered a medical package for Dr. Li. Weapons and armour lose durability with use. Check their condition with INVENTORY.",
        "note": "Advances when player takes BOTH pistol AND coat.",
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "msg": "Equipment wears down with use. Every successful attack costs weapon durability; every blow taken costs armour durability. At zero, weapons risk jamming and armour stops protecting. Check condition anytime with INVENTORY.",
    },
    {
        "verb": "go",
        "target": "east",
        "from_npc": "tutorial_kempeitai_soldier",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "msg": "You're armed now, wearing the officer's coat with a Mauser at your hip. Fang Jie is waiting beyond the outpost to the east. GO EAST.\n\nIf a fight turns against you, FLEE spends one escape charge to pull you back to your claimed safehouse. You gain an escape charge each time you CLAIM a safehouse, so keeping one in reserve can mean the difference between surviving and starting over from scratch.",
        "blocked_exits": {"refugee_entry_warehouse": {"east": {"stage": 24, "message": "Complete your business here first."}}},
    },
    {
        "verb": "none",
        "hint_level": "silent",
        "msg": "The FLEE command lets you escape a losing fight by spending an escape charge. You earn one charge each time you CLAIM a safehouse. FLEE pulls you instantly to your claimed safehouse.",
    },
]
_ROOM_OUTPOST = [
    {"room_id": "refugee_entry_outpost"},
    {
        "verb": "disguise as",
        "target": "japanese officer",
        "from_npc": "tutorial_fang_jie",
        "hint_level": "explicit",
        "cmd_hint": "DISGUISE AS JAPANESE OFFICER",
        "msg": "Type DISGUISE AS JAPANESE OFFICER to put on the officer's coat. The exact phrasing matters.\n\nThe coat settles onto your shoulders and, for one long breath, you are simply another officer crossing the warehouse. Then the sentry studies your insignia, realizes something is wrong, and heads for the telephone. REMOVE DISGUISE before he reaches it.\n\nDisguises improve your STEALTH and make you harder to identify, but they are never foolproof. When an NPC looks closely, its PERCEPTION is checked against your disguise. If it sees through the disguise, a civilian may ignore it, a guard may stop and question you, while an officer is likely to raise the alarm. The higher your wanted level, the more closely patrols examine you, making disguises easier to uncover.",
        "npc_msg": "The sentry's watching the door, not you. That's your chance. DISGUISE AS JAPANESE OFFICER. Just remember a uniform fools a glance, not an inspection.",
    },
    {
        "verb": "remove",
        "target": "disguise",
        "from_npc": "tutorial_fang_jie",
        "hint_level": "explicit",
        "cmd_hint": "REMOVE DISGUISE",
        "msg": "He has made you, and there is no talking your way back from that, so REMOVE DISGUISE now. The coat that hid you a moment ago is suddenly the most dangerous thing on your body, and you cannot hope to follow a man while you are dressed as the very enemy he intends to report.",
    },
    {
        "verb": "tail",
        "target": "officer",
        "from_npc": "tutorial_fang_jie",
        "hint_level": "explicit",
        "cmd_hint": "TAIL OFFICER",
        "msg": "",
        "npc_msg": "He is making for the stairs, so TAIL him, but hang back and keep to the wall and let the distance do your hiding for you. Follow a man long enough and he will show you his whole route without ever meaning to. You could never have done this in the coat, because a disguise draws every eye, and tailing needs you unseen.",
        "blocked_exits": {"refugee_entry_outpost": {"east": {"stage": 27, "message": "You must follow the officer."}}},
    },
]

_ROOM_ROOFTOP = [
    {"room_id": "refugee_entry_rooftop"},
    {
        "verb": "tail",
        "target": "officer",
        "hint_level": "silent",
        "msg": "The stairs open out onto the roof, where the officer has stopped at the parapet to scan the streets below him. You have followed him this far without being seen, so hold your place and keep it that way a moment longer.",
    },
    {
        "verb": "yell",
        "hint_level": "explicit",
        "cmd_hint": "YELL",
        "msg": "The officer is searching the wrong corner entirely, so YELL and pull his attention off toward somewhere you are not. A shout carries about three rooms out from where you stand, and the people who hear it come looking for its source. Noise is a tool in this city, and the trick of it is aiming it away from yourself.\nSound has an intensity scale that determines how far it travels. A whisper stays in the room where it started. Normal conversation carries one room. A yell reaches three rooms. A gunshot carries five rooms, and an explosion travels even further. Every NPC within range reacts according to their faction: Kempeitai investigate the source of the sound, civilians flee or spread rumours about what they heard, and gangsters move toward the commotion to see if there is profit in it. If you are hidden when the sound reaches a room, the NPCs who enter to investigate will not find you, but they may linger and make it harder to move unseen.",
    },
    {
        "verb": "look",
        "hint_level": "contextual",
        "cmd_hint": "LOOK",
        "msg": "Your shout rolls out across the rooftops and fades, and below you figures begin drifting toward the place it came from. Sound has a reach in this city: a whisper stays in the room, a yell carries three rooms, a gunshot five, and everyone inside that reach decides at once to close in or clear off. LOOK now to see what your noise has set moving down there.",
        "journal_entry": "Sound propagates between rooms. Yelling (3) carries 3 rooms. Gunshots (5) carry further.",
    },
    {
        "verb": "status",
        "hint_level": "explicit",
        "cmd_hint": "STATUS",
        "msg": "The street below is stirred up now, and some of that stirring may well have your name attached to it. Before you climb down into the middle of it, read your STATUS again: your nerve, your health, and whether that shout has cost you any standing. Never step into a moving situation blind to your own state.",
        "journal_entry": "NPCs react to sounds based on faction. Kempeitai investigate. Civilians flee.",
    },
    {
        "verb": "go",
        "target": "east",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "msg": "The roof has done its work and the officer is off chasing your echo, so leave him to it. A stairwell on the eastern side drops down toward the water, where a doctor is waiting for what you carried out of that safe. GO EAST.\nDeath has a cost but not a full stop. When you die, you lose everything you were carrying and wake at your claimed safehouse with nothing but the clothes on your back. Your previous body becomes a death journal in the room where you fell. Your next character can READ that journal by visiting that room, recovering the story of how you died and a record of what you discovered. It is the one thing that survives.",
        "blocked_exits": {"refugee_entry_rooftop": {"east": {"stage": 32, "message": "Complete your objective first."}}},
    },
]

_ROOM_DOCK = [
    {"room_id": "refugee_entry_dock"},
    {
        "verb": "none",
        "hint_level": "silent",
        "msg": "The dock smells of salt and coal smoke.",
    },
    {
        "verb": "give",
        "target": "worn medical kit",
        "from_npc": "tutorial_doctor_li",
        "hint_level": "explicit",
        "cmd_hint": "GIVE WORN MEDICAL KIT TO DOCTOR LI",
        "msg": "Type GIVE WORN MEDICAL KIT TO DOCTOR LI. The order matters: GIVE [item] TO [person].",
        "npc_msg": "Tell me you brought something I can actually use, and then GIVE me the medical kit before you say anything else. The right thing placed in the right hand settles more than a debt, it closes out the very task someone set you. This will keep a man breathing past tonight, and keeping men breathing is the whole of my work now.",
        "journal_entry": "GIVE hands items to NPCs. The right item to the right person completes missions.",
    },
    {
        "verb": "missions",
        "hint_level": "contextual",
        "cmd_hint": "MISSIONS",
        "msg": "",
        "journal_entry": "MISSIONS shows progress. MISSIONS AVAILABLE finds work. MISSIONS ACCEPT takes a job.",
    },
    {
        "verb": "journal",
        "hint_level": "contextual",
        "cmd_hint": "JOURNAL",
        "msg": "Your JOURNAL holds everything you have seen, the talk overheard, the small things found, the deaths witnessed along the way. It is also the one part of you that outlives the rest, so if you fall somewhere, whoever you become next can read this book beside your body and learn exactly how you came to be there.",
    },
    {
        "verb": "claim",
        "hint_level": "explicit",
        "cmd_hint": "CLAIM",
        "msg": "Once you have claimed a safehouse, you can use it to store items between trips. The RETRIEVE command pulls items from your safehouse stash back into your inventory. You can also PUT IN items into containers at your safehouse for long-term storage. This is how you keep your valuables safe when you go out on dangerous work, and how you hold more than your pockets can carry.",
        "journal_entry": "CLAIM makes a safe room my safehouse. CLAIM resets escape charge for FLEE. RETRIEVE recovers stashed items.",
    },
    {
        "verb": "go",
        "target": "east",
        "hint_level": "explicit",
        "cmd_hint": "GO EAST",
        "msg": "A low passage runs east out of the dock and through the cellar toward the Bund, and the doctor has no more to teach you here. GO EAST.",
        "blocked_exits": {"refugee_entry_dock": {"east": {"stage": 37, "message": "The cellar entrance is hidden."}}},
    },
]

_ROOM_ORDER = [
    _ROOM_TEA_HOUSE,
    _ROOM_BACK_ALLEY,
    _ROOM_MARKET_STREET,
    _ROOM_WAREHOUSE,
    _ROOM_OUTPOST,
    _ROOM_ROOFTOP,
    _ROOM_DOCK,
]

_STAGE_DEFS = []
for _block in _ROOM_ORDER:
    _STAGE_DEFS.extend(_block)

STAGE_ACTIONS: Dict[int, dict] = {}
STAGE_TARGETS: Dict[int, str] = {}
STAGE_BLOCKED_EXITS: Dict[int, dict] = {}
ROOM_FOR_STAGE: Dict[int, str] = {}

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
    _action = {"verb": _d["verb"]}
    for _k in ("target", "source", "cmd_hint", "journal_entry",
                   "alt_verb", "alt_target", "alt_source", "reward",
                   "confirm_on", "from_npc", "npc_msg", "indirect_state",
                   "note", "require_both", "flag"):
        if _d.get(_k):
            _action[_k] = _d[_k]
    if _d.get("msg"):
        _action["advance_message"] = _d["msg"]
    if _d.get("response_msg"):
        _action["response_message"] = _d["response_msg"]
    if _d.get("hint_level"):
        _action["hint_level"] = _d["hint_level"]
    STAGE_ACTIONS[_stage_idx] = _action
    if _d.get("target"):
        STAGE_TARGETS[_stage_idx] = _d["target"]
    if "blocked_exits" in _d:
        STAGE_BLOCKED_EXITS[_stage_idx] = _d["blocked_exits"]
    _stage_idx += 1

TUTORIAL_ROOM_IDS: List[str] = [
    "refugee_entry_tea_house",
    "refugee_entry_back_alley",
    "refugee_entry_market_street",
    "refugee_entry_warehouse",
    "refugee_entry_outpost",
    "refugee_entry_rooftop",
    "refugee_entry_dock",
    "refugee_entry_cellar",
    "bund_exit_checkpoint",
    "orientation_hub_01",
    "orientation_hub_02",
    "orientation_hub_03",
    "orientation_hub_04",
    "orientation_hub_05",
    "orientation_hub_06",
    "orientation_hub_07",
    "orientation_hub_08",
    "refugee_entry_dark_alley",
]


def tutorial_set_confirmation(player, stage: int, verb: str) -> None:
    key = f"stage_{stage}"
    confirm: dict = getattr(player, "tutorial_confirmation", {})
    confirmed: list = confirm.setdefault(key, [])
    if verb not in confirmed:
        confirmed.append(verb)


def advance_tutorial_stage(player) -> None:
    """Increment the player's tutorial stage by 1."""
    player.tutorial_stage = getattr(player, "tutorial_stage", 0) + 1


async def advance_tutorial(ctx, verb: str, target: str, indirect: str, raw_verb: str) -> None:
    player = ctx.session.player
    stage = getattr(player, "tutorial_stage", 0)
    action = STAGE_ACTIONS.get(stage)
    if not action:
        return

    if action.get("verb") == "none":
        await _send_advance_message(ctx, stage, action)
        advance_tutorial_stage(player)
        return

    require_both = action.get("require_both", False)
    confirm_on = action.get("confirm_on", "")

    if require_both and confirm_on:
        key = f"stage_{stage}"
        confirm: dict = getattr(player, "tutorial_confirmation", {})
        confirmed: list = confirm.get(key, [])
        expected_verbs: list = []

        if confirm_on == "purchase":
            if action.get("require_both"):
                expected_verbs = ["purchase", "purchase"]  # Two purchases
        elif confirm_on == "equip":
            expected_verbs = ["equip", "wear"]
        elif confirm_on == "take_from":
            expected_verbs = ["take_from", "take_from"]  # Two items from container

        required_count = 2 if action.get("require_both") else 1
        if len(confirmed) >= required_count:
            await _send_advance_message(ctx, stage, action)
            advance_tutorial_stage(player)
        return


    if confirm_on and not require_both:
        key = f"stage_{stage}"
        confirmed = getattr(player, "tutorial_confirmation", {}).get(key, [])
        if confirm_on in confirmed:
            await _send_advance_message(ctx, stage, action)
            advance_tutorial_stage(player)
        return

    matched = _try_stage_match(stage, verb, target, indirect, action)
    if not matched:
        return

    await _send_advance_message(ctx, stage, action)
    advance_tutorial_stage(player)


async def _send_advance_message(ctx, stage: int, action: dict) -> None:
    advance_msg = action.get("advance_message", "")
    if advance_msg:
        await ctx.session.send_display(advance_msg, msg_type=MessageType.TUTORIAL.value)

    npc_msg = action.get("npc_msg", "")
    if npc_msg:
        formatted = format_tutorial_text(npc_msg)
        await ctx.session.send_display(formatted, msg_type=MessageType.TUTORIAL_NPC.value)

    journal_entry = action.get("journal_entry", "")
    if journal_entry:
        pass

    reward = action.get("reward", {})
    if reward:
        fabi = reward.get("money_fabi", 0)
        if fabi:
            player = ctx.session.player
            if hasattr(player, "money"):
                player.money = getattr(player, "money", 0) + fabi


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

    return True


def get_tutorial_hint(player) -> str:
    stage = getattr(player, "tutorial_stage", 0)
    action = STAGE_ACTIONS.get(stage)
    if not action:
        return ""
    return action.get("cmd_hint", "")


def restart_tutorial(player, shared) -> None:
    player.tutorial_stage = 0
    player.in_tutorial = True
    player.tutorial_confirmation = {}
    player.tutorial_read_note = False
    player.tutorial_last_room = ""

    if "tutorial_complete" in player.flags:
        player.flags.remove("tutorial_complete")

    if hasattr(player, "tutorial_instance_id") and player.tutorial_instance_id:
        destroy_tutorial_clones_for_player(player.tutorial_instance_id, shared)

    instance_id = clone_tutorial_rooms_for_player(shared.world, id(player), shared)
    player.tutorial_instance_id = instance_id

    player.current_room = "refugee_entry_tea_house"
    if "refugee_entry_tea_house" not in player.map_revealed:
        player.map_revealed.append("refugee_entry_tea_house")

    logger.info("Tutorial restarted for player %s (instance=%s)", id(player), instance_id)


def get_cloned_room_id(instance_id: str, original_room_id: str, shared) -> str:
    clone_map = shared.tutorial_room_clones.get(instance_id, {})
    return clone_map.get(original_room_id, original_room_id)


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

    shared_state.tutorial_room_clones[instance_id] = clone_map
    logger.info("Cloned %d tutorial rooms for player %s (instance=%s)",
                len(clone_map), player_id, instance_id)
    return instance_id


def destroy_tutorial_clones_for_player(instance_id: str, shared) -> None:
    clone_map = shared.tutorial_room_clones.pop(instance_id, {})
    for cloned_id in clone_map.values():
        shared.cloned_tutorial_rooms.pop(cloned_id, None)
        shared.world.rooms.pop(cloned_id, None)
    count = len(clone_map)
    if count:
        logger.info("Destroyed %d cloned rooms for instance %s", count, instance_id)