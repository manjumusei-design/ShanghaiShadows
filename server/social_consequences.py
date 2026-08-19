from typing import Optional


def active_social_consequences(shared, *, room_id: Optional[str] = None, npc_id: Optional[str] = None) -> list[dict]:
    records = getattr(shared, "social_consequences", {})
    active = []
    for consequence_id in sorted(records):
        record = records[consequence_id]
        if record.get("state") != "active":
            continue
        if record.get("visibility", "local") == "hidden":
            continue
        if room_id is not None and record.get("room_id") != room_id:
            continue
        if npc_id is not None and npc_id not in record.get("npc_ids", []):
            continue
        active.append(record)
    return active


def room_consequence_manifestation(shared, room_id: str) -> list[str]:
    return [
        record["room_manifestation"]
        for record in active_social_consequences(shared, room_id=room_id)
        if record.get("room_manifestation")
    ]


def find_consequence_ask_lead(shared, npc_id: str, room_id: str, topic: str) -> Optional[dict]:
    normalized_topic = " ".join(topic.lower().split())
    for record in active_social_consequences(shared, room_id=room_id, npc_id=npc_id):
        lead_topic = " ".join(str(record.get("ask_topic", "")).lower().split())
        if lead_topic and (not normalized_topic or normalized_topic == lead_topic):
            return record
    return None


def find_consequence_rumour(shared, npc_id: str) -> Optional[dict]:
    for record in active_social_consequences(shared, npc_id=npc_id):
        if record.get("rumour"):
            return record
    return None


def publish_consequence_rumour(shared, record: dict, actor, target) -> None:
    if record.get("visibility", "local") == "hidden":
        return
    rumour = record.get("rumour")
    if not rumour:
        return
    from .rumors import grant_observation, grant_npc_observation, publish_event_rumor
    consequence_id = str(record.get("id", "") or "")
    created_day = getattr(getattr(shared, "game_time", None), "day", 1)
    record_id = record.get("rumor_record_id")
    if not record_id or record_id not in shared.rumor_records:
        record_id = publish_event_rumor(
            shared,
            event_type=f"consequence_{consequence_id}",
            text=rumour,
            location=str(record.get("room_id", "") or ""),
            district=str(record.get("district_id", "") or ""),
            witnesses=[],
            faction_context="",
            created_day=created_day,
            category=str(record.get("category", "street_talk") or "street_talk"),
        )
        record["rumor_record_id"] = record_id
    for npc in (actor, target):
        grant_observation(npc, record_id, getattr(npc, "id", ""), created_day, [record_id])
        if rumour not in npc.memory:
            npc.memory.append(rumour)
    for witness_id in record.get("witnesses", []) or []:
        grant_npc_observation(shared, witness_id, record_id, created_day, [record_id])