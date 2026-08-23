# Shanghai Shadows

> A multiplayer text-based storytelling game set in Japanese-occupied Shanghai that I am developing as a passion project to be showcased to teenagers in Shanghai for them to learn about historical events that happened during the Japanese occupation.

<!-- TODO: Capture hero image: the Tea House tutorial opening at night, Mrs. Lin's first lines visible, terminal colours on -->

**Play Shanghai Shadows:** <!-- TODO: Add playable demo URL -->

Shanghai Shadows is a MUD you play in a browser that is being hosted on Hackclubs DNS provider and NEST VPS. In this MUD, you are not a soldier, a spy, or a chosen one. You are one ordinary resident of an occupied city, trying to keep your stomach full, staying alive, and your name out of patrol reports between November 1937 and the liberation the world is counting down toward. The city runs on a shared clock other players live in the same Shanghai, hear the same rumours, and explore the lives of ordinary people living under the Japanese occupation of the time.

## Quick Start

```bash
git clone <repository-url>
cd SSL
python -m pip install -r requirements.txt
python main.py
```

Open `http://127.0.0.1:8080` in a browser and create an account. Python 3.11+ required. On Windows, `start.bat` does the same thing and is the way I would reccomend you to run it.

## What is Shanghai Shadows?

In late 1937, Japanese forces took Shanghai after the northeast expedition where they invaded Manchuria earlier in 1931 by staging the Marco Polo bridge incident which led to an invasion from the northeastern China all the way down south and taking Beijing in the process. For eight years of the occupation of Shanghai from 1937 to 1945, most people who lived through the occupation were neither collaborators nor heroes. They were ordinary 老百姓 or the general populance who worked, queued for rice, traded on the black market, spread gossip, kept their heads down after curfew, and occasionally made small, dangerous choices about whom to help. That is the part of history this game is about. The Chinese term laobaixing (老百姓), "ordinary hundred surnames", is the highlight of the game which I chose, since it was really easy to make a spy thriller game or a game where you play as the main character and shoot the bad guys dead but for a learning experience it would be much better to take a look at Shanghai through the lens of an ordinary person and the lives of ordinary or controversial figures that you may come across and how one would just them.

Mechanically, the MUD fundamentally works like this:

- The world is shared and persistent. Every player lives under one clock, one weather system, one rumour mill, one set of faction fortunes, so it would support maybe 30 people with the current VPS.
- Death is permanent. When your character dies, the character stays dead, and the account's next character starts from a safehouse with whatever stash the predecessor left behind and must collect the journal which serves as a form of progression of how many stories or encouters you have come across.
- The campaign has an endpoint. On Day 180, the occupation ends one way or another, decided by which factions players helped. The world resets, but some things carry over. At the moment I can only have 180 days due to the complex length to somehow put 1937 to 1945 in a server playthrough which would take too long (at least for now).
- Violence exists, and it is usually a mistake due to how embedded the Kempeitai (japanese secret police) and informants were in Shanghai during that period. More on that below.

## Why I made it

Around March or April 2026, during Hack Club's Flavortown hackathon, I came across [ForlornMUD](https://github.com/Snxhit/ForlornMUD) which is a fairly traditional RPG MUD where you kill mobs and follow along a storyline and was a pretty highly rated project. What stuck with me was the realisation that a text world could be a complete game, no engine, with almost no assets, just prose and rules. Their project was written in godot and I decided to challenge myself by coding it in python and I am pretty happy with the output so far. I did a tiny bit of analysis on it and concluded that the gameplay loop was just explore rooms -> find enemies/items -> fight -> loot -> gain XP -> improve stats/equipment -> interact with merchants/players -> continue exploring which is pretty straightforwards.

My first idea was simple and fundamentally just to build a historical simulator as a MUD. Pick a period where survival itself was dramatic, so the simulation would generate stories without me having to script them. I am a sucker for history lessons, especially the Asian Theatre of WW2 where my grandparents and their parents grew up in occupied areas or were conscripted in the army. My grandparents and their parents would often tell me of the hunger, curfews, informers, ration cards, and faction politics that existed during their youth/adulthood and listening to those stories growing up seemed like a dream away as in the 21st century we live in a relatively peaceful timeline.

Enough about sentimentals! Lets get into the nitty gritty. Traditional MUDs answer the question "what does the player do?" with "kill mobs and take their stuff, then use stuff to kill bigger mobs". I did not want that answer. I wanted the player's relationship with the world to look like a civilian's relationship with an occupying army, mostly avoidance, sometimes negotiation, rarely violence, and violence always being costly. Answering that question properly took the whole project. The rest of this README is, in large part, a record of how the answer changed over time.

## What you can do in the MUD

- Live under a working occupation economy where three currencies will also play a factor in how you manage your money (japanese military yuan, silver and fabi), inflation that gets worse every week of the campaign, seasonal food shortages, and a black market that will still serve you when legitimate vendors shut their stalls or run away or dissapear for whatever reason.
- Build trust across seven factions, from the Kempeitai to the Green Gang, where every conversation helps one standing and costs another.
- Hear and spread rumours that distort as they travel, and read them each morning in a purchasable newspaper with an AI endpoint that summarizes all of the rumours fed from the game into hackclubs api and returns a newspaper.
- Get around a city that enforces its own rules, where a 20:00 to 06:00 historic curfew, patrols with proximity warnings, checkpoints, and restricted districts.
- Disappear: hide, wear disguises, tail NPCS , pick pockets, plant evidence, and manage a wanted level from 0 to 3.
- Learn all of it through a staged tutorial taught by characters, using the same mechanics the rest of the game uses because I know the reviewer reading this has enough time to only play through the tutorial and the tutorial is what houses the demonstration of the game mechanics so to speak.


### April 2026: hello world

The first commit I have ever done added a `main.py` containing the text `hello world`. Within four days there was a walkable two-room world: The Bund at dawn and Nanjing Road, linked east-west by a  simple YAML file, plus a command parser with verb synonyms and an HTTP server speaking WebSocket to a bare HTML terminal page. Just a heads up I also have a journal on macondo but I would prefer if I spoke about it here.

The first items set the tone better than I realised at the time which was a ration card, a brass key, a photograph, and a newspaper. Not a sword. A few days later came the first NPC, Liu Wei, with dialogue and a daily schedule, trust rules as data, a curfew warning event, a disguises file, and a stealth system that wasnt very in detail with edge cases.

I carried a lot of assumptions over from conventional MUD structure such as rooms, exits, verbs, NPCs with schedules. Those turned out to be the easy part. Nothing in that first week told me what the player would spend their time doing.

### May 2026: discovering the real problem

May was the month the game grew a reason to play it.

Hunger, health, and morale arrived together in late-ish May. Items gained food values. Chinese localization arrived first, then English, because mandarin is my mother tongue but for the sake of review, english would be the way to go.

Two smaller moments from the month are worth recording:

- The parser knew the word `listen`, because MUDs know that word. Later I removed it entirely, replaced by something more honest for this setting, you do not actively eavesdrop, you overhear things when you stand near people talking. More on that in the mechanics section.

Mid-month also brought the first attempt at emergent narrative where I took my hand to write storylets, which short conditional vignettes that trigger based on where you are and what npcs are around. This system would be torn out and rebuilt before it stabilised. And on May 17, an AI client appeared, pointed at Hack Club's AI proxy, used to vary generated prose. It powers the newspaper today, with a deterministic fallback when the API key is absent. IT DOES NOT WRITE CONTENT.

### June 2026: consequences, and company

June built the machinery that turns a single-player toy into a world: bcrypt-backed accounts, a session manager for multiple simultaneous players, world state serialization, a tick loop driving NPC movement, saves, journals, endings etc.

Then came the burst. In roughly 2 weeks or so, the game gained combat resolution, missions, pickpocketing, equipment, milestones, suspicion with decay and investigation behaviour, a market tracker with food restocking, fabi inflation, behaviour trees with blackboards for every NPC, A* pathfinding, sound propagation through the room graph, wanted levels, last words on death, and NPC respawn logic.

The first tutorial also appeared in June, implemented as storylets. It was thin and extremely verbose. It told you commands existed rather than teaching them. It survived until August as I didnt want it to be like a multiple choice question, I wanted it to feel real as if you did not have any choices yourself but could see what choices npcs made. So a huge problem that I also faced was "how could I quantify npc to npc interactions to the player".

### July 2026: a real client, and deleting the memorial

In July I prototyped a Vue prototype landed and then a complete frontend with a theme, canvas map, audio hooks, state management. Until then the client had been one HTML page with a scrolling terminal div. The frontend work consumed much of late July, including a long fix batch for map panning, login validation, layout, and compass directions (rip compass direction).


One day in late July, I  dismantled the following piece by piece: the memorial command, the state field, the death write, the NPC-kill write, the login intro, the archive functions. The same series cut the campaign length from 2,835 days to 180 as it was too hard to keep track of any problems that happened with such a long running game, not to mention the testing as well. 

Late July also produced a new NPC function where NPCs who individually accumulate fear and social risk toward you, remember what they saw, and change how they behave around you. Anyone who has played Middle-earth: Shadow of Mordor knows the feeling of a world whose enemies remember you personally; I wanted that same sensation pointed in the opposite direction, civilians accumulating fear rather than orcs accumulating vengeance, so a shopkeeper you robbed in June still flinches in August.

### August 2026: teaching the city

In August I was being a bit lazy and was only committing an hour a day for the streak until the 15th where I sped things up to finish the MVP of the game. The tutorial rewrite deserves its own paragraph because it changed what kind of game this is. The June version listed commands. The current version puts you in a cloned copy of eighteen rooms with a woman named Mrs. Lin, who teaches you to search loose bricks, buy breakfast, wear a disguise, follow someone without being caught, and yell to draw a guard off his post. Crucially, nothing is faked as the tutorial runs the same sound propagation, the same tail choreography, the same rumour panel as the live world, just in an isolated private instance. When a stage claimed to demonstrate something the production code could not actually do, the fix was to repair the production mechanic, not to fake the demo which is something I stand by since I am also directly solving 2 birds with one stone.

Mid-August brought the curfew arrest system, deliberately non-lethal: get caught outside once and you are chased out of the street; get caught again and you spend a day in custody while everything on you is confiscated. Arrest never kills, because the design brief says authority in this city grinds people down rather than executing them on the spot. Then came a forty-commit stretch adding NPC memory and relationships, testimony documents, strict YAML validation, tab completion driven by the server, and a hint scheduler that waits ten seconds before offering help, on the theory that a player who figures it out themselves learns it permanently.



## How the game works

This section describes the game as it exists today

### Living in the city

You have health, hunger, and morale. Hunger drains hour by hour, faster in winter, through tiers from FULL down to STARVING and FAMISHED. Being famished is not just uncomfortable, every stealth check you make suffers for it, because a starving person moves and looks like a starving person. Morale sits under everything, low morale makes you worse in a fight, worse at hiding, and raises the prices vendors charge you.

Money comes in three flavours. Fabi is the paper currency, and it inflates as the campaign progresses, reaching roughly two and a half times its starting purchasing power by Day 180. Silver yuan hold value at a fixed exchange. Military yen come from the occupier, usually off a corpse and inflate the quickest. Prices stack regional differences, faction attitude, daily market conditions, inflation, season, your personal trust tier, and even your morale, so the same bowl of noodles costs different things on different days in different neighbourhoods. Winter multiplies food prices and slows restocking. When ordinary shops will not sell to you, the black market always will, at a markup, if you can carry contraband past the random checkpoints.

### Talking to people

Every NPC belongs to a faction, and you hold separate trust with each faction-role pair, starting neutral at 50. Helping the resistance earns CCP goodwill and loses Kempeitai goodwill, and the ledger is asymmetric enough that you cannot please everyone and must pick a side. At connected status (70+), factions grant concrete perks such as extra safehouse rooms for CCP, free weapon repairs for the KMT , checkpoint passage for the Kempeitai , faster clearing of your criminal record for the Green Gang.

Conversations are bucketed by mood and remapped by memory. An NPC who remembers you fondly greets you from their friendly line bucket yaml, an npc who watched you kill someone speaks to you from their afraid or hostile ones, and may simply avoid the room from then on. ASK reveals topics, room knowledge, consequences unfolding nearby, and lets you trace where a rumour came from. BOND builds friendship, most reliably by sharing food, though sharing Japanese food with the wrong person costs you.

Rumours are the game's circulatory system. Overheard exchanges arrive in a panel as you stand near conversing NPCs. Behind the panel, every rumour is an immutable record that mutates a little with each hop between tellers such as name swapping, details exaggeration, inverted meanings , until after five hops the text is garbled. Different factions retell the same event with their own spin. Your crimes enter this web automatically, and a high wanted level publishes its own rumours.

### The hard part: how do you quantify NPC-to-NPC interaction?

I posed this problem to myself back in June and it took until August to answer properly. If the city is supposed to feel alive, NPCs cannot just wait around for the player, they need to talk to each other. But the moment two NPCs have a conversation, three ugly questions appear, what did it actually change, who is allowed to know about it, and how do you show any of that without turning every street into a theatre performance for the player and overloading them with information?

The answer settled into three layers with strict rules about which is which:

- **Ambient** interactions are fully autonomous two-turn exchanges between NPCs in a room. Players standing nearby overhear them through the panel where nobody can interrupt, prompt, or steer them. They exist so the world talks when you are not the subject. 
- **Persistent** interactions leave bounded aftermath, a shuttered stall after a witnessed shakedown, cautious dialogue in that room, price pressure. They expire and are deduplicated, capped per district, and never directly move global endings.
- **Actionable** interactions are a small high-stakes subset that can surface later as an ASK lead or storylet, and only if every precondition still holds, actors alive and present, trust valid, timing windows open, cooldowns elapsed.

The second hard lesson was that overhearing should be passive. The original parser knew the word LISTEN because MUDs know that word, and I removed/reshaped it deliberately. In a real life setting you do not decide to eavesdrop standing in a room while people talk and thats what I aimed to achieve with shoving NPC chatter and interaction to be quantifiable to the player. That single removal made the whole system honest, because information now has geography and requires the player to be present, hear things, or to leave/not be in the area and miss them.

The third lesson was numbers. Fear of the player is not from being a direct victim most of the time since the combat system was one shot one kill, it accumulates from specific events such as  witnessing an attack adds 15, witnessing a kill adds 30, a damaging rumour within gossip range adds 5, and personality scales it, brave characters discount fear by half while cowardly ones amplify it past their own judgment. Every interaction category carries cooldowns, caps, and expiry so two NPCs cannot loop the same quarrel forever and one dramatic afternoon cannot permanently define a district.

The tutorial stress tests all of this in some areas. The rumours lesson needs a guaranteed exchange between Wen and his apprentice, but tutorial instances block normal world simulation, so the demonstration runs the exact production social pipeline once, pinned to that specific pair, with a durable fired-record making reruns impossible. When the demo claimed something the production code could not do, I fixed the production code rather than faking the demo because yeah.

### Moving through occupied Shanghai

The map spans eight historical zones and about ninety rooms, from the Bund to Hongkou, connected by streets you walk room by room. Weather changes what sound carries and how well you hide, seasons change prices, hunger, and patrol density. While this is not historically accurate, I assigned one political "entity" to govern areas of the map, for example ...

From 20:00 to 06:00 the streets belong to patrols. Staying out is possible and sometimes necessary, and the game warns you via a proximity indicator counts patrols down from three rooms away. If contact happens, there is one arrest resolution per night. The first catch of the night forces you out a side street. The second puts you in custody for a full in-game day, and everything you carried, including what you were wearing, is confiscated. Getting caught carrying contraband makes it worse, wearing the right disguise halves the odds.

Your wanted level w hich spans from 0 to 3, follows you everywhere. At 2 and above, legitimate vendors refuse to serve you and patrols double. Each level adds to how closely people examine your disguise and to your odds of a bad night under curfew. Levels decay only through days without crime, faster if you stay near a safe room.

<!-- TODO: Capture GIF: walking after curfew as the patrol proximity warning counts down from three rooms -->

### Staying unnoticed

Hiding is a skill roll against the room where indoor spots and authored hiding places help, alert observers, hunger and low morale will make it easier to get alerted. While hidden, observers can still passively spot you. Disguises change what people think you are in terms of perception and they are good but not perfect,  NPCs run perception checks against your disguise bonus, escalating through suspicion, challenge, and exposure stages, and a high wanted level subtracts directly from your protection. for example ...
 
Tailing is contested roll by roll as you close distance, and STOP TAIL breaks it off before you are noticed. Picking pockets gets you the benefit depending the victim, and getting caught costs suspicion, wanted level, and the victim's permanent memory of your face. Planting evidence on someone frames them, if they get caught with your planted item.

### When things go wrong

Combat exists, and here the design departs hardest from MUD tradition and ForlornMUD.

An attack is a one stage movement where you compare your effective courage stat against the target's authority. Win it, and you kill in one shot. Lose it, and you take a counter-blow of up to 25 damage, quite possibly disarmed, with the full matha and feedback shown to you afterward via the terminal. Weapons have durability,  firearms jam more often as they degrade and misfire catastrophically when worn out. 

Sound makes violence loud. Melee is silent. A gunshot carries four rooms, a shout carries three surrounding nearest rooms , and night extends both, storms double the reach. Silenced shots are truly silent when you have a silencer mod equipped on your weapon, and fired from hiding they suppress witnesses entirely, which is the one reliable way to kill quietly and exactly as morally compromised as it sounds. Witnesses react by their personalities via the BT (behavioural tree) to flee or scream or fight, the scene stays marked for two days, and word reaches the wider web within hours. Speaking of BT, I actually got this idea from HALO where you can make NPCs react a certain way depending on which branches it goes down to simulate descision making. 

Killing costs trust along faction lines, raises your wanted level, seeds rumours, and permanently removes named characters from the world which also removes oppurtunities to communicate them and to learn about their experiences. Their corpses decay within a day in the open with loot around on the floor to take. The rewards are pretty modest with a little loot. This matched my vision where fighting is made available and usually never efficient, which matches the historical reality the game is built around.


<!-- TODO: Capture GIF: a failed ATTACK showing the courage-versus-authority breakdown line, followed by the counter-damage narration -->

### A city that remembers

The world autosaves every five minutes, and clean shutdowns save again. Newspapers print daily and cost 3 fabi and contain 3 sections, teahouse talk, notable incidents that includes named deaths, lane whispers. Missions, sixty of them across the factions, expire if ignored and some lock you into dilemmas where taking one side closes another. Storylets, over a hundred of them, surface matched to your location, condition, and history. Ambient events fill the corners with about seventy-six of them.

On Day 180 the occupation ends. Which liberation you see depends on the influence players collectively built which is an uprising, a restoration, a joint effort, or simply the war moving on. Everyone sees the ending, the world resets, a new timeline begins in November 1937. Death journals persist across cycles, so a future character can find a journal left by someone playing months earlier.

<!-- TODO: Capture screenshot: a purchased newspaper showing Teahouse Talk and Lane Whispers sections -->

## Designing a MUD where combat isn't the point

Most of the systems above exist to answer one question which is that if killing things is not the core gameplay loop, what is? The answer the game settled on is *managing information*. What people know about you, what you know about them, and what the city believes are the true resources. Trust, rumours, memory, testimony, disguise, and stealth are all information systems.

Violence fits into that framework as an information catastrophe. Every fight creates witnesses, witnesses create rumours, rumours create suspicion, suspicion creates patrols and closed doors. The systems do not forbid fighting but they sure do make it costly.

Does it fully work? Not yet, and it is worth being specific. The deterrent against killing is currently entirely external, trust loss, wanted levels, witness chains. The original intent included internal cost as well, guilt expressed through the morale system, and I never really  was never built that piece yet. Killing a stranger in an alley where nobody sees remains feels really cheap an d unrealistic, and only the probabilistic risk of unseen witnesses carries the weight. Whether the game needs that internal cost, or whether external consequence plus roleplay pressure is enough, is the weakest link in the design in my opinion.

## How it works under the hood

A few decisions are worth explaining properly, because each one was borrowed from somewhere games already solved it, then bent to fit a city where nobody is shooting at anyone most of the time.

### Behaviour trees with blackboards - from Halo

This is my single biggest biggest biggest loan for the project. From Halo 2 onward they built enemy AI out of behaviour trees instead of giant state machines, and Gears of War later made the technique famous. The idea is actually pretty primative,  a selector node tries child options in priority order until one succeeds, a sequence commits to a run of steps, and a blackboard holds what this particular character currently knows about the world.

Every one of the 101 NPCs in Shanghai Shadows runs a tree like this. There are five authored archetypes, kempeitai_patrol, civilian_vendor, underground_operative, green_gang_thug, and faction_leader, built from Sequence, Selector, Parallel, Inverter, Succeeder, Cooldown, and RepeatUntilFail nodes, and each NPC gets its own blackboard holding things like the last sound it heard, whether danger is nearby, and whether it has noticed the player acting suspiciously.

Why go to all this trouble in a text game? Because finite state machines/holders fall apart and is not something I would like in this revolving game. A patrolling guard must simultaneously walk his route, hear a shout, grow suspicious, leave his post to investigate, and eventually give up and return, and any of those can be interrupted mid-step by something louder. Trees let a higher-priority branch take over without the character forgetting what it was doing, and a cooldwon node stops him re-investigating the same empty alley forever. The tutorial even teaches this pipeline, where for example if you YELL, a real sound event propagates, the officer's tree really perceives it, and he really walks off his anchor toward the noise.

### Sound as a physical object, after Thief: The Dark Project

Thief: The Dark Project treated noise as something with weight and travel, and I leaned on the same idea. Sound in ShanghaiShadows propagates through the room graph breadth first where a gunshot reaches four rooms, a shout three, footsteps one, and intensity roughly halves per room it crosses. Night extends every range by a room, storms double the reach, fog and rain muffle it. Melee is completely silent (albeit with local feedback noise), and a silenced shot fired from hiding suppresses witnesses entirely, which makes the quietest murder also the safest one and exactly as morally compromised as it sounds.

In a game where combat is supposed to be rare, this system is effectively the tax code on violence. You rarely see the mechanic, but it decides whether your fight stays your business.

### Disguises that erode under attention, inspired from Hitman

Hitman's costume system taught the industry that a disguise should not be a binary cloak. Mine works in a similar fashion where NPCs run perception checks against your disguise bonus, and the results escalate through authored stages, suspicion at threshold 25, an active challenge at 50, full exposure at 75. Your wanted level subtracts directly from your protection, so the same paper uniform that strolls past a checkpoint on day one of a clean record gets you stared at once the city has reason to doubt your face.

### Wanted levels as fading heat, from GTA and Elder Scrolls

A wanted level that only clears when you pay someone belongs to games where you play a professional criminal. ShanghaiShadows wanted level, 0 to 3, behaves more like heat in GTA or a bounty in the Elder Scrolls series where it decays only through consecutive days without further trouble, faster if you stay close to a safe room. At level 2 ordinary vendors simply refuse to serve you and patrols double, which matters enormously when staying fed while having a low inventory count is a daily problem. 

### Your death belongs to someone else, - NetHack

Roguelikes have shipped permadeath with inheritance for decades. NetHack's bones files drop a dead player's belongings and ghost into the dungeon where future players can find them, and Dwarf Fortress succession games hand one collapsing fortress between players as shared history. Shanghai Shadows combines the two where when your character dies, a death journal materialises where you fell, carrying your knowledge, journal entries, and testimonies, and another player must physically find and read it, claimable once across the whole server. Your successor wakes in a safehouse and retrieves whatever you stashed. Even the Day 180 world reset preserves death journals, so a character months from now can read what somebody learned in a timeline that no longer exists. Your worst moments literally become content somewhat also similar to blood streaks in Dark Souls.

### A trust ledger designed to be unfair, - Fallout: New Vegas

New Vegas proved that the best reputation systems are the ones where you cannot max everything. Seven factions live here, and you hold separate trust with each faction-role pair starting neutral at 50. Every action pays some ledger and debits another, often several at once, and the exchange rates are deliberately asymmetric. At connected standing (70+) each faction grants something concrete, extra safehouse rooms, free weapon repairs, checkpoint passage, a faster-clearing criminal record, which means the perks themselves force a political identity on you. Trust also decays under neglect, because in occupied Shanghai nobody's goodwill keeps indefinitely.

### The classic telephone game as a data structure

Rumour propagation is the schoolyard telephone game turned into an engineering contract. Every rumour is an immutable, hash-chained record, and each hop between tellers deterministically mutates the telling where names can swap, numbers might exaggerate, meanings can  invert, scaled by personality so honest carriers preserve the story and gossips/negative characters corrupt it faster. After five hops the text is garbled beyond recovery. Different factions retell the same event with their own institutional spin, the resistance says fascist forces, the Kempeitai says terrorist elements. Your crimes enter this web automatically as witnessed events, and Red Dead Redemption 2 showed just how much life comes from NPCs reacting to what they actually saw rather than to a script.

## Running it locally

Requirements: Python 3.11 or newer, and Node 20 only if you want to modify or rebuild the frontend (the repository ships a built client).

```bash
python -m pip install -r requirements.txt
python main.py
```

Then open `http://127.0.0.1:8080`. The same server hosts the browser client, the HTTP API, and the WebSocket connection (by default proxied through the same port; raw socket settings live in `.env`).

Configuration is optional. Copy `.env.example` to `.env` for:

| Variable | Default | Purpose |
|---|---|---|
| `HTTP_HOST` / `HTTP_PORT` | `127.0.0.1` / `8080` | Web server bind address |
| `WS_HOST` / `WS_PORT` | `127.0.0.1` / `8765` | WebSocket settings |
| `LOCALE` | `en` | `en` or `zh` |
| `HACKCLUB_API_KEY` | unset | Optional; enables AI-enhanced newspaper prose via Hack Club's AI proxy |
| `HACKCLUB_MODEL` | `qwen/qwen3-32b` | Model used when the key is present |

Without an API key everything still works; generated prose falls back to deterministic templates. On the link in the demo, the hackclub api key should work, if it doesnt then its either I have ran out of credits or HCAI is down.

Other ways to run:

```bash
# Windows one-step launcher (builds the client if needed)
start.bat

# Docker (two-stage build: Node compiles the Vue client, Python serves it)
docker build -t shanghai-shadows .
docker run -p 8080:8080 shanghai-shadows
```

Saves live under `server/data/saves/`; mount it as a volume in Docker to persist worlds. A `render.yaml` is included for deploying to Render.

Frontend development:

```bash
npm --prefix client-vue install
npm --prefix client-vue run dev      # Vite hot reload against a running server
npm --prefix client-vue run build   # rebuild the served client
npm --prefix client-vue test        # Vitest suite
```

## Development and testing

```bash
python -m pytest                     # ~168 test files covering nearly every mechanic
python -m pytest tests/test_curfew.py -v    # example focused run
```

Tests cover mechanics, persistence migrations, tutorial choreography, and content integrity, including checks that narrative references resolve to real identifiers. Behaviour changes are expected to arrive with regression tests; several subtle mechanics (curfew arrest sequencing, rumour distortion, journal claiming) are pinned by tests precisely because they broke silently during development.

To regenerate the tutorial transcript document after changing tutorial content:

```bash
python scripts/generate_tutorial_transcript.py
```

## Where it is now

As of late August 2026: 8 zones, ~90 rooms, 101 NPCs with individual behaviour trees and voice sheets, ~115 storylets, 76 ambient events, 60 missions, 84 catalogued mechanics, and a test suite collected at around 1,100 cases. Both normative documents are current with the implementation.

Honest limitations:

- Two client sound slots (`yell`, `struggle`) still have no assets, so those effects stay silent.
- Some mechanics drift between the reference document and code in minor ways (documented pricing layers versus the additional undocumented morale modifier, season boundaries, the exact fabi/silver exchange rate being implicit).
- A few rough edges survive in code: the tutorial's hide check always succeeds regardless of skill, buying a newspaper gives no feedback when you cannot afford it.
- Balance beyond solo and small-group play is untested. The simulation tooling exists but predates many systems.
- There is no public deployment yet.

## Where I want to take it next

Implemented and working now: everything described in "How the game works", including the full tutorial, permadeath lineage, rumour web, curfew custody, and Day 180 endings.

Planned next, in rough priority order:

- **Finish audio coverage.** Most weather, UI, and event sounds ship today; the remaining unmapped slots need assets, and the sound credits need finalising before any public release.
- **Content depth in the weaker districts.** The Bund and the teahouse core are dense; some outer zones are structurally complete but thinly populated. The expansion plan exists district by district.
- **Closing the doc/code drift list.** Small reconciliations, each trivial, collectively worth doing before more systems pile on top.
- **Public deployment**, so the multiplayer premise stops being hypothetical. The game is a different object when strangers share the city.
- **Balance simulation refresh**, bringing the playthrough analysis tooling up to date with post-June systems so numbers stop being tuned by feel.

Being explored, not committed:

- An internal cost for violence (morale consequences for killing) to complement the external ones, or a deliberate decision that the absence is correct.
- Extending City Memory further: district-level reputation rather than only individual NPCs' fear, so neighbourhoods themselves develop attitudes toward you.

## Credits & Inspiration

- **[ForlornMUD](https://github.com/ForlornMUD/ForlornMUD)**, encountered during Hack Club's Flavortown hackathon, is the reason this project exists. It demonstrated that a text world could carry a whole RPG, and everything here descends from wanting to try that myself in a different historical register.
- **Design lineage I consciously borrowed from:** behaviour-tree AI with blackboards from Bungie's Halo 2/3 era (popularised by Gears of War); Thief: The Dark Project's spatial sound propagation; Hitman's staged disguise suspicion; GTA and Elder Scrolls wanted-heat decay; Fallout: New Vegas's asymmetric faction reputation; NetHack's bones files and Dwarf Fortress succession for permadeath inheritance; Red Dead Redemption 2's witness reactions; Middle-earth: Shadow of Mordor's memory-driven NPCs.
- **Games that proved the framing could work:** This War of Mine and Pathologic for civilian survival under war as a real gameplay proposition rather than a cutscene; Papers, Please for document-and-checkpoint tension; Failbetter Games' Fallen London for the storylet format this game's encounters are built on.
- **Hack Club**, for the hackathon, and for running the AI proxy used for in-game newspaper prose.
- Built on Python (asyncio, websockets, aiohttp, PyYAML, bcrypt) and Vue 3 (Vite, Vuex, Vitest).
- Sound effects in the client are sourced from Minecraft (Mojang), used per the Minecraft Usage Guidelines for non-commercial fan projects; formal credit placement is planned for release.
- The historical grounding leans on research catalogs maintained under `docs/private/`, which record sources for period details, currency values, and testimonies referenced in-game. Historical facts are treated as constraints; the characters and plot events are fiction.


## AI Disclosure

During development I used AI tools for supporting tasks: skeleton code scaffolding, lint-style cleanup, translating stories from mandarin to english as there are some barriers to translation and understanding, and review passes. The game's systems, mechanics, and narrative content were designed and written by me along with the code unless stated so in the commit.

One AI integration is part of the shipped product and is the newspaper system optionally calls Hack Club's AI proxy (`ai.hackclub.com`) to vary generated article prose, gated behind an API key, with a deterministic fallback when the key is absent. The game runs fully without it although a little less polished and repetitive for the function.
