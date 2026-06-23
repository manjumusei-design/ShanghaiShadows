from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_STAGE_DEFS = [
    {"verb": "look", "compass": "tutorial_tea_house", "hint_level": "explicit",
     "cmd_hint": "LOOK" around",
     "auto_greet": True,
     "msg": 'Uncle Liu catches your eye. "First time? Type LOOK to get your bearings. Every room will tell you whats here and where you can go with the LOOK command."',
    "blocked": {"room": "tutorial_checkpoint", "east": 'A Japanese soldier blocks the east gate. "Pass required to go through here unfortunately." He nods west, "However the Tea house is open."'},
    {"verb": "go", "target": "west", "compass": "tutorial_tea_house", "hint_level": "explicit",
    "cmd_hint": "GO WEST",
    "auto_greet": True,
    "msg": 'Uncle Liu gestures west with his hand. "Good. Now head WEST to the Tea House. Type GO WEST or open the map via MAP and navigate to the Tea House. Your compass already points the way at the bottom of the screen."',
    "response_msg": "You arrive at the Tea House."},
    
# 2
    {"verb": "talk to", "target": "mrs.lin", "compass": "tutorial_tea_house", "hint_level": "explicit",
     "cmd_hint": "TALK TO Mrs. Lin/Use the tab after 'TALK TO' to see options'"
     "msg": 'Mrs.Lin sets down her pot. "Welcome. Type TALK TO Mrs.Lin(or use the tab function after TALK)'
     }































































]