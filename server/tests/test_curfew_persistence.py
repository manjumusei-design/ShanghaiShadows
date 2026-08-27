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


def test_curfew_state_round_trips_with_night_key_zero():
    original = PlayerData(
        username="curfew-state",
        curfew_immunity_expires_at=1441,
        last_curfew_night_key=0,
    )


    restored = deserialize_player(serialize_player(original))

    assert restored.curfew_immunity_expires_at = 1441
    assert restored.last_curfew_name_key == 0


def test_old_save_defaults_curfew_state_and_drops_legacy_fields_on_next_save():
    restored = deserialize_player(
        {
            "username": "old-curfew",
            "last_curfew_penalty_day": 12,
            "curfew_hidden_until_minute": 1500,
            "curfew_hidden_day": 12,
            "curfew_immunity_until": 1900,
        }
    )

    assert restored.curfew_immunity_expires_at == -1
    assert restored.last_curfew_night_key is None
    assert not hasattr(restored, "curfew_hidden_until_minute")
    assert not hasattr(restored, "curfew_hidden_day")
    payload = serialize_player(restored)
    for field_name in (
        "last_curfew_penalty_day",
        "curfew_hidden_until_minute",
        "curfew_hidden_day",
        "curfew_immunity_until",
    ):
        assert field_name not in payload


@pytest.mark.parametrize("trust", [24, 25, 49])
@pytest.mark.asyncio
async def test_escape_consumes_charge_once_and_moves_through_legal_exit_only(trust):
    player = PlayerData(
        username="escape",
        inventory=[item("kept", instance_id="kept")],
        escape_charge_available=True,
    )
    set_kempeitai_trust(player, trust)
    lane = Room(id="lane", title="Lane", description="", indoors=False)
    tutorial_room = Room(
        id="tut_x_lane", title="Private", description="", indoors=False, tags=["tutorial"]
    )
    private_room = Room(id="p_private", title="Private", description="", indoors=False)
    street = Room(
        id="street",
        title="Street",
        description="",
        indoors=False,
        exits={"east": "lane", "west": "tut_x_lane", "north": "p_private"},
    )
    world = SimpleNamespace(
        get_room=lambda room_id: {
            "lane": lane,
            "tut_x_lane": tutorial_room,
            "p_private": private_room,
            "street": street,
        }.get(room_id)
    )
    ctx = make_context(player, room=street, world=world)
    calls = []

    async def move(received_ctx, direction):
        calls.append((received_ctx, direction))

    resolution = await resolve_curfew_encounter(
        ctx,
        CurfewTrigger.PATROL_CONTACT,
        randint=lambda low, high: 1,
        escape_move=move,
    )

    assert resolution.status == "escape"
    assert player.last_curfew_night_key == 2
    assert player.escape_charge_available is False
    assert calls == [(ctx, "east")]
    assert player.custody_until == -1


@pytest.mark.parametrize("trust", [25, 49])
@pytest.mark.asyncio
async def test_custody_confiscates_inventory_and_records_shared_release_minute(trust):
    weapon = item("weapon", is_weapon=True)
    armour = item("armour", is_armour=True)
    disguise = item("disguise", disguise_id="worker")
    player = PlayerData(
        username="custody",
        inventory=[weapon, armour, disguise],
        escape_charge_available=False,
        money_fabi=9,
        money_silver=8,
        money_military_yen=7,
        equipped_weapon_id="weapon",
        worn_armour_id="armour",
        equipped_disguise_item_id="disguise",
        disguise="worker",
    )
    set_kempeitai_trust(player, trust)
    ctx = make_context(player)
    resolution = await resolve_curfew_encounter(
        ctx,
        CurfewTrigger.PATROL_CONTACT,
        randint=lambda low, high: 1,
    )

    assert resolution.status == "custody"
    assert player.last_curfew_night_key == 2
    assert set(resolution.confiscated_item_ids) == {"weapon", "armour", "disguise"}
    assert player.inventory == []
    assert player.equipped_weapon_id == ""
    assert player.worn_armour_id == ""
    assert player.equipped_disguise_item_id == ""
    assert player.disguise == ""
    assert player.custody_until == game_clock_total_minutes(GameTime(day=2, minute=1200)) + 1440
    assert player.custody_detention_room == "street"
    assert (player.money_fabi, player.money_silver, player.money_military_yen) == (9, 8, 7)


@pytest.mark.asyncio
async def test_arrest_without_legal_exit_enters_custody_without_consuming_charge():
    player = PlayerData(username="no-exit", escape_charge_available=True)
    set_kempeitai_trust(player, 30)
    ctx = make_context(player)

    resolution = await resolve_curfew_encounter(
        ctx,
        CurfewTrigger.PATROL_CONTACT,
        randint=lambda low, high: 1,
    )

    assert resolution.status =="custody"
    assert player.escape_charge_available is True
    assert player.custody_until == game_clock_total_minutes(GameTime(day=2, minute=1200)) + 1440


@pytest.mark.asyncio
async def test_high_trust_successful_arrest_uses_custody_and_preserves_wallet():
    player = PlayerData(
        username="warning",
        inventory=[item("kept", instance_id="kept")],
        escape_charge_available=False
        money_fabi=9,
        money_silver=8
        money_military_yen=7,
        equipped_weapon_id="kept",
    )
    set_kempeitai_trust(player, 50)
    ctx = make_context(player)

    resolution = await resolve_curfew_encounter(
        ctx,
        CurfewTrigger.PATROL_CONTACT,
        randint=lambda low, high: 1,
    )

    assert resolution.status == "custody"
    assert player.last_curfew_night_key == 2
    assert player.inventory == []
    assert player.equipped_weapon_id == ""
    assert player.custody_until == game_clock_total_minutes(GameTime(day=2, minute=1200)) + 1440
    assert (player.money_fabi, player.money_silver, player.money_military_yen) == (9, 8, 7)