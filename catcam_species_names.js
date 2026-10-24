/* Shared CatCam species-name formatting. */

window.catcamSpeciesNames = {
  "american goldfinch": "Spinus tristis",
  "american robin": "Turdus migratorius",
  "black-capped chickadee": "Poecile atricapillus",
  "blue jay": "Cyanocitta cristata",
  "carolina chickadee": "Poecile carolinensis",
  "chipping sparrow": "Spizella passerina",
  "common grackle": "Quiscalus quiscula",
  "dark-eyed junco": "Junco hyemalis",
  "downy woodpecker": "Dryobates pubescens",
  "european starling": "Sturnus vulgaris",
  "gray catbird": "Dumetella carolinensis",
  "hairy woodpecker": "Leuconotopicus villosus",
  "house finch": "Haemorhous mexicanus",
  "house sparrow": "Passer domesticus",
  "indigo bunting": "Passerina cyanea",
  "mourning dove": "Zenaida macroura",
  "northern cardinal": "Cardinalis cardinalis",
  "red-bellied woodpecker": "Melanerpes carolinus",
  "red-winged blackbird": "Agelaius phoeniceus",
  "rose-breasted grosbeak": "Pheucticus ludovicianus",
  "song sparrow": "Melospiza melodia",
  "tufted titmouse": "Baeolophus bicolor",
  "white-breasted nuthatch": "Sitta carolinensis"
};

window.formatCatcamSpecies = function(name) {
  if (!name) return '';

  const common = String(name).trim();
  const scientific = window.catcamSpeciesNames[common.toLowerCase()];

  return scientific
    ? `${common} (${scientific})`
    : common;
};
