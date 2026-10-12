"""
Emoji-to-inline-SVG mapping for slide_engine post-processing.

Provides small vector icons that replace emoji characters so PDF/PPTX exports
look crisp without depending on system emoji fonts.
"""

import re
import unicodedata

try:
    import emoji as _emoji_pkg
except Exception:  # pragma: no cover
    _emoji_pkg = None


_SVG_TEMPLATE = (
    '<svg class="ge-inline-icon" width="16" height="16" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'style="display:inline-block;vertical-align:middle;margin:0 4px">{}</svg>'
)


_ICON_PATHS = {
    'arrow-up': '<path d="M12 19V5M5 12l7-7 7 7"/>',
    'arrow-down': '<path d="M12 5v14M5 12l7 7 7-7"/>',
    'arrow-left': '<path d="M19 12H5m7 7l-7-7 7-7"/>',
    'arrow-right': '<path d="M5 12h14m-7-7l7 7-7 7"/>',
    'bell': '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    'bicycle': '<circle cx="6" cy="18" r="3"/><circle cx="18" cy="18" r="3"/><path d="M6 18l6-9 4 4"/><path d="M16 13l4 5"/>',
    'book': '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    'building': '<path d="M3 21h18M4 21V7l8-4 8 4v14M9 21v-6h6v6"/>',
    'bus': '<rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    'calendar': '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    'camera': '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    'car': '<path d="M4 16h16a2 2 0 0 0 2-2v-3l-2-3H6L4 11v3a2 2 0 0 0 2 2z"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/>',
    'chart': '<path d="M3 17l6-6 4 4 8-10"/><path d="M21 7h-2V5"/>',
    'chart-bar': '<path d="M3 20h18"/><path d="M6 20V10M12 20V4M18 20v-6"/>',
    'check': '<path d="M20 6L9 17l-5-5"/>',
    'circle-filled': '<circle cx="12" cy="12" r="10" stroke="none" fill="currentColor"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    'close': '<path d="M18 6L6 18M6 6l12 12"/>',
    'cloud': '<path d="M18 20H6a4 4 0 0 1 0-8 5 5 0 0 1 9.5-1A4 4 0 0 1 18 20z"/>',
    'diamond-filled': '<path d="M12 2l10 10-10 10L2 12z" stroke="none" fill="currentColor"/>',
    'fire': '<path d="M12 22c5-3 7-8 4-13 0 2-1 4-3 5-1-3-1-6 3-8-5 2-8 7-6 12 1-2 3-3.5 4-4-1 4 0 7 3 7z" stroke="none" fill="currentColor"/>',
    'flag': '<polygon points="4,4 20,10 4,16"/><line x1="4" y1="4" x2="4" y2="22"/>',
    'food': '<circle cx="12" cy="14" r="7"/><path d="M12 7V4"/>',
    'gem': '<path d="M6 3h12l4 6-10 12L2 9l4-6z"/><path d="M12 21V9"/>',
    'globe': '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    'heart-filled': '<path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" stroke="none" fill="currentColor"/>',
    'home': '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    'info': '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    'key': '<circle cx="7" cy="14" r="4"/><path d="M10 11l7-7"/><path d="M20 4h-3v3"/>',
    'leaf': '<path d="M12 22c5-4 8-10 8-16 0-3-1-4-2-4s-3 1-6 4c-3 3-5 7-6 12-.5 2 3 4 6 4z"/><path d="M12 6v16"/>',
    'lightbulb': '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-7 7c0 3 2 5.5 4 7v2h6v-2c2-1.5 4-4 4-7a7 7 0 0 0-7-7z"/>',
    'location': '<path d="M12 22s-7-7.5-7-13a7 7 0 0 1 14 0c0 5.5-7 13-7 13z"/><circle cx="12" cy="9" r="2.5"/>',
    'lock': '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M12 16v-2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    'mail': '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    'map': '<path d="M1 6l6-3 8 4 8-4v15l-8 4-8-4-6 3V6z"/><path d="M15 3v15"/><path d="M9 7v15"/>',
    'medal': '<circle cx="12" cy="9" r="6"/><path d="M7 14l-2 8M17 14l2 8"/><path d="M12 15v7"/>',
    'microphone': '<path d="M12 1a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>',
    'minus': '<path d="M5 12h14"/>',
    'money': '<circle cx="8" cy="14" r="5"/><circle cx="16" cy="14" r="5"/><circle cx="12" cy="10" r="5"/>',
    'mosque': '<path d="M4 22h16M6 22V10c0-2 2-3 4-3M14 22V10c0-2 2-3 4-3"/><path d="M12 4a5 5 0 0 0-5 5h10a5 5 0 0 0-5-5z"/>',
    'hospital': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 8v8M8 12h8"/>',
    'school': '<path d="M12 3L2 9h20L12 3z"/><path d="M4 9v11h16V9"/><path d="M10 20v-6h4v6"/>',
    'anchor': '<circle cx="12" cy="13" r="4"/><path d="M12 9V2"/><path d="M4 13h16"/>',
    'download': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    'pencil': '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
    'paperclip': '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    'clipboard': '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>',
    'scissors': '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.12 15.88M14 12l6 8"/>',
    'trash': '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    'link': '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    'folder': '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    'file': '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    'monitor': '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    'moon': '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    'music': '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    'people': '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><circle cx="17" cy="7" r="4"/>',
    'phone': '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.3 12.3 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.3 12.3 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    'plane': '<path d="M22 12h-6l-6-9h-4l2 9H2v4h6l-2 9h4l6-9h6z"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'question': '<circle cx="12" cy="12" r="10"/><path d="M12 16h.01"/><path d="M9 10a3 3 0 0 1 3-3 3 3 0 0 1 3 3c0 1.5-1 2-2 3"/>',
    'road': '<path d="M3 21l5-18M21 21l-5-18"/><line x1="12" y1="3" x2="12" y2="21" stroke-dasharray="3 3"/>',
    'search': '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
    'shield': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    'smartphone': '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M12 18h.01"/>',
    'sport': '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M3 12h18"/>',
    'square-filled': '<rect x="3" y="3" width="18" height="18" rx="2" stroke="none" fill="currentColor"/>',
    'star-filled': '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" stroke="none" fill="currentColor"/>',
    'sun': '<circle cx="12" cy="12" r="5"/><path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>',
    'train': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16"/><circle cx="8" cy="17" r="2"/><circle cx="16" cy="17" r="2"/>',
    'tree': '<path d="M12 2L4 16h16L12 2z"/><path d="M12 14v8"/>',
    'trophy': '<path d="M7 5h10v8a5 5 0 0 1-10 0V5z"/><path d="M4 5h3M17 5h3"/><path d="M12 13v6M9 22h6"/>',
    'video': '<rect x="1" y="5" width="15" height="14" rx="2"/><path d="M23 7l-7 5 7 5V7z"/>',
    'warning': '<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5M12 17h.01"/>',
    'water': '<path d="M2 10c2.5-2 5-2 7 0s5 2 7 0 5-2 7 0"/><path d="M2 16c2.5-2 5-2 7 0s5 2 7 0 5-2 7 0"/>',
    'walk': '<circle cx="12" cy="5" r="2"/><path d="M8 22l4-7 4 7"/><path d="M12 15l-3-4 5-2"/>',
}


# Keyword patterns for emoji short names. More specific patterns must come first.
_EMOJI_KEYWORDS = [
    # Arrows — handled first because many direction names also appear in other emojis.
    (('arrow_up', 'arrow_heading_up', 'point_up', 'thumb_up', 'thumbsup', 'arrow_double_up'), 'arrow-up'),
    (('arrow_down', 'arrow_heading_down', 'point_down', 'thumb_down', 'thumbsdown', 'arrow_double_down'), 'arrow-down'),
    (('arrow_left', 'arrow_backward', 'point_left', 'arrow_double_left'), 'arrow-left'),
    (('arrow_right', 'arrow_forward', 'point_right', 'arrow_double_right'), 'arrow-right'),

    # Check / cross / math symbols
    (('white_check_mark', 'heavy_check_mark', 'ballot_box_with_check', 'heavy_check', 'check_mark'), 'check'),
    (('cross_mark', 'heavy_multiplication_x', 'negative_squared_cross_mark', 'no_entry', 'prohibited', 'no_bicycles', 'no_smoking', 'no_mobile_phones'), 'close'),
    (('heavy_plus_sign', 'plus'), 'plus'),
    (('heavy_minus_sign', 'minus'), 'minus'),
    (('question', 'grey_question'), 'question'),
    (('exclamation', 'heavy_exclamation_mark', 'warning', 'stop_sign'), 'warning'),
    (('information', 'information_source'), 'info'),

    # Hearts and stars
    (('broken_heart',), 'heart-filled'),
    (('heart', 'love', 'kiss', 'lips', 'two_hearts', 'sparkling_heart', 'heartpulse'), 'heart-filled'),
    (('star', 'glowing_star', 'sparkles', 'dizzy', 'boom', 'collision'), 'star-filled'),

    # Money / finance
    (('money_bag', 'money_with_wings', 'money_mouth', 'yen', 'euro', 'pound', 'dollar', 'coin', 'credit_card', 'receipt'), 'money'),
    (('gem', 'gem_stone', 'ring'), 'gem'),
    (('diamond', 'diamond_shape'), 'diamond-filled'),

    # Buildings / places
    (('house_with_garden', 'house', 'home', 'hut'), 'home'),
    (('hospital',), 'hospital'),
    (('school',), 'school'),
    (('mosque', 'church', 'synagogue', 'temple', 'kaaba', 'shinto', 'hindu', 'wat', 'worship'), 'mosque'),
    (('office', 'hotel', 'factory', 'bank', 'department_store', 'convenience_store', 'post_office', 'japanese_post_office', 'european_post_office', 'building_construction', 'bricks', 'derelict_house', 'castle', 'stadium', 'classical_building'), 'building'),

    # Location / maps
    (('round_pushpin', 'pushpin', 'location'), 'location'),
    (('world_map', 'map'), 'map'),
    (('globe', 'earth', 'world'), 'globe'),
    (('rainbow_flag', 'white_flag', 'black_flag', 'checkered_flag', 'pirate_flag', 'triangular_flag'), 'flag'),
    (('anchor',), 'anchor'),

    # Transport
    (('motorway', 'railway_track'), 'road'),
    (('train', 'railway', 'metro', 'monorail', 'light_rail', 'mountain_railway', 'tram', 'aerial_tramway', 'suspension_railway', 'station'), 'train'),
    (('airplane', 'small_airplane', 'airport', 'airplane_departure', 'airplane_arriving', 'helicopter', 'rocket'), 'plane'),
    (('ship', 'cruise_ship', 'ferry', 'motor_boat', 'sailboat', 'speedboat'), 'plane'),
    (('car', 'red_car', 'oncoming_automobile', 'automobile', 'taxi', 'oncoming_taxi', 'minibus', 'trolleybus', 'pickup_truck', 'fire_engine', 'police_car', 'ambulance', 'truck', 'articulated_lorry'), 'car'),
    (('bus', 'trolleybus'), 'bus'),
    (('bicycle', 'bike'), 'bicycle'),
    (('walking', 'running', 'dancer', 'surfing', 'swimming', 'skier', 'snowboarder', 'golfer', 'horse_racing'), 'walk'),

    # Nature / weather / elements
    (('fire', 'flame', 'sparkler', 'fireworks'), 'fire'),
    (('tree', 'palm_tree', 'cactus', 'seedling', 'herb', 'four_leaf_clover', 'maple_leaf', 'fallen_leaf', 'leaves', 'leafy_green', 'evergreen_tree', 'deciduous_tree', 'wood'), 'tree'),
    (('rose', 'tulip', 'sunflower', 'blossom', 'hibiscus', 'cherry_blossom', 'bouquet', 'white_flower', 'lotus', 'wilted_flower'), 'leaf'),
    (('water_wave', 'ocean', 'beach', 'droplet', 'sweat_drops', 'pool', 'swimmer', 'umbrella_with_rain', 'umbrella'), 'water'),
    (('cloud_with_rain', 'cloud_with_snow', 'cloud_with_lightning', 'cloud_with_tornado', 'fog', 'cloud', 'partly_sunny', 'sun_behind_cloud'), 'cloud'),
    (('sun', 'sunny', 'sun_with_face', 'sunrise', 'sunset', 'city_sunrise', 'city_sunset'), 'sun'),
    (('moon', 'crescent_moon', 'full_moon', 'new_moon', 'first_quarter_moon', 'last_quarter_moon', 'waxing_moon', 'waning_moon'), 'moon'),

    # Charts / analytics
    (('chart_with_upwards_trend', 'chart_with_downwards_trend'), 'chart'),
    (('bar_chart', 'chart'), 'chart-bar'),

    # Communication / media
    (('mobile_phone', 'iphone'), 'smartphone'),
    (('telephone_receiver', 'telephone', 'phone', 'calling'), 'phone'),
    (('envelope', 'e-mail', 'incoming_envelope', 'outbox_tray', 'inbox_tray'), 'mail'),
    (('camera', 'camera_with_flash'), 'camera'),
    (('video_camera', 'movie_camera', 'film', 'clapper'), 'video'),
    (('microphone', 'studio_microphone'), 'microphone'),
    (('musical_note', 'notes', 'headphone', 'radio', 'sound', 'speaker'), 'music'),
    (('television', 'tv'), 'monitor'),
    (('laptop', 'computer', 'desktop_computer', 'keyboard', 'mouse', 'trackball', 'joystick', 'printer', 'fax'), 'monitor'),

    # Office / tools
    (('book', 'notebook', 'closed_book', 'open_book', 'green_book', 'blue_book', 'orange_book', 'books', 'scroll', 'newspaper'), 'book'),
    (('bookmark',), 'book'),
    (('calendar', 'date', 'tear-off_calendar'), 'calendar'),
    (('clock', 'alarm_clock', 'timer', 'stopwatch', 'watch'), 'clock'),
    (('hourglass',), 'hourglass'),
    (('bell',), 'bell'),
    (('light_bulb', 'bulb', 'flashlight', 'candle'), 'lightbulb'),
    (('battery', 'electric_plug', 'electric'), 'monitor'),
    (('gear', 'tools', 'toolbox', 'wrench', 'hammer', 'axe', 'screwdriver', 'nut_and_bolt'), 'monitor'),
    (('pencil', 'pen', 'paintbrush', 'crayon', 'memo'), 'pencil'),
    (('scissors',), 'scissors'),
    (('paperclip', 'linked_paperclips'), 'paperclip'),
    (('clipboard',), 'clipboard'),
    (('folder', 'file_folder', 'open_file_folder'), 'folder'),
    (('file', 'page', 'page_with_curl', 'page_facing_up', 'rolled_up_newspaper'), 'file'),
    (('trash', 'wastebasket'), 'trash'),
    (('search', 'magnifying'), 'search'),
    (('link', 'chains'), 'link'),
    (('download', 'upload'), 'download'),

    # Awards / security
    (('trophy', 'rosette'), 'trophy'),
    (('medal', '1st_place_medal', '2nd_place_medal', '3rd_place_medal'), 'medal'),
    (('crown',), 'crown'),
    (('shield',), 'shield'),
    (('lock', 'closed_lock_with_key', 'unlock', 'key'), 'lock'),

    # People / body / food / sport fallback
    (('handshake', 'raised_hand', 'wave', 'clap', 'ok_hand', 'vulcan', 'crossed_fingers', 'pinching_hand', 'fist', 'punch', 'muscle', 'leg', 'foot'), 'handshake'),
    (('person', 'people', 'family', 'couple', 'man', 'woman', 'child', 'baby', 'older', 'adult', 'dancers'), 'people'),
    (('food', 'fruit', 'drink', 'coffee', 'tea', 'beer', 'wine', 'cocktail', 'pizza', 'hamburger', 'sushi', 'bread', 'cheese', 'meat', 'egg', 'fish', 'shrimp', 'apple', 'banana', 'grape', 'cake', 'ice_cream', 'croissant', 'pancake', 'hotdog', 'sandwich', 'taco', 'burrito', 'curry', 'ramen', 'spaghetti', 'soup', 'donut', 'cookie', 'candy', 'popcorn', 'avocado', 'broccoli'), 'food'),
    (('sport', 'ball', 'tennis', 'football', 'soccer', 'basketball', 'baseball', 'volleyball', 'rugby', 'cricket', 'golf', 'boxing', 'gymnastics', 'fencing', 'badminton'), 'sport'),
]


_FLAG_KEYWORDS = (
    'white_flag', 'black_flag', 'checkered_flag', 'rainbow_flag', 'pirate_flag',
    'triangular_flag_on_post', 'waving_white_flag', 'waving_black_flag',
)


def _icon_key_for_emoji(emoji_char):
    """Map a single emoji character to an icon key."""
    if _emoji_pkg is not None:
        try:
            short = _emoji_pkg.demojize(emoji_char, language='en').strip(':')
            # Remove skin-tone suffix if present, e.g. thumbs_up_medium_skin_tone -> thumbs_up
            if '_skin_tone' in short:
                short = short.split('_skin_tone')[0]
            # Country / region flags use the flag_ prefix
            if short.startswith('flag_'):
                return 'flag'
            # Explicit flag names
            for kw in _FLAG_KEYWORDS:
                if kw in short:
                    return 'flag'
            for patterns, key in _EMOJI_KEYWORDS:
                for pat in patterns:
                    if pat in short:
                        return key
        except Exception:
            pass

    # Fallback: try to guess from unicode name
    try:
        name = unicodedata.name(emoji_char, '').lower().replace(' ', '_')
        for patterns, key in _EMOJI_KEYWORDS:
            for pat in patterns:
                if pat in name:
                    return key
    except Exception:
        pass

    # Neutral fallback: a small filled circle, never a checkmark.
    return 'circle-filled'


def get_emoji_svg(emoji_str, size=16):
    """Return inline SVG markup for an emoji string (may contain multiple emojis)."""
    if _emoji_pkg is not None:
        try:
            items = _emoji_pkg.emoji_list(emoji_str)
        except Exception:
            items = []
    else:
        items = []

    if not items:
        # fallback: treat the whole string as one emoji
        inner = _ICON_PATHS.get('circle-filled', '')
        return _SVG_TEMPLATE.format(inner)

    parts = []
    for info in items:
        e = info['emoji']
        key = _icon_key_for_emoji(e)
        inner = _ICON_PATHS.get(key) or _ICON_PATHS.get('circle-filled', '')
        parts.append(_SVG_TEMPLATE.format(inner))
    return ''.join(parts)


def _svg_repl(emoji_char, _data=None):
    return get_emoji_svg(emoji_char)


def replace_emojis_in_text(text):
    """Replace every emoji inside a plain text segment with an inline SVG."""
    if not text or _emoji_pkg is None:
        return text
    try:
        return _emoji_pkg.replace_emoji(text, _svg_repl)
    except Exception:
        return text
