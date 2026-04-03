"""Trim-level feature inference - infers standard features from trim/variant names."""

import logging
import re

logger = logging.getLogger(__name__)

# Known trim levels and their standard features.
# This maps (make_pattern, model_pattern, trim_pattern) -> list of canonical feature keys.
# Features listed here are standard equipment for that trim, so if the listing
# mentions the trim but has no feature list, we can still infer these.
TRIM_FEATURES: list[tuple[str, str, str, list[str]]] = [
    # BMW
    (r"bmw", r"", r"m\s*sport", [
        "leather_interior", "sat_nav", "parking_sensors_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
    ]),
    (r"bmw", r"", r"m\s*sport\s*(pro|plus)", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "adaptive_cruise_control", "harman_kardon_audio", "ambient_lighting",
        "heated_seats_front", "heads_up_display",
    ]),
    (r"bmw", r"", r"(m\d{2,3}|m\s*performance)", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "adaptive_cruise_control", "harman_kardon_audio", "ambient_lighting",
        "heated_seats_front", "heads_up_display", "heated_steering_wheel",
    ]),
    (r"bmw", r"", r"se\b", [
        "sat_nav", "parking_sensors_rear", "apple_carplay", "android_auto",
    ]),
    (r"bmw", r"(x3|x4|x5|x6|x7)", r"xdrive", [
        "four_wheel_drive",
    ]),
    # Audi
    (r"audi", r"", r"s\s*line", [
        "leather_interior", "sat_nav", "parking_sensors_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
    ]),
    (r"audi", r"", r"black\s*edition", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "bang_olufsen_audio", "matrix_led_headlights",
    ]),
    (r"audi", r"", r"vorsprung", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "bang_olufsen_audio", "matrix_led_headlights", "panoramic_roof",
        "adaptive_cruise_control", "heads_up_display", "heated_seats_front",
        "360_camera", "air_suspension",
    ]),
    (r"audi", r"", r"(sport|technik)", [
        "sat_nav", "parking_sensors_rear", "apple_carplay", "android_auto",
    ]),
    (r"audi", r"(q[3-8]|a[4-8]|e-tron)", r"quattro", [
        "four_wheel_drive",
    ]),
    # Mercedes
    (r"mercedes", r"", r"amg\s*line", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "ambient_lighting", "keyless_entry",
    ]),
    (r"mercedes", r"", r"amg\s*line\s*premium(\s*plus)?", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "ambient_lighting", "keyless_entry", "panoramic_roof",
        "heated_seats_front", "360_camera", "heads_up_display",
        "electric_tailgate",
    ]),
    (r"mercedes", r"", r"(amg\s+[a-z]*\d{2,3}|amg\s*gt)", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "ambient_lighting", "keyless_entry", "adaptive_cruise_control",
        "heated_seats_front", "heated_steering_wheel",
    ]),
    (r"mercedes", r"", r"sport\b", [
        "sat_nav", "parking_sensors_rear", "apple_carplay", "android_auto",
    ]),
    (r"mercedes", r"", r"4matic", [
        "four_wheel_drive",
    ]),
    # Volkswagen
    (r"volkswagen|vw", r"", r"r[\s-]*line", [
        "sat_nav", "parking_sensors_front_rear", "digital_cockpit",
        "apple_carplay", "android_auto", "ambient_lighting",
    ]),
    (r"volkswagen|vw", r"", r"gtd|gti|gte", [
        "sat_nav", "parking_sensors_front_rear", "digital_cockpit",
        "apple_carplay", "android_auto", "adaptive_cruise_control",
        "heated_seats_front", "keyless_entry",
    ]),
    (r"volkswagen|vw", r"golf\s*r\b", r"", [
        "sat_nav", "parking_sensors_front_rear", "digital_cockpit",
        "apple_carplay", "android_auto", "adaptive_cruise_control",
        "heated_seats_front", "keyless_entry", "four_wheel_drive",
        "leather_interior",
    ]),
    (r"volkswagen|vw", r"", r"sel\b", [
        "sat_nav", "parking_sensors_rear", "apple_carplay", "android_auto",
    ]),
    # Volvo
    (r"volvo", r"", r"r[\s-]*design", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "heated_seats_front", "heated_steering_wheel",
    ]),
    (r"volvo", r"", r"inscription", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "digital_cockpit", "apple_carplay", "android_auto",
        "heated_seats_front", "heated_steering_wheel", "adaptive_cruise_control",
        "blind_spot_monitoring", "ambient_lighting",
    ]),
    # Land Rover / Range Rover
    (r"land\s*rover|range\s*rover", r"", r"hse", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "parking_camera", "digital_cockpit", "apple_carplay", "android_auto",
        "heated_seats_front", "heated_steering_wheel", "adaptive_cruise_control",
        "keyless_entry", "electric_tailgate", "four_wheel_drive",
        "meridian_audio", "blind_spot_monitoring",
    ]),
    (r"land\s*rover|range\s*rover", r"", r"autobiography", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "360_camera", "digital_cockpit", "apple_carplay", "android_auto",
        "heated_seats_front", "heated_seats_rear", "ventilated_seats",
        "heated_steering_wheel", "adaptive_cruise_control",
        "keyless_entry", "electric_tailgate", "four_wheel_drive",
        "meridian_audio", "blind_spot_monitoring", "panoramic_roof",
        "heads_up_display", "air_suspension",
    ]),
    (r"land\s*rover|range\s*rover", r"", r"(se|s)\b", [
        "sat_nav", "parking_sensors_rear", "parking_camera",
        "apple_carplay", "android_auto", "four_wheel_drive",
    ]),
    # Jaguar
    (r"jaguar", r"", r"r[\s-]*sport", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "parking_camera", "digital_cockpit", "apple_carplay", "android_auto",
        "heated_seats_front", "keyless_entry", "meridian_audio",
    ]),
    # Ford
    (r"ford", r"", r"st[\s-]*line(\s*x)?", [
        "sat_nav", "parking_sensors_rear", "apple_carplay", "android_auto",
    ]),
    (r"ford", r"", r"vignale", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "parking_camera", "apple_carplay", "android_auto",
        "heated_seats_front", "heated_steering_wheel", "keyless_entry",
        "electric_tailgate", "bang_olufsen_audio",
    ]),
    # Hyundai / Kia
    (r"hyundai|kia", r"", r"premium(\s*se)?", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "parking_camera", "apple_carplay", "android_auto",
        "heated_seats_front", "heated_steering_wheel", "keyless_entry",
        "blind_spot_monitoring",
    ]),
    (r"hyundai|kia", r"", r"ultimate", [
        "leather_interior", "sat_nav", "parking_sensors_front_rear",
        "360_camera", "apple_carplay", "android_auto",
        "heated_seats_front", "ventilated_seats",
        "heated_steering_wheel", "keyless_entry",
        "blind_spot_monitoring", "heads_up_display",
        "panoramic_roof", "electric_tailgate",
    ]),
    # Tesla
    (r"tesla", r"", r"", [
        "sat_nav", "digital_cockpit", "adaptive_cruise_control",
        "parking_camera", "parking_sensors_front_rear",
        "heated_seats_front", "heated_seats_rear",
        "heated_steering_wheel", "keyless_entry", "apple_carplay",
    ]),
]

# Pre-compile patterns
_COMPILED_TRIMS: list[tuple[re.Pattern, re.Pattern, re.Pattern, list[str]]] = [
    (
        re.compile(make_p, re.IGNORECASE),
        re.compile(model_p, re.IGNORECASE) if model_p else re.compile(r"", re.IGNORECASE),
        re.compile(trim_p, re.IGNORECASE) if trim_p else re.compile(r"", re.IGNORECASE),
        features,
    )
    for make_p, model_p, trim_p, features in TRIM_FEATURES
]


def infer_trim_features(
    make: str,
    model: str,
    variant: str,
    title: str,
    year: int | None = None,
) -> list[str]:
    """Infer standard features based on trim/variant name.

    Checks the make, model, variant, and title against known trim-level
    feature databases. Returns a list of canonical feature keys that are
    standard equipment for the identified trim.

    Args:
        make: Vehicle manufacturer.
        model: Vehicle model.
        variant: Trim/variant name (e.g. "M Sport", "S Line").
        title: Full listing title (sometimes contains trim info).
        year: Registration year (for future year-specific trim data).

    Returns:
        List of canonical feature keys inferred from trim level.
    """
    if not make:
        return []

    # Combine variant and title for matching
    search_text = f"{variant or ''} {title or ''}"
    inferred = set()

    for make_pat, model_pat, trim_pat, features in _COMPILED_TRIMS:
        # Check make matches
        if not make_pat.search(make):
            continue

        # Check model matches (empty pattern matches everything)
        if model_pat.pattern and not model_pat.search(model or ""):
            continue

        # Check trim matches in variant or title
        if trim_pat.pattern:
            if not trim_pat.search(search_text):
                continue

        inferred.update(features)

    return sorted(inferred)
