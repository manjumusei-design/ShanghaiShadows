from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import json
import os

DISTRICT_OF = {
    "bund_dawn": "Bund",
    "bund_canton_road": "Bund",
    "customs_house": "Bund",
    "hsbc_building": "Bund",
    "tea_house": "Bund",
    "international_settlement_bar": "Bund",
    "checkpoint_garden_bridge": "Bund",
    "gmd_safehouse_bund": "Bund",
    "bund_river_promenade": "Bund",
    "holy_trinity_cathedral": "Bund",
    "bund_hankow_road": "Bund",
    "astor_house_alley": "Bund",
    "nanjing_road": "Nanjing Road",
    "sincere_department_store": "Nanjing Road",
    "wing_on_company": "Nanjing Road",
    "broadway_warehouses": "Nanjing Road",
    "sun_sun_store": "Nanjing Road",
    "checkpoint_soochow_creek": "Nanjing Road",
    "umbrella_market": "Nanjing Road",
    "velvet_nightclub": "Nanjing Road",
    "commercial_black_market": "Nanjing Road",
    "commercial_printshop": "Nanjing Road",
    "commercial_watchmaker": "Nanjing Road",
    "commercial_gang_office": "Nanjing Road",
    "yuyuan_garden_gate": "Old City",
    "city_god_temple": "Old City",
    "tortoise_shell_alley": "Old City",
    "yuyuan_rear_lanes": "Old City",
    "grey_brick_longtang": "Old City",
    "old_city_market": "Old City",
    "st_josephs_nanshi": "Old City",
    "gmd_safehouse_old_city": "Old City",
    "old_city_tea_room": "Old City",
    "laundry_line_courtyard": "Old City",
    "persimmon_tree_courtyard": "Old City",
    "old_city_clinic": "Old City",
    "old_city_market_stall": "Old City",
    "checkpoint_north_gate": "Hongkou",
    "hongkou_checkpoint_square": "Hongkou",
    "wayside_road": "Hongkou",
    "japanese_bathhouse_lane": "Hongkou",
    "dobun_shoin_academy_gate": "Hongkou",
    "dobun_shoin_academy": "Hongkou",
    "kempeitai_hq": "Hongkou",
    "university": "Hongkou",
    "hongkou_field_hospital": "Hongkou",
    "hongkou_refugee_block": "Hongkou",
    "little_tokyo_row_houses": "Hongkou",
    "seward_road_tenements": "Hongkou",
    "hongkou_detention": "Hongkou",
    "avenue_joffre_market": "French Concession",
    "rue_lafayette": "French Concession",
    "cercle_sportif_francais": "French Concession",
    "plane_tree_avenue": "French Concession",
    "rue_du_consulat_gardens": "French Concession",
    "french_concession_safehouse": "French Concession",
    "french_jazz_cafe": "French Concession",
    "french_consulate_office": "French Concession",
    "french_newspaper_office": "French Concession",
    "french_bakery": "French Concession",
    "glass_arcade": "French Concession",
    "eglise_saint_pierre": "French Concession",
    "customs_house_jetty": "Yangpu",
    "jardine_matheson_wharf": "Yangpu",
    "nanshi_fishermans_pier": "Yangpu",
    "imperial_army_wharf": "Yangpu",
    "dock_warehouse": "Yangpu",
    "warehouse_district": "Yangpu",
    "docks_cargo_berth": "Yangpu",
    "mission_supply_huozhan": "Yangpu",
    "nanshi_tea_duizhan": "Yangpu",
    "rue_montauban_silk_huozhan": "Yangpu",
    "yangshupu_factory_floor": "Yangpu",
    "printers_union_cellar": "Zhabei",
    "power_station_bunker": "Zhabei",
    "guerrilla_supply_cache": "Zhabei",
    "radio_communications_room": "Zhabei",
    "boone_road_school": "Zhabei",
    "mill_workers_night_school": "Zhabei",
    "chapei_ruins": "Zhabei",
    "mctyeire_school": "Xujiahui",
    "zikawei_cathedral": "Xujiahui",
    "church_refugee_clinic": "Xujiahui",
    "mctyeire_classroom": "Xujiahui",
    "zikawei_mission_chapel": "Xujiahui",
    "chungking_radio_station": "Xujiahui",
    "intelligence_bureau_annex": "Xujiahui",
    "hidden_altar_undercroft": "Xujiahui",
}

ZONE_TAG_OF_DISTRICT = {
    "Bund": "bund",
    "Nanjing Road": "nanjing_rd",
    "Old City": "old_city",
    "Hongkou": "hongkou",
    "French Concession": "french",
    "Yangpu": "yangpu",
    "Zhabei": "zhabei",
    "Xujiahui": "xujiahui",
}


class TopologyValidationError(Exception):
    pass


@dataclass(frozen=True)
class Topology:
    nodes: frozenset
    district_of: dict
    zone_tags: dict
    exits: dict
    coordinates: dict


TABLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "map_presentation.json",
)

APPROVED_BRIDGE_AREA_PAIRS = frozenset({
    frozenset((1, 2)), frozenset((2, 3)), frozenset((3, 4)),
    frozenset((1, 5)), frozenset((2, 6)), frozenset((3, 7)),
    frozenset((5, 6)), frozenset((6, 7)),
})

ONE_STEP_EDGES = 120
BRIDGE_COUNT = 8


def _load_table():
    with open(TABLE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def derive_adjacency(table=None):
    table = table if table is not None else _load_table()
    pos = {r: tuple(c) for r, c in table["public"].items()}
    by_cell = {c: r for r, c in pos.items()}

    edges = set()
    for (x, y), room in by_cell.items():
        for dx, dy in ((1, 0), (0, 1)):
            neighbour = by_cell.get((x + dx, y + dy))
            if neighbour:
                edges.add(tuple(sorted((room, neighbour))))

    area_of_room = {}
    for area_key, meta in table["areas"].items():
        for room in meta.get("rooms", []):
            area_of_room[room] = int(area_key)
    missing_area = sorted(set(pos) - set(area_of_room))
    if missing_area:
        raise TopologyValidationError(
            "locked table has no area metadata for %s" % missing_area
        )

    bridges = []
    for a, b in table["bridges"]:
        ax, ay = pos[a]
        bx, by = pos[b]
        steps = abs(ax - bx) + abs(ay - by)
        if steps != 2:
            raise TopologyValidationError(
                "bridge %s<->%s spans %d steps (must be 2)" % (a, b, steps)
            )
        if (ax - bx) and (ay - by):
            raise TopologyValidationError(
                "bridge %s<->%s is diagonal" % (a, b)
            )
        pair = frozenset((area_of_room[a], area_of_room[b]))
        if len(pair) == 1:
            raise TopologyValidationError(
                "two-step link inside one area: %s<->%s" % (a, b)
            )
        if pair not in APPROVED_BRIDGE_AREA_PAIRS:
            raise TopologyValidationError(
                "bridge %s<->%s connects unapproved areas %d/%d"
                % (a, b, area_of_room[a], area_of_room[b])
            )
        edges.add(tuple(sorted((a, b))))
        bridges.append(tuple(sorted((a, b))))

    one_step_count = len(edges) - len(bridges)
    if len(pos) != 88:
        raise TopologyValidationError("public rooms != 88 (%d)" % len(pos))
    if one_step_count != ONE_STEP_EDGES:
        raise TopologyValidationError(
            "one-step connections != %d (%d)"
            % (ONE_STEP_EDGES, one_step_count)
        )
    if len(bridges) != BRIDGE_COUNT:
        raise TopologyValidationError(
            "bridges != %d (%d)" % (BRIDGE_COUNT, len(bridges))
        )

    PORT_BY_DELTA = {(-1, 0): "west", (1, 0): "east",
                     (0, -1): "north", (0, 1): "south"}
    INVERSE = {"west": "east", "east": "west", "north": "south",
               "south": "north"}
    adjacency = {room: {} for room in pos}
    for a, b in edges:
        dx = (pos[b][0] > pos[a][0]) - (pos[b][0] < pos[a][0])
        dy = (pos[b][1] > pos[a][1]) - (pos[b][1] < pos[a][1])
        port_a = PORT_BY_DELTA[(dx, dy)]
        adjacency[a][port_a] = b
        adjacency[b][INVERSE[port_a]] = a
    return pos, adjacency


def build_topology(table_path=None):
    import json as _json

    table = (
        _load_table() if table_path is None
        else _json.load(open(table_path, encoding="utf-8"))
    )
    pos, exits_by_direction = derive_adjacency(table)

    nodes = frozenset(pos)
    if sum(len(e) for e in exits_by_direction.values()) != 2 * (
        ONE_STEP_EDGES + BRIDGE_COUNT
    ):
        raise TopologyValidationError("mismatch")
    seen = {"bund_dawn"}
    queue = deque(["bund_dawn"])
    while queue:
        n = queue.popleft()
        for d in exits_by_direction[n].values():
            if d not in seen:
                seen.add(d)
                queue.append(d)
    if seen != set(exits_by_direction):
        raise TopologyValidationError("grid graph not connected")

    district_of = {rid: d for rid, d in DISTRICT_OF.items() if rid in nodes}
    zone_tags = {rid: ZONE_TAG_OF_DISTRICT[d] for rid, d in district_of.items()}

    return Topology(
        nodes=nodes,
        district_of=dict(district_of),
        zone_tags=zone_tags,
        exits={node: dict(e) for node, e in exits_by_direction.items()},
        coordinates=pos,
    )


if __name__ == "__main__":
    topo = build_topology()
    und = {frozenset((s, d)) for s in topo.nodes for d in topo.exits[s].values()}
    print("public rooms:", len(topo.nodes))
    print("undirected:", len(und))
    print("directed:", sum(len(e) for e in topo.exits.values()))
