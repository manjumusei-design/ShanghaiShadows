# Tutorial walkthrough


## Stage 0

**Player action:** LOOK
**System hint:** LOOK
**Verb:** look
**Room Id:** refugee_entry_tea_house
**Cue:** LOOK shows you the room around you: who is here, what is nearby, and where you can go. Use it whenever you need to get your bearings or check what has changed.
.

## Stage 1
**Player action:** TALK TO MRS. LIN
**System hint:** TALK TO MRS. LIN to speak with her.
**Verb:** talk to
**Room Id:** refugee_entry_tea_house
**Target:** mrs. lin
**From Npc:** tutorial_mrs_lin
**Cue:** Mrs. Lin sets down the tray and looks you over.
**Cue Speech:** Come in. Do not stand in the doorway. Sit where I can see you. You are not from Shanghai, are you?
**Npc Msg:** If you have come this far with only the road behind you, things must be bad where you came from. Sit. Tell me what you need. Food? Work? Or are you looking for something else?

## Stage 2

**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_tea_house

## Stage 3
**Player action:** TYPE ASK MRS. LIN, then use the topic list to choose what to ask about, such as ASK MRS. LIN ABOUT WORK
**System hint:** ASK MRS. LIN ABOUT [TOPIC] lets you ask about something she knows. Press Tab after ABOUT to see available topics.
**Verb:** ask
**Room Id:** refugee_entry_tea_house
**From Npc:** tutorial_mrs_lin
**Npc Msg:** Chen is in the alley behind the tea house. He is a nervous man, but I sent word that you might come, so he should hear you out. If you are going to see him, buy a baozi before you leave. That alley is no place to discover you are hungry.
**Topics:** FOOD, WORK, THE CITY

## Stage 4
**Player action:** BUY FROM MRS. LIN
**System hint:** BUY FROM <NPC NAME> opens a vendor's shop. Not every NPC is a vendor.
**Verb:** buy
**Room Id:** refugee_entry_tea_house
**Target:** baozi
**From Npc:** tutorial_mrs_lin
**Cue:** BUY FROM opens a vendor's shop, where you can see what they sell and choose what to purchase.

## Stage 5
**Player action:** INVENTORY
**System hint:** INVENTORY opens your inventory and shows what you are carrying. Use it whenever you want to check your items.
**Verb:** inventory
**Room Id:** refugee_entry_tea_house
**From Npc:** tutorial_mrs_lin
**Cue:** INVENTORY shows the items you are currently carrying. Open it now and check that your baozi is there.
**Cue Speech:** Before you leave, check that you still have the baozi. Better to notice something is missing here than outside. Space is limited, you can only carry 12 items at a time so choose what to bring with you wisely.

## Stage 6
**Player action:** EAT BAOZI
**System hint:** EAT <ITEM> consumes food you are carrying. Try EAT BAOZI.
**Verb:** eat
**Room Id:** refugee_entry_tea_house
**Target:** baozi
**From Npc:** tutorial_mrs_lin
**Cue:** Hunger falls over time. Food restores hunger, and some foods can also restore morale. If hunger falls too low, it can weaken you and eventually cost you health.
**Cue Speech:** Go on, eat it while it is still warm. Food does you no good sitting in your bag, and you do not want to discover how hungry you are once you are out in the street.

## Stage 7
**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_tea_house
**Target:** east
**From Npc:** tutorial_mrs_lin
**Cue:** A sharp shout carries in from the street. The Japanese soldier at the eastern doorway turns and steps outside, leaving the passage clear.
**Cue Speech:** That is your chance. Chen should be in the alley by now. Go east and find him before the soldier comes back.

## Stage 8
**Player action:** TALK TO COMRADE CHEN
**System hint:** TALK TO COMRADE CHEN
**Verb:** talk to
**Room Id:** refugee_entry_back_alley
**Target:** comrade chen
**From Npc:** tutorial_comrade_chen
**Cue:** Chen glances toward the mouth of the alley and beckons you closer, keeping one eye on the street.
**Cue Speech:** Come closer. Keep your voice down.
**Arrival Text:** The tea-house door closes behind you. A latch drops into place on the other side.
**Npc Msg:** Mrs. Lin sent word about you. She says you can carry a message. I know almost nothing about you, and for once that is useful. The patrols here have not learned your face yet. For one errand, I can make use of that. It does not mean I trust you with everything. Listen carefully. A patrol is due through this alley soon, and I would rather they pass without finding a reason to stop.
**Journal Entry:** Mrs. Lin sent me to Comrade Chen in the alley. He appears to have connections with the Communists and warned me that a patrol would be passing through soon.

## Stage 9
**Player action:** HIDE
**System hint:** HIDE
**Verb:** hide
**Room Id:** refugee_entry_back_alley
**From Npc:** tutorial_comrade_chen
**Cue:** HIDE is deterministic. Room details show the Stealth requirement before you act: real cover requires 25 Stealth, ordinary rooms require 50, and exposed or authority-controlled areas require 75. Meet the requirement and HIDE succeeds. Once successfully hidden, patrols and observers do not overturn that success. This private tutorial has no live patrol, but in the main game patrols move through rooms and can limit how long you can safely remain and interact with people. Read the room before you hide.
**Cue Speech:** Get out of sight before anyone comes through here. Look at the ground around you before choosing where to disappear. Some places give you real cover. Others leave you far more exposed.
**Narration:** The alley remains quiet in this private lesson. You settle into cover. A successful HIDE remains secure.

## Stage 10
**Player action:** SEARCH LOOSE BRICK
**System hint:** SEARCH LOOSE BRICK
**Verb:** search
**Room Id:** refugee_entry_back_alley
**Target:** loose brick
**From Npc:** tutorial_comrade_chen
**Cue:** Hidden objects and passages rarely reveal themselves on their own. SEARCH the right detail and your Perception determines what you notice.
**Cue Speech:** While you were pressed against that wall, did you notice the brick beside your shoulder? Look again. It sits differently from the others, and the mortar around it has been disturbed more than once. Search it carefully and tell me what you find.
**Narration:** You ease the loose brick free. A shallow hollow has been cut into the wall behind it. Inside rests a tarnished brass key and a folded scrap of paper, both wrapped in cloth to keep the damp away.
**Journal Entry:** SEARCH can uncover hidden items, dead drops, and concealed passages. Behind a loose brick in the alley, I found a brass key and a folded note.

## Stage 11
**Player action:** TAKE TARNISHED BRASS KEY
**System hint:** TAKE TARNISHED BRASS KEY
**Verb:** take
**Room Id:** refugee_entry_back_alley
**Target:** tarnished brass key
**From Npc:** tutorial_comrade_chen
**Cue:** TAKE opens a chooser showing what is available to take. Take the tarnished brass key and keep it with you: a matching key is consumed when it opens the lock it fits.
**Cue Speech:** Take the key with you. If someone went to the trouble of hiding it here, there is probably a lock somewhere that matters.
**Narration:** The key is cold in your hand. The folded paper still lies in the hollow.

## Stage 12
**Player action:** TAKE CRUMPLED NOTE
**System hint:** TAKE CRUMPLED NOTE
**Verb:** take
**Room Id:** refugee_entry_back_alley
**Target:** crumpled note
**From Npc:** tutorial_comrade_chen
**Cue Speech:** And take the paper. Fold it up and keep it with you. A message hidden in a wall is only useful until someone else finds it.
**Narration:** The paper is worn soft along the creases, small enough when folded to disappear into your palm.

## Stage 13
**Player action:** EXAMINE CRUMPLED NOTE
**System hint:** EXAMINE CRUMPLED NOTE
**Verb:** examine
**Room Id:** refugee_entry_back_alley
**Target:** crumpled note
**From Npc:** tutorial_comrade_chen
**Cue:** EXAMINE reveals more detail about an item. For readable items such as notes, it can also reveal what they say.
**Cue Speech:** Do not carry a message you have not read. See what it actually says before you ASK ME about it.
**Narration:** The note unfolds into cramped handwriting, the ink gone brown at the edges. It names a Doctor Li and mentions medicine being kept in a warehouse to the east.

## Stage 14
**Player action:** ASK COMRADE CHEN ABOUT NOTE
**System hint:** ASK COMRADE CHEN ABOUT NOTE
**Verb:** ask
**Room Id:** refugee_entry_back_alley
**From Npc:** tutorial_comrade_chen
**Narration:** Chen draws back the bolt. The east gate scrapes open.
**Npc Msg:** Doctor Li runs a clinic past the docks. The medicine is for his patients. You already have his name on that note, so there is no reason to write down anything more. Read what you find, remember what matters, and ask if something is unclear. The less unnecessary information you carry, the less you have to explain if a patrol searches you.

## Stage 15

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_back_alley
**Target:** east
**From Npc:** tutorial_comrade_chen

## Stage 16

**Player action:** STATUS
**System hint:** Use STATUS to get a look at the current state of the world
**Verb:** status
**Room Id:** refugee_entry_market_street
**From Npc:** tutorial_old_gao

Stage 17

Player action: BUY FROM OLD GAO
System hint: BUY FROM OLD GAO
Verb: buy
Room Id: refugee_entry_market_street
Target: wooden_club
From Npc: tutorial_old_gao
Cue: Gao taps the wooden club, then pinches the repaired shoulder of the jacket. The club is a weapon and the jacket is armour. They cost 12 and 18 fabi respectively.
Cue Speech: Chen sent you? Then he should have told you the road east can be rough. Twelve for the club, eighteen for the jacket. Neither is much to look at, but both still do their job. If you mean to keep going, I would take both.

Stage 18

Player action: WEAR QUILTED JACKET
System hint: WEAR QUILTED JACKET
System hint: EQUIP WOODEN CLUB
Verb: wear
Room Id: refugee_entry_market_street
Target: quilted_jacket
From Npc: tutorial_old_gao
Cue Speech: Do not just carry them around. Put the jacket on and keep the club ready. The jacket will not protect you folded under your arm, and the club will not help much buried with the rest of your things.
Narration: Gao releases the brake on the nearest handcart and rolls it clear of the eastern lane.
Npc Msg: The warehouse is east. One soldier inside, unless someone has joined him since Chen last checked. He usually watches the far door more closely than the market entrance. Do not take a turned back for an invitation. Look at what is in front of you before you decide what to do.

## Stage 19

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_market_street
**Target:** east
**From Npc:** tutorial_old_gao

Stage 20

Player action: ASSESS KEMPEITAI SOLDIER
System hint: ASSESS KEMPEITAI SOLDIER
Verb: assess
Room Id: refugee_entry_warehouse
Target: kempeitai soldier
From Npc: tutorial_kempeitai_soldier
Cue: The soldier watches the far door, his back half-turned toward the market entrance. ASSESS shows a target's faction, role, Authority, Courage, and threat rating. Check it before you fight. Those details tell you what kind of opponent you are dealing with.

## Stage 21
**Player action:** ATTACK KEMPEITAI SOLDIER
**System hint:** ATTACK KEMPEITAI SOLDIER
**Verb:** attack
**Room Id:** refugee_entry_warehouse
**Target:** kempeitai soldier
**From Npc:** tutorial_kempeitai_soldier
**Cue:** The soldier turns toward you. His eyes settle on the club in your hand, then on your face. He reaches for the rifle beside him and steps between you and the safe. You have been made. Combat can kill you, and death is permanent. If you die, your journal remains where you fell, and the first finder can claim its knowledge once. Combat resolves in a single exchange: your Courage plus your equipped weapon is measured against the soldier's Authority. Meet or exceed it and you win the fight.
**Cue Speech:** Stop there. Put the club down.
**Journal Entry:** ATTACK measures COURAGE plus my equipped weapon against the target's AUTHORITY. A curfew patrol arrest spends my one stored escape charge to move me through a legal exit; without that charge, I remain in custody until release.

## Stage 22
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_warehouse
**Narration:** The soldier goes down. The warehouse falls quiet.
## Stage 23
**Player action:** OPEN RUSTED IRON SAFE
**System hint:** OPEN RUSTED IRON SAFE
**Verb:** open
**Room Id:** refugee_entry_warehouse
**Target:** rusted iron safe
**Cue:** The way to the rusted iron safe is clear. The brass key you found in the alley opens it. A matching key is consumed when it opens a lock, so use it here.

## Stage 24
**Player action:** TAKE FROM RUSTED IRON SAFE
**System hint:** TAKE FROM RUSTED IRON SAFE
**Verb:** take from
**Room Id:** refugee_entry_warehouse
**Target:** refugee_pistol
**Journal Entry:** Recovered supplies for Dr. Li. Weapons and armour lose durability through use. Check their condition with INVENTORY.
## Stage 25
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_warehouse
**Advance Message:** Weapons and armour wear with use. A broken weapon reduces your Courage, while broken armour no longer protects you. Check INVENTORY regularly to keep track of their condition.
## Stage 26
**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_warehouse
**Target:** east
**Narration:** The eastern door groans open. Beyond it, a narrow passage leads toward the outpost.

## Stage 27
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_warehouse
## Stage 28
**Player action:** DISGUISE AS JAPANESE OFFICER
**System hint:** DISGUISE AS JAPANESE OFFICER
**Verb:** disguise as
**Room Id:** refugee_entry_outpost
**Target:** japanese officer
**From Npc:** tutorial_fang_jie
**Cue:** Fang Jie catches your eye and briefly touches two fingers to her collar.
**Cue Speech:** Before you go any farther, use what you took from the warehouse. A disguise only works if you own the exact disguise item. Watchers test their Perception against it, and every point of Wanted makes them more likely to see through you. If they pierce the disguise, the item is confiscated and they will fight you. Get changed now, while no one is paying enough attention to question it.
## Stage 29
**Player action:** TAIL OFFICER
**System hint:** TAIL OFFICER
**Verb:** tail
**Room Id:** refugee_entry_outpost
**Target:** officer
**From Npc:** tutorial_fang_jie
**Cue:** As the officer turns toward the stairwell, Fang Jie tilts her head after him. TAIL follows an NPC from room to room. The target checks your disguise when the tail begins and again every five minutes. Suspicion lets the tail continue, a challenge ends it but leaves your disguise intact, and exposure ends the tail and confiscates the disguise item.
**Cue Speech:** He is moving. Keep him in sight until you know where he is going. Do not cut across the route or guess where he will turn.
## Stage 30
**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_outpost
**Target:** east
**Narration:** His footsteps climb the stairs ahead of you.
## Stage 31
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_rooftop
**Narration:** The stairs open onto the roof. The officer has stopped at the western parapet, watching the streets below.

## Stage 32
**Player action:** YELL TOWARD THE ALLEY
**System hint:** YELL TOWARD THE ALLEY
**Verb:** yell
**Room Id:** refugee_entry_rooftop
**Cue:** Laundry lifts between you and the parapet, and the western alley disappears beyond the roof edge. Sound travels between rooms: a yell carries about three rooms, while a gunshot carries four. A silencer cancels a gunshot's reach. Noise can draw nearby watchers, and this time that is exactly what you want. Yell toward the alley to draw the officer away from the eastern stairwell.
**Journal Entry:** Sound propagates between rooms. A yell carries about three rooms. A gunshot carries four, while a silencer cancels its reach.

## Stage 33

**Player action:** REMOVE DISGUISE
**System hint:** REMOVE DISGUISE
**Verb:** remove
**Room Id:** refugee_entry_rooftop
**Target:** disguise
**Cue:** The laundry settles around you. For the first time since the outpost, no uniformed eyes are watching.


## Stage 34

**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_rooftop
**Narration:** The eastern stairwell is clear.

## Stage 35

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_rooftop
**Target:** east
**Narration:** The eastern stairs descend through the smell of river water and damp timber.

## Stage 36

**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_dock
**Narration:** Doctor Li looks up from his bag. His eyes settle on the worn medical kit.


## Stage 37
**Player action:** GIVE WORN MEDICAL KIT TO DOCTOR LI
**System hint:** GIVE WORN MEDICAL KIT TO DOCTOR LI
**Verb:** give
**Room Id:** refugee_entry_dock
**Target:** worn_medical_kit
**From Npc:** tutorial_doctor_li
**Cue:** GIVE hands an item to an NPC. Delivering the right item to the right person can complete a mission objective.
**Cue Speech:** You brought it. Good. There is a child upstairs whose fever has not broken since dawn, and his mother has been waiting for me to do something. Give me the kit. I can use what is inside.
**Narration:** Doctor Li takes the kit. He opens the clasp with one thumb, checks the contents, then closes it and nods once.
**Journal Entry:** GIVE hands items to NPCs. Delivering the right item to the right person can complete a mission objective.


## Stage 38

**Player action:** MISSIONS
**System hint:** MISSIONS
**Verb:** missions
**Room Id:** refugee_entry_dock
**From Npc:** tutorial_doctor_li
**Cue Speech:** Now that the kit is here, see what other work you have taken on. There is always more to do than there are people to do it.
**Advance Message:** MISSIONS shows your current work. MISSIONS AVAILABLE shows authored opportunities that are offered through NPC encounters. When an encounter presents a mission, you can Accept, Decline, or choose Not now. Accept commits you to that mission and locks the rival offers in the same dilemma. Decline permanently removes only the offer in front of you. Not now defers that offer until the next day. Objectives can ask you to collect an item, deliver something to someone, talk to a person, or visit a place. You can carry up to five missions at once, and higher trust with a faction unlocks more of its work.
**Journal Entry:** MISSIONS shows your progress. MISSIONS AVAILABLE finds work. During an encounter, Accept commits you to the mission, Decline permanently removes that one offer, and Not now defers it until the next day.


## Stage 39

**Player action:** JOURNAL
**System hint:** JOURNAL
**Verb:** journal
**Room Id:** refugee_entry_dock
**Advance Message:** Your JOURNAL records names, clues, and unfinished business. Death is permanent, but the journal remains where you fell. The first finder claims its knowledge once, and later finders receive nothing. It is the record that can survive when your inventory does not.
**Journal Entry:** Death is permanent. If I fall, my journal stays where I died, and the first finder claims its knowledge once.

## Stage 40
**Player action:** CLAIM
**System hint:** CLAIM
**Verb:** claim
**Room Id:** refugee_entry_dock
**Cue:** This shed can be made yours. CLAIM turns a safe room into your safehouse, and you can have only one safehouse per account. Visiting your claimed safehouse restores your one escape charge. If a curfew patrol arrests you, that charge is spent automatically to move you through a legal exit. Your stash is kept at your safehouse. This claim is practice for the lesson. In the city, gear left behind by a predecessor waits at the account safehouse, where a living successor can recover it with RETRIEVE.

## Stage 41
**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_dock
**Target:** east
**From Npc:** tutorial_doctor_li
**Cue Speech:** The work here is done. The passage east runs beneath the Bund. Mind the steps. The brick stays wet even when the street above is dry.
**Narration:** The eastern passage slopes beneath the Bund, its brickwork slick with river damp.

## Stage 42
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_cellar
**Narration:** A tram bell sounds beyond the brickwork, followed by the low murmur of traffic along the river.
## Stage 43
**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** refugee_entry_cellar
**Target:** east
## Stage 44
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_bund_exit
**Narration:** At the western barrier, a guard closes one passbook and reaches for the next.
## Stage 45
**Player action:** GO WEST
**System hint:** GO WEST
**Verb:** go
**Room Id:** refugee_entry_bund_exit
**Target:** west
**Narration:** You follow the railings west until the checkpoint barrier blocks the road ahead.
## Stage 46
**Player action:** Automatic tutorial transition.
**Verb:** none
**Room Id:** refugee_entry_checkpoint
**Narration:** At the southern side of the barrier, an auxiliary lifts the rope and waves the next group through.

## Stage 47
**Player action:** GO SOUTH
**System hint:** GO SOUTH
**Verb:** go
**Room Id:** refugee_entry_checkpoint
**Target:** south
**From Npc:** tutorial_uncle_liu
**Cue Speech:** Not yet. Stand beside me until that group clears the barrier. The auxiliary is checking bundles as closely as faces. If you are wanted, or carrying contraband, a checkpoint can turn dangerous quickly. Keep your hands where they can see them, answer only what you are asked, and move when I move.
**Narration:** The rope drops behind you. The southern lane climbs between shuttered offices toward a roof crowded with instruments.

## Stage 48
**Player action:** TALK TO METEOROLOGIST ZHANG
**System hint:** TALK TO METEOROLOGIST ZHANG
**Verb:** talk to
**Room Id:** orientation_weather
**Target:** meteorologist zhang
**From Npc:** orientation_meteorologist_zhang
**Cue:** Zhang finishes a line in the ledger, sets down the chalk, and looks toward you.
**Cue Speech:** The pressure has been falling since dawn. Rain should reach this district before noon. Pay attention to the weather when you make your plans. Fog makes it easier to stay hidden, but harder to notice what is around you. Rain muffles sound, while a storm carries sound farther. Winter makes hunger drain faster. Look at the sky before you plan to spend a night outside.
**Narration:** Zhang picks up the chalk again. Beyond the instrument tables, the eastern door stands clear.

## Stage 49

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_weather
**Target:** east
**Narration:** You pass between the instrument tables and through the eastern door.

## Stage 50
**Player action:** TRUST
**System hint:** TRUST
**Verb:** trust
**Room Id:** orientation_trust
**From Npc:** orientation_elder_qian
**Cue:** TRUST shows how each faction currently regards you. Trust runs from 0 to 100. Helpful acts raise it, hostile acts lower it, and neglected relationships decay slowly. Higher trust can improve prices, dialogue, and access to faction work.
**Cue Speech:** Mrs. Lin's word helped you with Chen. Somewhere else, being known to Chen might work against you. Do not assume every faction sees you the same way, or that an old relationship still stands where you left it. Check where you stand before you rely on it.
**Narration:** Beyond the eastern door, a narrow corridor is lined with official notices and photographs.

## Stage 51

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_trust
**Target:** east
**Narration:** You pass through the eastern door and enter the notice-lined corridor.

## Stage 52
**Player action:** WANTED
**System hint:** WANTED
**Verb:** wanted
**Room Id:** orientation_wanted
**From Npc:** orientation_inspector_park
**Cue:** Before entering the market, check whether the police are looking for you. WANTED shows your Wanted level from 0 to 3. It rises when you are caught breaking the law and falls after days without further trouble. Each level makes arrest more likely and disguises easier to pierce, and at level 2 ordinary vendors refuse to serve you.
**Cue Speech:** Before you walk into that market, know how much attention you are drawing. The police do not need your name to remember you. A coat, a voice, the direction you ran, the same description passed between two posts can be enough. If people in uniform are beginning to look twice when you pass, it may be time to keep a lower profile.
**Narration:** Beyond the eastern door, the official notices thin out and the corridor narrows toward a shuttered alley.

## Stage 53

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_wanted
**Target:** east
**Narration:** You leave the notice-covered walls behind and pass into the shuttered alley.

## Stage 54
**Player action:** TALK TO OLD MOTHER JIN
**System hint:** TALK TO OLD MOTHER JIN
**Verb:** talk to
**Room Id:** orientation_blackmarket
**Target:** old mother jin
**From Npc:** orientation_mother_jin
**Cue:** Old Mother Jin pauses over a tray of wrapped parcels and looks up as you enter.
**Narration:** Jin grips the handcart by its handles and draws it closer to the wall, clearing the eastern passage.
**Npc Msg:** The scribe is beyond the next partition. Wen. He hears more than he says, which is why people keep finding reasons to visit him. The patrols call this lane the black market. Customers who earn enough trust can reach the Back Room, but anything bought there is contraband, and checkpoints take an interest in that sort of thing. When you see Wen, let him finish what he is doing before you start asking questions. He remembers who is impatient.

## Stage 55
**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_blackmarket
**Target:** east
**Narration:** You pass the stacked crates and follow the smell of ink through the eastern partition.

## Stage 56
**Player action:** RUMORS
**System hint:** RUMORS
**Verb:** rumors
**Room Id:** orientation_rumors
**From Npc:** orientation_scribe_wen
**Cue:** Copied notices lie in neat stacks across Wen's desk. A second pile of loose slips waits beside his brush. RUMORS opens your Rumours panel in two sections: Known Rumours you have gathered and Overheard Exchanges reaching you right now. Rumours can also surface through conversation, and asking people about what you hear may reveal more. As a rumour spreads, factions may alter the version that reaches you.
**Cue Speech:** Those slips beside the brush are today's talk. Some describe the same event differently. Look at who passed each version along before you decide which one you believe.
**Narration:** Wen turns a page and draws the folding screen closer to the wall. Beyond it, a corridor of closed doors leads toward the listening post.

## Stage 57

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_rumors
**Target:** east
**Narration:** You pass the row of closed doors and follow the corridor to the listening post.

## Stage 58
**Player action:** TALK TO OLD CRANE
**System hint:** TALK TO OLD CRANE
**Verb:** talk to
**Room Id:** orientation_eavesdrop
**Target:** old crane
**From Npc:** orientation_old_crane
**Cue:** Old Crane lowers one hand from the listening pipe and studies you across the narrow room.
**Narration:** The exchanges carried through this room reach your Rumours panel as they are heard.
**Npc Msg:** Keep your voice down. That brass pipe carries talk from the rooms below better than the open window carries anything from the street. Sit here long enough and you will hear arguments, bargains, names people should know better than to say aloud, and every so often something worth remembering. Drunk men exaggerate. Frightened men leave things out. Compare what you hear before you decide what to repeat.
**Advance Message:** Old Crane reaches past the worn chair and lifts the wooden latch from the eastern door. The passage beyond leads toward the Resistance Contact Point.

## Stage 59

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_eavesdrop
**Target:** east
**Narration:** You leave the listening pipe behind and pass through the eastern door.

## Stage 60
**Player action:** TALK TO SISTER ZHAO
**System hint:** TALK TO SISTER ZHAO
**Verb:** talk to
**Room Id:** orientation_contact
**Target:** sister zhao
**From Npc:** orientation_sister_zhao
**Cue:** Sister Zhao turns toward you as you enter and waits for you to speak.
**Narration:** Zhao sets down her cup, crosses to the eastern door and draws back the wooden bolt.
**Npc Msg:** The passage east is clear for now. It was not clear an hour ago, and it may not be clear later. Keep moving until you reach the river road. Once you are out there, look before you step into the open. No one here can tell you what is waiting around the next corner.

## Stage 61
**Player action:** BOND SISTER ZHAO
**System hint:** BOND SISTER ZHAO
**Verb:** bond
**Room Id:** orientation_contact
**Target:** sister zhao
**From Npc:** orientation_sister_zhao
**Cue:** Zhao glances at the food you carry and waits. BOND shares a meal with an NPC to build friendship and indebtedness. Friendship can keep doors open after the work is done, and the person you share with will remember the kindness.
**Cue Speech:** We share what we have in this house. Sit with me and eat before you go.
**Narration:** You share the food with Sister Zhao. She nods once, and the eastern door stands ready.
**Journal Entry:** BOND shares food with an NPC to build friendship and indebtedness. Sister Zhao will remember the shared meal.

## Stage 62

**Player action:** GO EAST
**System hint:** GO EAST
**Verb:** go
**Room Id:** orientation_contact
**Target:** east
**Narration:** You pass through the eastern door and follow the narrow passage toward the river road.

## Stage 63

**Player action:** LOOK
**System hint:** LOOK
**Verb:** look
**Room Id:** orientation_alley
**Advance Message:** Beyond the southern mouth, the river road is open.

## Stage 64

**Player action:** GO SOUTH
**System hint:** GO SOUTH
**Verb:** go
**Room Id:** orientation_alley
**Target:** south
**Narration:** You leave the damp passage and step onto the broad road above the river.
