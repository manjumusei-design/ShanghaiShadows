from types import SimpleNamespace

import pytest

from server.curfew import (
    CurfewTrigger,
    curfew_immunity_active,
    game_clock_total_minutes,
    resolve_curfew_encounter,
)
from server.player_data import PlayerData, deserialize_player, serialize_player
from server.time_system import GameTime
from server.world import Item, Room


def make_context(play, game_time: None, room=None, world=None):
    room = room or Room(id="street", title="street", description="", indoors=False)
    game_time = game_time or GameTime(day=2, minute=1200)
    session = SimpleNamespace(player=player)
    world= world or SimpleNamespace(get_room=lambda room_id: room)
    shared = SimpleNamespace(game_time=game_time, world=world)
    return SimpleNamespace(session=session, shared=shared, room=room, disguises={})


def set_kempeitai_trust(player, value):
    player.trust["kempeitai"] = {"officer": value}


def item(item_id, *, instance_id="", is_weapon=False, is_armour=False, disguise_id=""):
    return Item(
        id=item_id,
        instance_id=instance_id,
        name=item_id,
        description="",
        is_weapon=is_weapon,
        disguise_id=disguise_id,
    )