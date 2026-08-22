import random
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from .constants import DISARM_CHANCE_CAP, MORALE_LOW_THRESHOLD, MORALE_PENALTY_MAX, STEALTH_KILL_BONUS, WEAPON_TYPE_BASE_DAMAGE, STEALTH_DAMAGE_BONUS
from .formatting import format_bold
from .pathfinding import SoundEvent, emit_sound

if TYPE_CHECKING:
    from .world import Item


def counter_damage_for(gap: int) -> int:
    return max(5, min(25, 5 + max(0, gap) // 5))


def courage_multiplier_for(weapon) -> float:
    return 2.0 if weapon and "extended_magazine" in weapon.mods else 1.0


def compute_effective_courage(
    attacker_courage: int,
    attacker_weapon,
    attacker_hidden: bool,
    target_armour,
    attacker_morale: int,
    disguise_bonus: int = 0,
    courage_multiplier: float = 1.0,
): 
    effective_courage = attacker_courage
    if courage_multiplier != 1.0:
        effective_courage = int(attacker_courage * courage_multiplier)
    parts = [f"Courage ({attacker_courage})"]

    def add(label: str, delta: int) -> None:
        nonlocal effective_courage
        effective_courage += delta
        parts.append(f"{label} ({delta:+d})")

    if attacker_weapon:
        add(attacker_weapon.name, attacker_weapon.courage_bonus)
        mod_stealth = getattr(attacker_weapon, 'stealth_bonus', 0)
        if attacker_hidden and mod_stealth:
            add("silencer", mod_stealth)
    if attacker_hidden:
        add("stealth", STEALTH_KILL_BONUS)
    if target_armour and hasattr(target_armour, 'durability') and target_armour.durability <= 0:
        defence = 0
    else:
        defence = target_armour.defense_value if target_armour else 0
    if defence:
        add("armour", -defence)
    morale_pen = min(MORALE_PENALTY_MAX, MORALE_LOW_THRESHOLD - attacker_morale) if attacker_morale < MORALE_LOW_THRESHOLD else 0
    if morale_pen:
        add("shaken", -morale_pen)
    if disguise_bonus:
        add("disguise", disguise_bonus)
    if attacker_weapon and hasattr(attacker_weapon, 'durability') and attacker_weapon.durability <= 0:
        add("broken_weapon", -10)
    return effective_courage, parts, defence, morale_pen


def strip_article(name: str) -> str:
    if name.lower().startswith("an "):
        return name[3:]
    if name.lower().startswith("a "):
        return name[2:]
    return name


def with_article(name: str) -> str:
    name_lower = name.lower().strip()
    if name_lower.startswith("a ") or name_lower.startswith("an "):
        return name
    
    plural_suffixes = ("s", "files", "records", "documents", "cables", "lists", 
                       "drafts", "beads", "noodles", "provisions")
    if name_lower.endswith(plural_suffixes):
        return name

    vowel_starts = ("a", "e", "i", "o", "u")
    if name_lower[0] in vowel_starts:
        return f"an {name}"
    
    return f"a {name}"
    

@dataclass
class CombatResult:
    won: bool = False
    silent: bool = False
    disarmed: bool = False
    weapon_broken: bool = False
    instant_kill: bool = False
    attacker_damaged: int = 0
    target_damage: int = 0
    messages: List[str] = field(default_factory=list)
    breakdown: str = ""
    sound_event: Optional["SoundEvent"] = None


_HIT_LINES = [
    "Your strike finds its mark.",
    "You press the opening and land a clean blow.",
    "The hit connects and they stagger back.",
    "You commit to the strike and it pays off.",
]
_SILENT_KILL_LINES = [
    "You close the distance unseen and strike before they can cry out.",
    "From the shadow, one motion. They fold without a sound.",
    "Your blade finds them quietly and they drop.",
]
_DISARM_LINES = [
    "Your attack is deflected and your weapon spins away!",
    "They catch your wrist and tear the weapon from your grip!",
    "You overcommit; they turn it and send your weapon clattering off.",
]
_FAIL_LINES = [
    "Your attack falters. They counter and you take {dmg} damage.",
    "The struggle turns against you. You take {dmg} damage and give ground.",
    "You miss, and a blow comes back. You take {dmg} damage.",
]

COMBAT_DAMAGE_TEMPLATE = "You take {dmg} damage."
COMBAT_DAMAGE_BOLD_TEMPLATE = "You take <b>{dmg}</b> damage."


def resolve_attack(
    attacker_courage: int,
    attacker_weapon: Optional["Item"],
    target_authority: int,
    target_armour: Optional["Item"],
    attacker_hidden: bool = False,
    attacker_morale: int = 100,
    disguise_bonus: int = 0,
    courage_multiplier: float = 1.0,
) -> CombatResult:
    result = CombatResult()

    if attacker_weapon and hasattr(attacker_weapon, 'durability'):
        weapon_type = getattr(attacker_weapon, 'weapon_type', '') or ''
        if weapon_type == 'firearm':
            max_durability = max(1, getattr(attacker_weapon, 'max_durability', 1))
            wear_ratio = max(0.0, min(1.0, attacker_weapon.durability / max_durability))
            jam_chance = 0.5 if attacker_weapon.durability <= 0 else 0.02 + (1.0 - wear_ratio) * 0.28
            if random.random() < jam_chance:
                backfire = random.random() < 0.05
                dmg = random.randint(5, 10) if backfire else 0
                msg = "Your weapon jams. The firing pin clicks on an empty chamber."
                if backfire:
                    msg = "The weapon backfires! Hot metal burns your hand."
                return CombatResult(won=False, instant_kill=False, silent=False, attacker_damaged=dmg,breakdown=f"Your {attacker_weapon.name} jams! (broken)", disarmed=False)
        elif attacker_weapon.durability <= 0:
            if random.random() < 0.20:
                return CombatResult(won=False, instant_kill=False, silent=False,
                                  breakdown=f"Your {attacker_weapon.name} fails! (broken)", disarmed=False)

    weapon_type = attacker_weapon.weapon_type if attacker_weapon else ""
    effective_courage, parts, defence, morale_pen = compute_effective_courage(
        attacker_courage, attacker_weapon, attacker_hidden, target_armour,
        attacker_morale, disguise_bonus, courage_multiplier,
    )
    if attacker_hidden:
        result.silent = weapon_type == "stealth"
    result.breakdown = " ".join(parts) + f" = {effective_courage} vs authority ({target_authority})."

    if effective_courage >= target_authority:
        result.won = True
        result.instant_kill = True
        base = WEAPON_TYPE_BASE_DAMAGE.get(weapon_type, 20)
        if attacker_hidden and weapon_type == "stealth":
            base += STEALTH_DAMAGE_BONUS
        result.target_damage = max(1, base + random.randint(0, 10) - defence)
        if result.silent:
            result.messages.append(random.choice(_SILENT_KILL_LINES))
            result.messages.append("[Silent kill - no alarm were raised.]")
        else:
            result.messages.append(random.choice(_HIT_LINES))
    else:
        gap = target_authority - effective_courage
        result.attacker_damaged = counter_damage_for(gap)
        disarm_chance = min(gap * 2, DISARM_CHANCE_CAP)
        if random.randint(1, 100) <= disarm_chance:
            result.disarmed = True
            result.messages.append(random.choice(_DISARM_LINES))
        else:
            dmg_formatted = format_bold(str(result.attacker_damaged))
            result.messages.append(random.choice(_FAIL_LINES).format(dmg=dmg_formatted))

    return result


def degrade_weapon(weapon: "Item", attack_succeeded: bool) -> tuple:
    if weapon.durability == -1:
        return False, ""
    old_durability = weapon.durability
    if "stock" in weapon.mods:
        weapon.durability -= random.randint(1, 2)
    else:
        weapon.durability -= 5 if attack_succeeded else 2
    
    if weapon.durability <= 0:
        weapon.durability = 0
        return True, f"Your {strip_article(weapon.name)} has broken!"

    pct = int((weapon.durability / weapon.max_durability) * 100) if weapon.max_durability > 0 else 0
    if pct <= 20 and pct > 0:
        return False, f"Your {strip_article(weapon.name)} is nearly broken ({pct}% durability)."
    elif pct <= 40:
        return False, f"Your {strip_article(weapon.name)} is showing severe wear ({pct}% durability)."
    
    return False, ""


def degrade_armour(armour: "Item") -> tuple:
    if armour.durability == -1:
        return False, ""
    
    armour.durability -= 3
    
    if armour.durability <= 0:
        armour.durability = 0
        return True, f"Your {strip_article(armour.name)} has been destroyed!"
    pct = int((armour.durability / armour.max_durability) * 100) if armour.max_durability > 0 else 0
    if pct <= 20 and pct > 0:
        return False, f"Your {strip_article(armour.name)} is nearly destroyed ({pct}% durability)."
    return False, ""