"""Shared bird species display names for CatCam.

Keep internal species identifiers unchanged. These mappings are for display.
"""

SCIENTIFIC_NAMES = {
    "northern cardinal": "Cardinalis cardinalis",
    "house finch": "Haemorhous mexicanus",
    "american goldfinch": "Spinus tristis",
    "house sparrow": "Passer domesticus",
    "blue jay": "Cyanocitta cristata",
    "mourning dove": "Zenaida macroura",
    "red-bellied woodpecker": "Melanerpes carolinus",
    "downy woodpecker": "Dryobates pubescens",
    "hairy woodpecker": "Leuconotopicus villosus",
    "white-breasted nuthatch": "Sitta carolinensis",
    "tufted titmouse": "Baeolophus bicolor",
    "black-capped chickadee": "Poecile atricapillus",
    "carolina chickadee": "Poecile carolinensis",
    "american robin": "Turdus migratorius",
    "european starling": "Sturnus vulgaris",
    "common grackle": "Quiscalus quiscula",
    "dark-eyed junco": "Junco hyemalis",
    "song sparrow": "Melospiza melodia",
    "chipping sparrow": "Spizella passerina",
    "red-winged blackbird": "Agelaius phoeniceus",
    "rose-breasted grosbeak": "Pheucticus ludovicianus",
    "indigo bunting": "Passerina cyanea",
    "gray catbird": "Dumetella carolinensis",
}


def format_species_name(common_name, scientific_name=None):
    """Display Common Name (Scientific name), when available."""
    if not common_name:
        return ""

    common_name = str(common_name).strip()
    scientific_name = (
        scientific_name
        or SCIENTIFIC_NAMES.get(common_name.casefold())
    )

    if scientific_name and scientific_name.casefold() != common_name.casefold():
        return f"{common_name} ({scientific_name})"

    return common_name
