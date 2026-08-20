FACTION_DISPLAY_NAMES = {
    "ccp": "CCP",
    "gmd": "GMD",
    "kempeitai": "Kempeitai",
    "green_gang": "Green Gang",
    "french_concession": "French",
    "british": "British",
    "civilian": "", 
}


def format_bold(text: str) -> str:
    return f"<b>{text}</b>"


def format_bold_underline(text: str) -> str:
    return f"<b><u>{text}</u></b>"


def format_italic(text: str) -> str:
    return f"<i>{text}</i>"


def format_bold_italic(text: str) -> str:
    return f"<b><i>{text}</i></b>"


TUTORIAL_NPC_NAMES = [
    "MRS. LIN", "COMRADE CHEN", "OLD GAO", "FANG JIE", "DOCTOR LI", "UNCLE LIU",
    "METEOROLOGIST ZHANG", "ELDER QIAN", "INSPECTOR PARK", "MOTHER JIN",
    "SCRIBE WEN", "OLD CRANE", "SISTER ZHAO", "PATROL GUARD", "DRUNK MERCHANT",
    "KEMPEITAI SOLDIER", "KEMPEITAI OFFICER", "JAPANESE OFFICER", "SOLDIER",
    "MRS LIN", "COMRADE CHEN", "OLD GAO", "FANG JIE", "DOCTOR LI", "UNCLE LIU",
]


def format_tutorial_text(text: str) -> str:
    result = text
    for name in sorted(TUTORIAL_NPC_NAMES, key=len, reverse=True):
        if name in result:
            result = result.replace(name, f"<b>{name}</b>")
    return result


def get_faction_tag(faction: str) -> str:
    display_name = FACTION_DISPLAY_NAMES.get(faction, "")
    if display_name:
        return f"[{display_name}]"
    return ""


def semantic_span(text: str, kind: str) -> str:
    return f'<sem type="{kind}">{text}</sem>'


def format_npc_presence(npc_name: str, faction: str, wounded: bool = False,
                       reveal_faction: bool = True) -> str:
    faction_tag = get_faction_tag(faction) if reveal_faction else ""
    name_part = semantic_span(npc_name, "npc")
    if faction_tag:
        if wounded:
            return f"{name_part} {faction_tag} is here, wounded and bleeding."
        else:
            return f"{name_part} {faction_tag} is here."
    else:
        if wounded:
            return f"{name_part} is here, wounded and bleeding."
        else:
            return f"{name_part} is here."


def format_item_list(items: list) -> str:
    return ", ".join(semantic_span(item, "item") for item in items)


def format_exit(direction: str, destination: str) -> str:
    return f"{semantic_span(direction, 'exit')} ({semantic_span(destination, 'exit')})"
