def hide_requirement_for_room(room) -> int:
    tags = set(getattr(room, "tags", []) or [])
    if "authority_controlled" in tags or "authority" in tags:
        return 75
    if getattr(room, "hiding_spots", False):
        return 25
    return 50