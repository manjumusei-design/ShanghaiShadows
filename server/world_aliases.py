#AI wrote this entire file, wanted to save some time doing repetitive work hence why I used it to reorder and realign my map without changing too much of the preexisting data.


from .world_topology import DISTRICT_OF

DIRECT_ROOM_ALIASES = {
        'bund_05': 'customs_house',
        'bund_07': 'hsbc_building',
        'bund_09': 'bund_canton_road',
        'bund_10': 'bund_hankow_road',
        'ccp_base_01': 'printers_union_cellar',
        'ccp_base_02': 'power_station_bunker',
        'ccp_base_03': 'guerrilla_supply_cache',
        'ccp_base_04': 'radio_communications_room',
        'checkpoint_south_docks': 'avenue_joffre_market',
        'church_01': 'st_josephs_nanshi',
        'church_02': 'eglise_saint_pierre',
        'church_03': 'holy_trinity_cathedral',
        'church_05': 'zikawei_cathedral',
        'church_06': 'zikawei_mission_chapel',
        'commercial_03': 'sincere_department_store',
        'commercial_04': 'broadway_warehouses',
        'commercial_05': 'wing_on_company',
        'commercial_07': 'sun_sun_store',
        'docks_01': 'customs_house_jetty',
        'docks_02': 'jardine_matheson_wharf',
        'docks_03': 'nanshi_fishermans_pier',
        'docks_05': 'imperial_army_wharf',
        'french_04': 'rue_lafayette',
        'french_05': 'cercle_sportif_francais',
        'french_06': 'plane_tree_avenue',
        'french_07': 'rue_du_consulat_gardens',
        'gmd_office_02': 'intelligence_bureau_annex',
        'gmd_office_04': 'chungking_radio_station',
        'hongkou_07': 'dobun_shoin_academy_gate',
        'hongkou_08': 'wayside_road',
        'hongkou_ruins': 'chapei_ruins',
        'kempeitai_radio_post_hongkou': 'japanese_bathhouse_lane',
        'oldcity_03': 'yuyuan_garden_gate',
        'oldcity_04': 'yuyuan_rear_lanes',
        'oldcity_05': 'city_god_temple',
        'oldcity_06': 'grey_brick_longtang',
        'oldcity_07': 'tortoise_shell_alley',
        'residence_01': 'astor_house_alley',
        'residence_05': 'little_tokyo_row_houses',
        'residence_06': 'seward_road_tenements',
        'school_01': 'dobun_shoin_academy',
        'school_02': 'mctyeire_school',
        'school_03': 'mill_workers_night_school',
        'school_05': 'boone_road_school',
        'venue_bund_river_promenade': 'bund_river_promenade',
        'venue_church_refugee_clinic': 'church_refugee_clinic',
        'venue_commercial_black_market': 'commercial_black_market',
        'venue_commercial_gang_office': 'commercial_gang_office',
        'venue_commercial_market_street': 'umbrella_market',
        'venue_commercial_nightclub_room': 'velvet_nightclub',
        'venue_commercial_printshop': 'commercial_printshop',
        'venue_commercial_watchmaker_shop': 'commercial_watchmaker',
        'venue_docks_cargo_berth': 'docks_cargo_berth',
        'venue_french_bakery': 'french_bakery',
        'venue_french_consulate_front': 'french_consulate_office',
        'venue_french_jazz_cafe': 'french_jazz_cafe',
        'venue_french_newspaper_office': 'french_newspaper_office',
        'venue_hidden_altar_undercroft': 'hidden_altar_undercroft',
        'venue_hongkou_checkpoint_square': 'hongkou_checkpoint_square',
        'venue_hongkou_factory_floor': 'yangshupu_factory_floor',
        'venue_hongkou_field_hospital': 'hongkou_field_hospital',
        'venue_hongkou_refugee_block': 'hongkou_refugee_block',
        'venue_old_city_clinic': 'old_city_clinic',
        'venue_old_city_courtyard_north': 'persimmon_tree_courtyard',
        'venue_old_city_cramped_courtyard': 'laundry_line_courtyard',
        'venue_old_city_market_hub': 'old_city_market_stall',
        'venue_old_city_tea_room': 'old_city_tea_room',
        'venue_school_classroom': 'mctyeire_classroom',
        'venue_shopping_arcade_french': 'glass_arcade',
        'warehouse_02': 'nanshi_tea_duizhan',
        'warehouse_04': 'rue_montauban_silk_huozhan',
        'warehouse_06': 'mission_supply_huozhan',
}

REMOVED_ROOM_FALLBACKS = {
        'bund_02': 'bund_dawn',
        'bund_03': 'bund_dawn',
        'bund_04': 'bund_dawn',
        'bund_06': 'bund_dawn',
        'bund_11': 'bund_dawn',
        'bund_13': 'bund_dawn',
        'bund_14': 'bund_dawn',
        'bund_15': 'bund_dawn',
        'bund_16': 'bund_dawn',
        'bund_17': 'bund_dawn',
        'bund_19': 'bund_dawn',
        'bund_20': 'bund_dawn',
        'bund_21': 'bund_dawn',
        'bund_23': 'bund_dawn',
        'bund_24': 'bund_dawn',
        'bund_25': 'bund_dawn',
        'church_04': 'mctyeire_school',
        'commercial_06': 'checkpoint_soochow_creek',
        'docks_06': 'customs_house_jetty',
        'docks_07': 'customs_house_jetty',
        'gmd_office_01': 'mctyeire_school',
        'gmd_office_03': 'mctyeire_school',
        'gmd_safehouse_french_concession': 'french_concession_safehouse',
        'hongkou_06': 'wayside_road',
        'oldcity_08': 'yuyuan_garden_gate',
        'residence_02': 'bund_dawn',
        'residence_03': 'bund_dawn',
        'residence_04': 'bund_dawn',
        'residence_07': 'bund_dawn',
        'school_04': 'mctyeire_school',
        'venue_bund_safehouse': 'bund_dawn',
        'venue_bund_settlement_bar': 'bund_dawn',
        'venue_bund_tea_house': 'bund_dawn',
        'venue_church_altar_room': 'mctyeire_school',
        'venue_church_confessional_room': 'mctyeire_school',
        'venue_church_parish_room': 'mctyeire_school',
        'venue_church_side_chapel': 'mctyeire_school',
        'venue_commercial_arcade': 'checkpoint_soochow_creek',
        'venue_commercial_arcade_office': 'checkpoint_soochow_creek',
        'venue_commercial_backroom_market': 'checkpoint_soochow_creek',
        'venue_commercial_market_lane': 'checkpoint_soochow_creek',
        'venue_commercial_market_stalls': 'checkpoint_soochow_creek',
        'venue_commercial_nightclub_stage': 'checkpoint_soochow_creek',
        'venue_commercial_noodle_stall': 'checkpoint_soochow_creek',
        'venue_commercial_occupation_office': 'checkpoint_soochow_creek',
        'venue_commercial_office_back': 'checkpoint_soochow_creek',
        'venue_commercial_office_counter': 'checkpoint_soochow_creek',
        'venue_commercial_office_district': 'checkpoint_soochow_creek',
        'venue_commercial_office_front': 'checkpoint_soochow_creek',
        'venue_commercial_printshop_office': 'checkpoint_soochow_creek',
        'venue_commercial_produce_market': 'checkpoint_soochow_creek',
        'venue_commercial_research_office': 'checkpoint_soochow_creek',
        'venue_docks_courier_wharf': 'customs_house_jetty',
        'venue_docks_ferry_quay': 'customs_house_jetty',
        'venue_docks_fishing_quay': 'customs_house_jetty',
        'venue_docks_river_landing': 'customs_house_jetty',
        'venue_french_apartment_flat': 'french_concession_safehouse',
        'venue_french_boulevard': 'french_concession_safehouse',
        'venue_french_boulevard_cafe_edge': 'french_concession_safehouse',
        'venue_french_boulevard_stage': 'french_concession_safehouse',
        'venue_french_cafe_backroom': 'french_concession_safehouse',
        'venue_french_cafe_bar': 'french_concession_safehouse',
        'venue_french_cafe_boulevard': 'french_concession_safehouse',
        'venue_french_cafe_dance_floor': 'french_concession_safehouse',
        'venue_french_cafe_lounge': 'french_concession_safehouse',
        'venue_french_cafe_parlor': 'french_concession_safehouse',
        'venue_french_cafe_stage': 'french_concession_safehouse',
        'venue_french_cafe_table': 'french_concession_safehouse',
        'venue_french_concession_boulevard': 'french_concession_safehouse',
        'venue_french_consulate_back': 'french_concession_safehouse',
        'venue_french_mirror_apartment': 'french_concession_safehouse',
        'venue_french_parish_house': 'french_concession_safehouse',
        'venue_french_tree_lined_boulevard': 'french_concession_safehouse',
        'venue_hidden_boarding_house_hatch': 'wayside_road',
        'venue_hidden_confessional_passage': 'mctyeire_school',
        'venue_hidden_crate_door_cache': 'customs_house_jetty',
        'venue_hidden_french_wardrobe_trapdoor': 'french_concession_safehouse',
        'venue_hidden_kitchen_coal_chute': 'bund_dawn',
        'venue_hidden_mirror_corridor': 'french_concession_safehouse',
        'venue_hidden_old_city_false_wall_chamber': 'yuyuan_garden_gate',
        'venue_hidden_old_city_shrine_floorboard': 'yuyuan_garden_gate',
        'venue_hidden_printshop_bookshelf_compartment': 'checkpoint_soochow_creek',
        'venue_hongkou_checkpoint_cordon': 'wayside_road',
        'venue_hongkou_checkpoint_gate': 'wayside_road',
        'venue_hongkou_checkpoint_lane': 'wayside_road',
        'venue_hongkou_checkpoint_post': 'wayside_road',
        'venue_hongkou_checkpoint_station': 'wayside_road',
        'venue_hongkou_market_stall': 'wayside_road',
        'venue_hongkou_refugee_clinic': 'wayside_road',
        'venue_hongkou_refugee_courtyard': 'wayside_road',
        'venue_hongkou_refugee_house': 'wayside_road',
        'venue_hongkou_refugee_lane': 'wayside_road',
        'venue_hongkou_refugee_shelter': 'wayside_road',
        'venue_hongkou_refugee_shelter_gate': 'wayside_road',
        'venue_hongkou_tenement': 'wayside_road',
        'venue_old_city_back_courtyard': 'yuyuan_garden_gate',
        'venue_old_city_black_market': 'yuyuan_garden_gate',
        'venue_old_city_courtyard_lane': 'yuyuan_garden_gate',
        'venue_old_city_courtyard_room': 'yuyuan_garden_gate',
        'venue_old_city_courtyard_south': 'yuyuan_garden_gate',
        'venue_old_city_inner_courtyard': 'yuyuan_garden_gate',
        'venue_old_city_market_lane': 'yuyuan_garden_gate',
        'venue_old_city_market_street': 'yuyuan_garden_gate',
        'venue_old_city_refugee_courtyard': 'yuyuan_garden_gate',
        'venue_old_city_residential_lane': 'yuyuan_garden_gate',
        'venue_old_city_tea_corner': 'yuyuan_garden_gate',
        'venue_old_city_tea_intersection': 'yuyuan_garden_gate',
        'venue_old_city_tea_lane': 'yuyuan_garden_gate',
        'venue_old_city_tenement_court': 'yuyuan_garden_gate',
        'venue_residential_clergy_house': 'bund_dawn',
        'venue_residential_coal_chute_house': 'bund_dawn',
        'venue_residential_courtyard_house': 'bund_dawn',
        'venue_residential_lane_house': 'bund_dawn',
        'venue_residential_tenant_block': 'bund_dawn',
        'venue_residential_tenant_house': 'bund_dawn',
        'venue_school_dormitory': 'mctyeire_school',
        'venue_school_lecture_room': 'mctyeire_school',
        'venue_warehouse_cargo_bay': 'customs_house_jetty',
        'venue_warehouse_crate_storage': 'customs_house_jetty',
        'venue_warehouse_loading_bay': 'customs_house_jetty',
        'venue_warehouse_provision_store': 'customs_house_jetty',
        'warehouse_01': 'customs_house_jetty',
        'warehouse_05': 'customs_house_jetty',
}


LEGACY_SAFEHOUSE_ALIASES = {
    'venue_old_city_residential_lane': 'laundry_line_courtyard',
    'venue_french_cafe_boulevard': 'plane_tree_avenue',
    'residence_02': 'astor_house_alley',
    'venue_hongkou_refugee_clinic': 'hongkou_field_hospital',
    'venue_church_parish_room': 'church_refugee_clinic',
    'venue_residential_courtyard_house': 'laundry_line_courtyard',
    'venue_residential_tenant_house': 'laundry_line_courtyard',
    'venue_church_side_chapel': 'zikawei_cathedral',
}


def resolve_current_room(room_id):
    if room_id in DIRECT_ROOM_ALIASES:
        return DIRECT_ROOM_ALIASES[room_id]
    if room_id in REMOVED_ROOM_FALLBACKS:
        return REMOVED_ROOM_FALLBACKS[room_id]
    if room_id in _CANONICAL_ROOM_IDS:
        return room_id
    return None


def resolve_discovery_list(room_ids):
    resolved = []
    seen = set()
    for room_id in room_ids:
        canonical = _canonical_identity(room_id)
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        resolved.append(canonical)
    return resolved


def translate_strict(room_id):
    if room_id in DIRECT_ROOM_ALIASES:
        return DIRECT_ROOM_ALIASES[room_id]
    if room_id in _CANONICAL_ROOM_IDS:
        return room_id
    return None


def resolve_override_keys(overrides):
    resolved = {}
    for key in sorted(overrides):
        canonical = _canonical_identity(key)
        if canonical is None or canonical in resolved:
            continue
        resolved[canonical] = overrides[key]
    return resolved


def resolve_safehouse(room_id, is_valid_safehouse):
    if not room_id:
        return ''
    canonical = _canonical_identity(room_id)
    if canonical is None:
        canonical = LEGACY_SAFEHOUSE_ALIASES.get(room_id)
    if canonical is None:
        return ''
    if is_valid_safehouse is None or is_valid_safehouse(canonical):
        return canonical
    return ''


def _canonical_identity(room_id):
    if room_id in REMOVED_ROOM_FALLBACKS:
        return None
    if room_id in DIRECT_ROOM_ALIASES:
        return DIRECT_ROOM_ALIASES[room_id]
    if room_id in _CANONICAL_ROOM_IDS:
        return room_id
    return None


_CANONICAL_ROOM_IDS = frozenset(DISTRICT_OF)
