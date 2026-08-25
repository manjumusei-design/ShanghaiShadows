#AI generated file for server/world_topology.py, used to define the topology of the game world. This file is generated from the canonical data in server/world_topology.py, it just builds on preexisting data that I had since I wanted to reorder the rooms.

from collections import defaultdict, deque
from dataclasses import dataclass
import sys

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

EXPECTED_DISTRICT_COUNTS = {
    "Bund": 12,
    "Nanjing Road": 12,
    "Old City": 13,
    "Hongkou": 13,
    "French Concession": 12,
    "Yangpu": 11,
    "Zhabei": 7,
    "Xujiahui": 8,
}

INTERNAL_EDGES = [
    ("bund_dawn", "bund_hankow_road"),
    ("bund_hankow_road", "bund_canton_road"),
    ("bund_canton_road", "customs_house"),
    ("customs_house", "hsbc_building"),
    ("hsbc_building", "international_settlement_bar"),
    ("international_settlement_bar", "tea_house"),
    ("tea_house", "checkpoint_garden_bridge"),
    ("bund_dawn", "astor_house_alley"),
    ("bund_dawn", "bund_river_promenade"),
    ("astor_house_alley", "bund_river_promenade"),
    ("bund_canton_road", "holy_trinity_cathedral"),
    ("hsbc_building", "gmd_safehouse_bund"),
    ("checkpoint_garden_bridge", "bund_canton_road"),
    ("bund_hankow_road", "astor_house_alley"),
    ("nanjing_road", "sincere_department_store"),
    ("sincere_department_store", "wing_on_company"),
    ("wing_on_company", "sun_sun_store"),
    ("sun_sun_store", "velvet_nightclub"),
    ("velvet_nightclub", "broadway_warehouses"),
    ("nanjing_road", "umbrella_market"),
    ("umbrella_market", "commercial_black_market"),
    ("sincere_department_store", "commercial_watchmaker"),
    ("wing_on_company", "commercial_printshop"),
    ("velvet_nightclub", "commercial_gang_office"),
    ("broadway_warehouses", "checkpoint_soochow_creek"),
    ("commercial_black_market", "sun_sun_store"),
    ("wing_on_company", "nanjing_road"),
    ("yuyuan_garden_gate", "city_god_temple"),
    ("city_god_temple", "old_city_market_stall"),
    ("old_city_market_stall", "old_city_tea_room"),
    ("old_city_tea_room", "tortoise_shell_alley"),
    ("tortoise_shell_alley", "yuyuan_rear_lanes"),
    ("yuyuan_rear_lanes", "yuyuan_garden_gate"),
    ("yuyuan_rear_lanes", "laundry_line_courtyard"),
    ("laundry_line_courtyard", "persimmon_tree_courtyard"),
    ("persimmon_tree_courtyard", "grey_brick_longtang"),
    ("grey_brick_longtang", "city_god_temple"),
    ("tortoise_shell_alley", "old_city_market"),
    ("grey_brick_longtang", "old_city_clinic"),
    ("old_city_clinic", "tortoise_shell_alley"),
    ("city_god_temple", "st_josephs_nanshi"),
    ("st_josephs_nanshi", "gmd_safehouse_old_city"),
    ("old_city_market", "old_city_market_stall"),
    ("checkpoint_north_gate", "hongkou_checkpoint_square"),
    ("hongkou_checkpoint_square", "wayside_road"),
    ("wayside_road", "japanese_bathhouse_lane"),
    ("japanese_bathhouse_lane", "little_tokyo_row_houses"),
    ("wayside_road", "hongkou_refugee_block"),
    ("hongkou_refugee_block", "hongkou_field_hospital"),
    ("wayside_road", "seward_road_tenements"),
    ("seward_road_tenements", "university"),
    ("university", "dobun_shoin_academy"),
    ("dobun_shoin_academy", "dobun_shoin_academy_gate"),
    ("dobun_shoin_academy_gate", "little_tokyo_row_houses"),
    ("hongkou_checkpoint_square", "kempeitai_hq"),
    ("kempeitai_hq", "hongkou_detention"),
    ("hongkou_refugee_block", "seward_road_tenements"),
    ("university", "japanese_bathhouse_lane"),
    ("avenue_joffre_market", "rue_lafayette"),
    ("rue_lafayette", "french_jazz_cafe"),
    ("french_jazz_cafe", "plane_tree_avenue"),
    ("plane_tree_avenue", "rue_du_consulat_gardens"),
    ("rue_du_consulat_gardens", "french_consulate_office"),
    ("avenue_joffre_market", "eglise_saint_pierre"),
    ("eglise_saint_pierre", "glass_arcade"),
    ("glass_arcade", "rue_lafayette"),
    ("rue_lafayette", "french_bakery"),
    ("french_jazz_cafe", "cercle_sportif_francais"),
    ("plane_tree_avenue", "french_newspaper_office"),
    ("cercle_sportif_francais", "french_concession_safehouse"),
    ("french_bakery", "avenue_joffre_market"),
    ("customs_house_jetty", "jardine_matheson_wharf"),
    ("jardine_matheson_wharf", "nanshi_fishermans_pier"),
    ("nanshi_fishermans_pier", "imperial_army_wharf"),
    ("imperial_army_wharf", "dock_warehouse"),
    ("dock_warehouse", "warehouse_district"),
    ("warehouse_district", "docks_cargo_berth"),
    ("docks_cargo_berth", "mission_supply_huozhan"),
    ("mission_supply_huozhan", "nanshi_tea_duizhan"),
    ("nanshi_tea_duizhan", "rue_montauban_silk_huozhan"),
    ("rue_montauban_silk_huozhan", "yangshupu_factory_floor"),
    ("yangshupu_factory_floor", "warehouse_district"),
    ("jardine_matheson_wharf", "dock_warehouse"),
    ("nanshi_fishermans_pier", "customs_house_jetty"),
    ("imperial_army_wharf", "warehouse_district"),
    ("chapei_ruins", "boone_road_school"),
    ("boone_road_school", "mill_workers_night_school"),
    ("mill_workers_night_school", "printers_union_cellar"),
    ("printers_union_cellar", "power_station_bunker"),
    ("power_station_bunker", "guerrilla_supply_cache"),
    ("guerrilla_supply_cache", "radio_communications_room"),
    ("radio_communications_room", "chapei_ruins"),
    ("mill_workers_night_school", "chapei_ruins"),
    ("mctyeire_school", "mctyeire_classroom"),
    ("mctyeire_school", "zikawei_cathedral"),
    ("zikawei_cathedral", "zikawei_mission_chapel"),
    ("zikawei_mission_chapel", "church_refugee_clinic"),
    ("church_refugee_clinic", "hidden_altar_undercroft"),
    ("hidden_altar_undercroft", "zikawei_cathedral"),
    ("chungking_radio_station", "intelligence_bureau_annex"),
    ("intelligence_bureau_annex", "zikawei_cathedral"),
    ("church_refugee_clinic", "mctyeire_school"),
]

BRIDGE_EDGES = [
    ("nanjing_road", "bund_hankow_road"),
    ("checkpoint_north_gate", "checkpoint_garden_bridge"),
    ("checkpoint_north_gate", "checkpoint_soochow_creek"),
    ("old_city_market", "bund_river_promenade"),
    ("st_josephs_nanshi", "avenue_joffre_market"),
    ("plane_tree_avenue", "zikawei_mission_chapel"),
    ("hongkou_refugee_block", "chapei_ruins"),
    ("seward_road_tenements", "yangshupu_factory_floor"),
    ("nanshi_fishermans_pier", "bund_river_promenade"),
    ("umbrella_market", "yuyuan_rear_lanes"),
    ("nanshi_tea_duizhan", "guerrilla_supply_cache"),
    ("rue_du_consulat_gardens", "mctyeire_school"),
    ("boone_road_school", "chungking_radio_station"),
    ("mission_supply_huozhan", "eglise_saint_pierre"),
]

PINNED_EDGE_PORTS = {
    frozenset(("boone_road_school", "chungking_radio_station")): {
        "boone_road_school": "south",
        "chungking_radio_station": "north",
    },
    frozenset(("mission_supply_huozhan", "eglise_saint_pierre")): {
        "mission_supply_huozhan": "south",
        "eglise_saint_pierre": "north",
    },
}

INTENTIONAL_LEAVES = frozenset({
    "holy_trinity_cathedral",
    "gmd_safehouse_bund",
    "commercial_watchmaker",
    "commercial_printshop",
    "commercial_gang_office",
    "gmd_safehouse_old_city",
    "hongkou_field_hospital",
    "hongkou_detention",
    "french_consulate_office",
    "french_concession_safehouse",
    "french_newspaper_office",
    "mctyeire_classroom",
})

ROOT = "bund_dawn"
INVERSE_PORT = {"north": "south", "south": "north", "east": "west", "west": "east"}
PORTS = ("north", "east", "south", "west")
PORT_OFFSETS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}


class TopologyValidationError(Exception):
    pass


@dataclass(frozen=True)
class Topology:
    nodes: frozenset
    district_of: dict
    zone_tags: dict
    exits: dict
    coordinates: dict


class _Axis:
    def __init__(self):
        self.succ = {}
        self.pred = {}

    def _reaches(self, start, target):
        seen = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            for successor in self.succ.get(current, ()):
                if successor not in seen:
                    stack.append(successor)
        return False

    def cycle_if(self, lower, higher):
        return self._reaches(higher, lower)

    def add(self, lower, higher):
        self.succ.setdefault(lower, set()).add(higher)
        self.pred.setdefault(higher, set()).add(lower)

    def remove(self, lower, higher):
        successors = self.succ.get(lower)
        if successors is not None:
            successors.discard(higher)
        predecessors = self.pred.get(higher)
        if predecessors is not None:
            predecessors.discard(lower)

    def layered(self):
        values = {}

        def calculate(node):
            if node in values:
                return values[node]
            best = 0
            for higher in sorted(self.succ.get(node, ())):
                best = max(best, calculate(higher) + 1)
            values[node] = best
            return best

        all_nodes = set(self.succ) | set(self.pred) | set(DISTRICT_OF)
        for node in sorted(all_nodes):
            calculate(node)
        return dict(values)


def _validate_tables(nodes, undirected_edges):
    if len(nodes) != 88:
        raise TopologyValidationError("expected exactly 88 canonical nodes")
    district_counts = {}
    for district in DISTRICT_OF.values():
        district_counts[district] = district_counts.get(district, 0) + 1
    if district_counts != EXPECTED_DISTRICT_COUNTS:
        raise TopologyValidationError("district counts do not match the frozen corpus")
    if len(INTERNAL_EDGES) != 102:
        raise TopologyValidationError("expected exactly 102 internal edges")
    if len(BRIDGE_EDGES) != 14:
        raise TopologyValidationError("expected exactly 14 bridge edges")
    if len(undirected_edges) != 116:
        raise TopologyValidationError("expected exactly 116 unique undirected edges")
    for source, dest in undirected_edges:
        if source == dest:
            raise TopologyValidationError("self edge: %s" % source)
        if source not in nodes or dest not in nodes:
            raise TopologyValidationError("edge endpoint missing from manifest: %s-%s" % (source, dest))


def _validate_graph(nodes, adjacency, undirected_edges):
    reachable = {ROOT}
    queue = deque([ROOT])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    if len(reachable) != len(nodes):
        raise TopologyValidationError("graph is not fully connected from %s" % ROOT)
    degrees = {node: len(adjacency[node]) for node in nodes}
    histogram = {}
    for degree in degrees.values():
        histogram[degree] = histogram.get(degree, 0) + 1
    if any(degree > 4 for degree in degrees.values()):
        raise TopologyValidationError("degree above 4 detected")
    if any(degree == 0 for degree in degrees.values()):
        raise TopologyValidationError("degree-0 room detected")
    leaves = {node for node, degree in degrees.items() if degree == 1}
    if leaves != set(INTENTIONAL_LEAVES):
        raise TopologyValidationError("leaf set does not match the frozen intentional leaves")
    expected_histogram = {1: 12, 2: 27, 3: 30, 4: 19}
    if histogram != expected_histogram:
        raise TopologyValidationError("degree histogram does not match the frozen graph")


def _assign_ports(nodes, undirected_edges):
    edges = sorted(tuple(sorted(edge)) for edge in undirected_edges)
    free_ports = {node: set(PORTS) for node in nodes}
    vertical = _Axis()
    horizontal = _Axis()
    assignment = {}

    pinned = {}
    for edge, constraint in PINNED_EDGE_PORTS.items():
        key = tuple(sorted(edge))
        if key not in set(edges):
            raise TopologyValidationError("pinned port edge missing from graph: %s" % (key,))
        pinned[key] = constraint

    def try_port(source, port, dest):
        inverse = INVERSE_PORT[port]
        if port not in free_ports[source]:
            return None
        if inverse not in free_ports[dest]:
            return None
        axis = vertical if port in ("north", "south") else horizontal
        lower, higher = (source, dest) if port in ("north", "west") else (dest, source)
        if axis.cycle_if(lower, higher):
            return None
        return port, inverse, axis, lower, higher

    def apply(source, port, dest):
        inverse = INVERSE_PORT[port]
        axis = vertical if port in ("north", "south") else horizontal
        lower, higher = (source, dest) if port in ("north", "west") else (dest, source)
        free_ports[source].discard(port)
        free_ports[dest].discard(inverse)
        assignment[tuple(sorted((source, dest)))] = (source, port, dest)
        axis.add(lower, higher)

    for key, constraint in sorted(pinned.items()):
        first_room, port = next(iter(constraint.items()))
        source, dest = key if key[0] == first_room else (key[1], key[0])
        if constraint[dest] != INVERSE_PORT[port]:
            raise TopologyValidationError(
                "pinned ports are not reciprocal for %s: %s" % (key, constraint)
            )
        outcome = try_port(source, port, dest)
        if outcome is None:
            raise TopologyValidationError(
                "pinned port conflict while assigning %s %s -> %s" % (source, port, dest)
            )
        apply(source, port, dest)

    remaining = [edge for edge in edges if edge not in assignment]

    def solve(index):
        if index == len(remaining):
            return True
        best_edge = None
        best_options = None
        for edge in remaining:
            if edge in assignment:
                continue
            source, dest = edge
            options = sum(1 for port in PORTS if try_port(source, port, dest))
            if options == 0:
                return False
            if best_options is None or options < best_options:
                best_edge = edge
                best_options = options
            if options == 1:
                break
        source, dest = best_edge
        for port in PORTS:
            outcome = try_port(source, port, dest)
            if outcome is None:
                continue
            port, inverse, axis, lower, higher = outcome
            free_ports[source].discard(port)
            free_ports[dest].discard(inverse)
            assignment[(source, dest)] = (source, port, dest)
            axis.add(lower, higher)
            if solve(index + 1):
                return True
            axis.remove(lower, higher)
            del assignment[(source, dest)]
            free_ports[source].add(port)
            free_ports[dest].add(inverse)
        return False

    sys.setrecursionlimit(20000)
    if not solve(0):
        raise TopologyValidationError("no complete reciprocal cardinal port assignment exists")
    exits = {node: {} for node in nodes}
    for source, port, dest in assignment.values():
        exits[source][port] = dest
        exits[dest][INVERSE_PORT[port]] = source
    return exits


def _place_coordinates(exits):
    vertical_values = _Axis()
    horizontal_values = _Axis()
    for source, exits_by_direction in exits.items():
        for direction, dest in exits_by_direction.items():
            axis = vertical_values if direction in ("north", "south") else horizontal_values
            lower, higher = (source, dest) if direction in ("north", "west") else (dest, source)
            axis.add(lower, higher)
    x_values = horizontal_values.layered()
    y_values = vertical_values.layered()
    positions = {node: (x_values[node], y_values[node]) for node in exits}

    horizontal_links = defaultdict(set)
    for source, exits_by_direction in exits.items():
        for direction, dest in exits_by_direction.items():
            if direction in ("east", "west"):
                horizontal_links[source].add(dest)
                horizontal_links[dest].add(source)
    component_of = {}
    component_id = 0
    for node in sorted(exits):
        if node in component_of:
            continue
        stack = [node]
        component_of[node] = component_id
        while stack:
            current = stack.pop()
            for neighbor in horizontal_links[current]:
                if neighbor not in component_of:
                    component_of[neighbor] = component_id
                    stack.append(neighbor)
        component_id += 1

    occupied = set()
    ordered_components = []
    seen_components = set()
    for node in sorted(positions):
        component = component_of[node]
        if component in seen_components:
            continue
        seen_components.add(component)
        ordered_components.append(component)
    for component in ordered_components:
        members = [n for n, c in component_of.items() if c == component]
        offset = 0
        while any(
            (positions[n][0] + offset, positions[n][1]) in occupied
            for n in members
        ):
            offset += 1
        for n in members:
            positions[n] = (positions[n][0] + offset, positions[n][1])
            occupied.add(positions[n])

    for source, exits_by_direction in exits.items():
        sx, sy = positions[source]
        for direction, dest in exits_by_direction.items():
            dx, dy = positions[dest]
            ox, oy = PORT_OFFSETS[direction]
            if ox and (dx - sx) * ox <= 0:
                raise TopologyValidationError(
                    "coordinate sign violation: %s %s %s" % (source, direction, dest)
                )
            if oy and (dy - sy) * oy <= 0:
                raise TopologyValidationError(
                    "coordinate sign violation: %s %s %s" % (source, direction, dest)
                )
    if len(set(positions.values())) != len(positions):
        raise TopologyValidationError("coordinates are not unique")
    return positions


def build_topology() -> Topology:
    nodes = frozenset(DISTRICT_OF)
    internal = {tuple(sorted(edge)) for edge in INTERNAL_EDGES}
    bridges = {tuple(sorted(edge)) for edge in BRIDGE_EDGES}
    if internal & bridges:
        raise TopologyValidationError("bridge edge duplicates an internal edge")
    undirected_edges = internal | bridges
    _validate_tables(nodes, undirected_edges)

    adjacency = {node: set() for node in nodes}
    for source, dest in undirected_edges:
        adjacency[source].add(dest)
        adjacency[dest].add(source)
    _validate_graph(nodes, adjacency, undirected_edges)

    exits = _assign_ports(nodes, undirected_edges)
    coordinates = _place_coordinates(exits)

    zone_tags = {
        node: ZONE_TAG_OF_DISTRICT[district]
        for node, district in DISTRICT_OF.items()
    }
    return Topology(
        nodes=nodes,
        district_of=dict(DISTRICT_OF),
        zone_tags=zone_tags,
        exits={node: dict(exits_by_direction) for node, exits_by_direction in exits.items()},
        coordinates=coordinates,
    )
