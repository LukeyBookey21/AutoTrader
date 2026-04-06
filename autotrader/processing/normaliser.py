"""Spec normalisation - maps inconsistent feature names to canonical keys."""

import logging
import re

from autotrader.storage.database import (
    get_all_listings_for_scoring,
    update_listing_normalised_features,
)

logger = logging.getLogger(__name__)

# Canonical feature keys mapped to patterns that identify them.
# Each pattern is a list of regex patterns (case-insensitive) that match
# different ways AutoTrader listings describe the same feature.
FEATURE_PATTERNS: dict[str, list[str]] = {
    # Roof features
    "panoramic_roof": [
        r"panoramic\s*(sun)?roof",
        r"panoramic\s*glass\s*roof",
        r"glass\s*panoramic\s*roof",
    ],
    "sunroof": [
        r"(?<!panoramic\s)sun\s*roof",
        r"electric\s*sun\s*roof",
        r"tilt.+slide\s*sun\s*roof",
    ],
    # Heated seats
    "heated_seats_front": [
        r"heated\s*(front\s*)?seats?(?!\s*rear)",
        r"front\s*seat\s*heat",
        r"heated\s*front\s*seats?",
        r"seat\s*heat.*front",
    ],
    "heated_seats_rear": [
        r"heated\s*rear\s*seats?",
        r"rear\s*(heated\s*)?seats?\s*heat",
    ],
    "ventilated_seats": [
        r"ventilated\s*seats?",
        r"cooled\s*seats?",
        r"seat\s*ventilat",
        r"air\s*conditioned\s*seats?",
    ],
    # Interior
    "leather_interior": [
        r"leather\s*(interior|upholster|seats?|trim)",
        r"full\s*leather",
        r"nappa\s*leather",
        r"merino\s*leather",
        r"windsor\s*leather",
        r"vernasca\s*leather",
        r"dakota\s*leather",
        r"semi[\s-]*leather",
    ],
    "heated_steering_wheel": [
        r"heated\s*steering\s*wheel",
        r"steering\s*wheel\s*heat",
    ],
    "ambient_lighting": [
        r"ambient\s*light",
        r"interior\s*ambient\s*light",
        r"mood\s*light",
    ],
    # Driving assistance
    "adaptive_cruise_control": [
        r"adaptive\s*cruise\s*control",
        r"acc\b",
        r"active\s*cruise\s*control",
        r"radar\s*cruise",
        r"intelligent\s*cruise",
    ],
    "lane_assist": [
        r"lane\s*(keep|departure|assist)",
        r"lane\s*warning",
    ],
    "blind_spot_monitoring": [
        r"blind\s*spot\s*(monitor|detect|assist|warn)",
        r"bsm\b",
        r"side\s*assist",
    ],
    "auto_parking": [
        r"auto(matic)?\s*park",
        r"park\s*assist",
        r"self[\s-]*park",
    ],
    "heads_up_display": [
        r"head(s)?[\s-]*up\s*display",
        r"\bhud\b",
    ],
    # Parking
    "parking_camera": [
        r"(rear|reverse|reversing|backup)\s*(view)?\s*camera",
        r"parking\s*camera",
        r"rear\s*camera",
    ],
    "360_camera": [
        r"360\s*(degree)?\s*camera",
        r"surround\s*(view)?\s*camera",
        r"bird('?s)?\s*eye\s*(view)?\s*camera",
        r"all[\s-]*round\s*camera",
    ],
    "parking_sensors_front_rear": [
        r"front\s*(and|&)\s*rear\s*parking\s*sensors?",
        r"parking\s*sensors?\s*front\s*(and|&)\s*rear",
        r"f(ront)?\s*/?\s*r(ear)?\s*park(ing)?\s*sens",
    ],
    "parking_sensors_rear": [
        r"\brear\s*parking\s*sensors?",
        r"parking\s*sensors?\s*rear",
        r"reverse\s*parking\s*sensors?",
    ],
    # Technology
    "apple_carplay": [
        r"apple\s*car\s*play",
        r"carplay",
    ],
    "android_auto": [
        r"android\s*auto",
    ],
    "wireless_charging": [
        r"wireless\s*charg",
        r"inductive\s*charg",
        r"qi\s*charg",
    ],
    "digital_cockpit": [
        r"digital\s*(cockpit|instrument|dash)",
        r"virtual\s*cockpit",
        r"digital\s*driver\s*display",
        r"live\s*cockpit",
    ],
    "sat_nav": [
        r"sat\s*nav",
        r"satellite\s*nav",
        r"navigation\s*system",
        r"built[\s-]*in\s*nav",
    ],
    "keyless_entry": [
        r"keyless\s*(entry|go|start|access)",
        r"comfort\s*access",
        r"smart\s*key",
    ],
    # Audio
    "harman_kardon_audio": [
        r"harman\s*/?\s*kardon",
    ],
    "bose_audio": [
        r"bose\s*(sound|audio|speaker|surround)?",
    ],
    "bang_olufsen_audio": [
        r"bang\s*(&|and)?\s*olufsen",
        r"b(&|and)?o\s*(sound|audio|speaker)?",
    ],
    "meridian_audio": [
        r"meridian\s*(sound|audio|speaker|surround)?",
    ],
    # Exterior
    "matrix_led_headlights": [
        r"matrix\s*led",
        r"led\s*matrix",
        r"pixel\s*led",
        r"intellilux\s*led",
        r"adaptive\s*led",
    ],
    "electric_tailgate": [
        r"electric\s*(tailgate|boot|trunk)",
        r"power\s*(tailgate|boot|trunk)",
        r"auto(matic)?\s*(tailgate|boot|trunk)",
        r"hands[\s-]*free\s*(tailgate|boot|trunk)",
    ],
    # Drivetrain
    "four_wheel_drive": [
        r"4(wd|x4|\s*wheel\s*drive)",
        r"all[\s-]*wheel\s*drive",
        r"\bawd\b",
        r"quattro",
        r"xdrive",
        r"4matic",
        r"4motion",
    ],
    "air_suspension": [
        r"air\s*suspension",
        r"adaptive\s*air\s*suspension",
        r"pneumatic\s*suspension",
    ],
}

# Pre-compile all patterns
_COMPILED_PATTERNS: dict[str, list[re.Pattern]] = {
    key: [re.compile(p, re.IGNORECASE) for p in patterns]
    for key, patterns in FEATURE_PATTERNS.items()
}


def normalise_feature(feature_text: str) -> list[str]:
    """Map a raw feature string to zero or more canonical feature keys.

    A single feature string might match multiple canonical features
    (e.g. "Front and rear parking sensors with camera" matches both
    parking_sensors_front_rear and parking_camera).
    """
    matches = []
    cleaned = feature_text.strip()
    if not cleaned:
        return matches

    for canonical_key, patterns in _COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(cleaned):
                matches.append(canonical_key)
                break  # Found a match for this key, move to next

    return matches


def normalise_features(raw_features: list[str]) -> list[str]:
    """Normalise a list of raw feature strings to canonical keys.

    Returns a deduplicated, sorted list of canonical feature keys.
    """
    all_keys = set()
    for feature in raw_features:
        keys = normalise_feature(feature)
        all_keys.update(keys)

    # Handle precedence: if both front+rear and rear-only sensors found,
    # keep only front+rear
    if "parking_sensors_front_rear" in all_keys:
        all_keys.discard("parking_sensors_rear")

    # If panoramic roof found, don't also count sunroof
    if "panoramic_roof" in all_keys:
        all_keys.discard("sunroof")

    return sorted(all_keys)


def mine_features_from_description(description: str) -> list[str]:
    """Extract feature mentions from free-text seller descriptions.

    Scans the description for references to canonical features that weren't
    captured in the structured features list. Returns canonical keys found.
    """
    if not description or not description.strip():
        return []

    found = set()
    for canonical_key, patterns in _COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(description):
                found.add(canonical_key)
                break

    return sorted(found)


def normalise_all_listings(make: str | None = None, model: str | None = None):
    """Normalise features for all listings in the database.

    Combines structured features, description text mining, and trim-level
    inference to produce the most complete feature set possible.

    Args:
        make: Optional filter by make.
        model: Optional filter by model.
    """
    from autotrader.processing.trim_features import infer_trim_features

    listings = get_all_listings_for_scoring(make, model)
    updated = 0

    for listing in listings:
        raw = listing.get("features_raw", [])

        # Start with structured feature normalisation
        normalised = set(normalise_features(raw)) if raw else set()

        # Text mining: extract features from description
        description = listing.get("description", "")
        if description:
            mined = mine_features_from_description(description)
            normalised.update(mined)

        # Trim-level inference: infer standard features from trim/variant
        inferred = infer_trim_features(
            make=listing.get("make", ""),
            model=listing.get("model", ""),
            variant=listing.get("variant", ""),
            title=listing.get("title", ""),
            year=listing.get("year"),
        )
        normalised.update(inferred)

        # Apply precedence rules
        if "parking_sensors_front_rear" in normalised:
            normalised.discard("parking_sensors_rear")
        if "panoramic_roof" in normalised:
            normalised.discard("sunroof")

        final = sorted(normalised)
        update_listing_normalised_features(listing["id"], final)
        updated += 1

    logger.info(f"Normalised features for {updated} listings")
    return updated


# Human-readable names for display in the UI
FEATURE_DISPLAY_NAMES: dict[str, str] = {
    "panoramic_roof": "Panoramic Roof",
    "sunroof": "Sunroof",
    "heated_seats_front": "Heated Front Seats",
    "heated_seats_rear": "Heated Rear Seats",
    "ventilated_seats": "Ventilated Seats",
    "leather_interior": "Leather Interior",
    "heated_steering_wheel": "Heated Steering Wheel",
    "ambient_lighting": "Ambient Lighting",
    "adaptive_cruise_control": "Adaptive Cruise Control",
    "lane_assist": "Lane Assist",
    "blind_spot_monitoring": "Blind Spot Monitoring",
    "auto_parking": "Auto Parking",
    "heads_up_display": "Heads-Up Display",
    "parking_camera": "Parking Camera",
    "360_camera": "360 Camera",
    "parking_sensors_front_rear": "Front & Rear Parking Sensors",
    "parking_sensors_rear": "Rear Parking Sensors",
    "apple_carplay": "Apple CarPlay",
    "android_auto": "Android Auto",
    "wireless_charging": "Wireless Charging",
    "digital_cockpit": "Digital Cockpit",
    "sat_nav": "Sat Nav",
    "keyless_entry": "Keyless Entry",
    "harman_kardon_audio": "Harman Kardon Audio",
    "bose_audio": "Bose Audio",
    "bang_olufsen_audio": "Bang & Olufsen Audio",
    "meridian_audio": "Meridian Audio",
    "matrix_led_headlights": "Matrix LED Headlights",
    "electric_tailgate": "Electric Tailgate",
    "four_wheel_drive": "Four-Wheel Drive",
    "air_suspension": "Air Suspension",
}
