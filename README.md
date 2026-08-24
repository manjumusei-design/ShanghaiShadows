# Shanghai Shadows

> Shanghai Shadows is a historic storytelling educative MUD that aims to be a simulator/mini shared world focused on exploration, actions and consequence. 


![Final UI](image.png)

**Play it here:** <https://shanghai.dino.icu/login>

Demo Tutorial walkthrough (no voice): 
--- TODO

## What Is It? / What Does It Do?

Shanghai Shadows is a historic/educative MUD set in the late 1930s where Shanghai was put under Japanese occupation. The game serves as a layer to make learning about historical events interesting, fresh and to gamify it and tell stories/events as how they have happened to showcase the brutality of the Japanese occupation during WW2.

The spin I have taken on the usual MUD gameplay which is explore, fight, loot, acquire XP, upgrade, and repeat which I wanted to make my own spin on and it resulted in creating an interconnected world where every action you do has an effect for example if you were to kill an npc in front of other npcs, they would remember. If you decided to shoot a gun or yell, NPCs would come flocking and investigating.

My gameplay loop is simple but more reactive where the player (who has 12 inventory slots) has to survive the occupation for 180 in game days, and learn about the city via experiencing npc to npc interactions, reading documents, letters and other pieces of memorabilia that migrants from all over China have left behind in Shanghai to piece together a perception of what Shanghai was like during occupation.

- NPC behaviour tree that I created after watching a video on Halos behaviour tree
- Interactive MUD interface that I designed from different shortcomings that I have analysed after playing a fellow hack clubbers project [ForlornMUD](https://github.com/Snxhit/ForlornMUD)/ [Flavortown ForlornMUD entry](https://flavortown.hackclub.com/projects/9751)
- Patrol system that uses pathfinding to mimic Kempeitai night curfew patrols
- Sound propagation system that is reactive to NPCs
- Rumour web where NPCs gossip about you and word spreads through the city
- Shared city clock, so every player lives through the same hunger decay, curfews and ambient events
- Economy with fabi inflation and seasonal food prices
- Curfew encounters with arrest chances and escape options

## Why I Made It

I made this MUD first and foremost because when I was reviewing projects on Flavortown I came across [ForlornMUD](https://github.com/Snxhit/ForlornMUD) which is a MUD (Multi User Dungeon) that is themed around Flavortown built in Godot. I was pretty intrigued since I was under the perception that a MUD cant be that interesting, its literally text on a screen how will it ever be interesting? It sat at the back of my head for a few weeks and suddenly sprang up when I was in Shanghai visiting my grandparents they told me of stories during their time growing up as children in Shanghai, as well as what stories their parents had told them and the hardships they faced such as rationing and ration cards, secret police raids, resistance, and so on. This kinda clicked in my head because Shanghai as compared to the rest of China is relatively small and could work as a MUD to retell the stories my grandparents told me along with stories that I got from Chinese forums such as Tieba and Zhihu who discuss regularly about history. So after that moment it just clicked and I knew what I wanted to make.

Now for the audience, I feel that this game would have some decent educational qualities as it is technically considered a history lesson bundled in a game so I settled that I wanted to keep this as a long horizon project and to get it super polished and then upload it to the middle school I graduated from as a game to teach middle and high schoolers on the occupation period. After doing some research I realized that I didnt really want it to be a main protagonist story where you defeat and liberate Shanghai from all of the evil bad guys since that didnt really happen and I wanted to focus on historical realism instead of revisionist history, thus I changed the gameplay loop to make the player/protagonist a nobody, a generic person in a sea of generic peoples that only wants to survive, explore and to be bounded by consequences of their own actions.

## How I Made It

### Tech Stack

- **Backend:** Python 3.11+ — `asyncio` game loop and world tick, `websockets` for the live connection, `aiohttp` for HTTP, `PyYAML` for all the world/narrative data, `bcrypt` for accounts
- **Frontend:** Vue 3 + TypeScript + Vite, with Vuex for state (auth / game / UI modules) and Vue Router for Login → Home → Lobby → Game
- **Data:** The whole city — rooms, NPCs, storylets, rumours, items — lives in YAML under `server/data/`, so content is editable without touching game logic

### Architecture In One Paragraph

One Python process runs everything where a WebSocket server drives a shared tick loop where a single city clock advances time for every player and NPC at once so everyone shares the same time and are subject to the Hunger decay, curfew enforcement, patrol movement, ambient events. The Vue client sends typed commands over WebSocket and renders server-approved messages; the same server hosts the browser client, HTTP API, and WebSocket on port 8080 (raw socket settings live in `.env`, default WS port 8765).

### Hosting

The live version runs on a Hack Club Nest VPS with DNS through Hack Club (`shanghai.dino.icu`), sized for roughly 30 concurrent players. There's also a `Dockerfile` if you'd rather containerize it:

```bash
docker build -t shanghai-shadows .
docker run -p 8080:8080 shanghai-shadows
```

### The build over time

The interface went through a lot of iterations, and each one came from a specific problem I ran into while playing. This is how the UI evolved, in order.

**1. The very first client was one HTML file, thrown together as a placeholder for testing. But I made one decision early that never changed which was to make the game render as a dark, monospace CRT terminal, because a MUD typically is played by communicating with the terminal + black background for eyestrain. 

![The first client: one HTML file, styled as a CRT terminal from day one](docs/images/ui-v1-placeholder-terminal.png)

**2. I set out to tackle a bunch of problems,  A MUD is scary for newcomers if the answer to everything is "read the docs". So the help output was initially designed around seven starter verbs (look, go, inventory, status, talk to, eat, help), and every room ends with a contextual "You can:" line that only lists actions that actually make sense right now. But I felt as though it added too much clutter and was kinda babysitting the player and thus I decided to scrap it.

![Seven verbs, contextual hints, colored exits](docs/images/ui-basic-commands.png)

**3. The wall of text problem.  Once conversations and journal entries started stacking up, the terminal became a solid wall of identical green text. Nothing was scannable and players couldn't tell dialogue from system messages from exits. This is when I realized that I could use colours to segregate and containerize certian categories of text so they wont be part of the wall of text chunk.

![Everything the same colour: a wall of text](docs/images/ui-nonverbose-journal.png)

4. Colour as navigation, not decoration. I colour-coded every text category: room tags, exits in cyan, items in yellow, NPC names in green, tutorial hints in their own bar. The catch I had to fight with was CSS overriding my colour codes, and once it worked I had to restrain myself from turning the screen into a rainbow vomit and had to consolidate categories.

![Colour-coded categories: exits, items, NPCs, tutorial hints](docs/images/ui-colour-categories.png)

**5. Making room entries breathe.** Room entry text got proper formatting: the room name is underlined as a heading, the atmospheric description sits in its own block, and tags like [safe] [indoors] sit on their own quiet line. The goal was that a room entry reads like a paragraph in a book, not a log dump. In the latest  rendition I moved the tags up to the right side of the UI.

![Tea House entry: underlined room name, prose block, quiet tags line](docs/images/ui-room-formatting.png)

6. Tab completion, borrowed from Mandarin input. Typing full commands like "talk to mrs. lin" gets old fast. I built cycling tab completion styled after how Mandarin input methods work: type a fragment, get a ranked suggestion panel. It went through several iterations before I settled on a top-down dropdown approach, and it gives the game a linux-esque feel.

![Typing "tak" suggests take, take from, take trishaw](docs/images/ui-tab-completion.png)

![The full suggestion panel, iterating toward a top-down dropdown](docs/images/ui-tabular-panel.png)

7. Examine that answers the "so what can I do with it" question. Examining an item used to just describe it. Now examine also tells you your actual options per item type, you can EAT a bowl of rice, but a brass key only offers DROP or SELL. 

![Examine shows per-item actions](docs/images/ui-examine-actions.png)

8. The final layout. Everything above got folded into a three-column HUD with a canvas area map and vitals/inventory/stats on the left, the terminal in the middle, and a live sidebar on the right showing room info, who's present, items here, active missions and known rumours. The design rule behind it is to make the world live in the terminal, the state lives in the sidebar, and you should never have to type a command just to check something the server already knows.

![The final UI: map, vitals, terminal, and live state sidebar](image.png)

**Why the final build is better.**

Against my own earlier builds, each iteration solved a specific usability problem. Colours made the terminal easier to scan. Better room formatting made descriptions easier to read. Tab completion reduced the friction of typing commands. But one problem survived every redesign: the game’s state still lived in the scrollback.

If you wanted to know your hunger, you typed status, read the result, and watched it disappear into the text stream. If you wanted to know who was in the room, you typed look again. The interface could tell you almost anything, but only after you asked, and only temporarily.

So instead of treating everything as terminal output, it gives persistent information a permanent place in the interface. The map and vitals stay visible on the left side of the panel. The terminal remains in the centre for your typing leisure, where the world’s prose, dialogue, and commands belong. The right sidebar holds the information the server already knows such as the current room you are in , npcs inside nearby, items on the ground, active missions, and rumours you have learned. These panels update with the game state rather than waiting for the player to request the same information repeatedly which also raise the question of "Do a lot of the commands in the game need deduplication?" Perhaps.

But either ways it was a step forwards as a result, the important state no longer disappears just because more text has been printed.

That is also where my frontend differs most from ForlornMUD, the project that originally inspired Shanghai Shadows. ForlornMUD uses an xterm.js terminal connected through a WebSocket-to-TCP bridge, preserving the traditional MUD model very closely. The browser essentially becomes a terminal, and the game arrives as one continuous stream of text. It does a lot within that constraint, including ASCII art (which I have an idea for the future on what to integrate ShanghaiShadows with after watching this one youtube video [ASCII City](https://www.youtube.com/watch?v=UCKEDWowc0o)), help cards, and profile-style output, but information is still fundamentally something the player has to request and then find again in the scrollback. Checking your surroundings, inventory, or character state means entering another command and clogging up the terminal.

I wanted to keep the part of that experience that made MUDs interesting to me in the first place. Shanghai Shadows still feels like a terminal. You still type commands. The prose still arrives through the centre of the screen. Colour, text, and command-driven interaction remain the game's main language.


Tldr: You type when you want to change the world. You LOOK when you want to understand your current state. The terminal remains the place where the game happens, but it no longer has to be the place where every piece of information is stored and refreshed.

![alt text](image.png)

### Running It Locally

Requirements: Python 3.11+. On Windows, `start.bat` does all of this for you.

```bash
git clone <repository-url>
cd SSL
python -m pip install -r requirements.txt
python main.py
```

Then open `http://127.0.0.1:8080` and create an account.

Optional config (via `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `HTTP_HOST` / `HTTP_PORT` | `127.0.0.1` / `8080` | Web server bind address |
| `WS_HOST` / `WS_PORT` | `127.0.0.1` / `8765` | WebSocket settings |
| `LOCALE` | `en` | `en` or `zh` |
| `HACKCLUB_API_KEY` | unset | Optional AI proxy key for newspaper prose variation |

Without an API key the game still runs since there is fallback to deterministic hardcoded templates.

## What I Struggled With (And What I Learned)

Building this project taught me quite a lot:

**Technical Skills**
- Learning `asyncio` which was my first time exposure building anything serious with async code, and a tick loop that runs the game and manages the server.
- Concurrency. With possible and future multiple players, a shared clock and background ticks all touching the same world state meant race conditions I had to hunt down one by one to prune.
- Making YAML data files long term data and content stores centralized so texts can be edited without touching game logic.

**Problem Solving**
- Managing a VERY VERY much larger codebase than I'm used to, and structuring a server with reusable logic. 
- Making invisible systems (NPC memory, rumours, consequences) quantifiable and visible to players, which turned out to be as much work as building the systems themselves with the amount of thought.
- Although I tried my best to write good quality code, although I see a lot of design choices biting me. I learnt a lot about DRY, and "Youre not gonna need it" principles.
- Properly using a VCS!

**Personal**
- Working on something for months until I'm actually satisfied with it.
- Building consistent and efficient work habits by working on something for 116 days with spread out effort.

## AI Disclosure

I used AI tools while building this project. I'd ask questions when stuck on a concept, use it to speed up boilerplate and repetitive scaffolding and to consider possible edge cases that I may have missed out upon, get a second pair of eyes on bugs I was chasing, and draft text I then rewrote. The game's design, its systems, the historical research, the world and narrative direction, and every architectural decision are mine, and everything in this repo was reviewed, tested, debugged, and play-tested by me before shipping.

