# Nepal–Tibet Himalayan Flash-Flood Analysis

Python project for investigating the reported 26 August 2026 flash flood in the
high-mountain Nepal–Tibet (China) border region and comparing it with earlier
events. The planned workflow combines Planet imagery (subject to account access)
with open remote-sensing and geospatial datasets to assess likely causes,
inundation and geomorphic change, exposed assets, and damage.

> **Project status:** initial scaffold. Event details, affected-area boundaries,
> acquisition dates, and causal interpretations must be verified against
> authoritative sources before operational analysis or publication.

## Planned outputs

- Reproducible catalogue of pre-event, event, and post-event observations
- Cloud/snow masking, terrain correction, and image co-registration
- Change, water, debris, and landslide indicators
- Building, road, bridge, agricultural, and land-cover exposure statistics
- Comparisons with documented historical flash floods
- Static figures, tabular summaries, and an interactive before/after slider map
- Methods, provenance, uncertainty, and limitations documentation

## Repository layout

```text
.
├── configs/                 # AOI, dates, data-source, and processing settings
├── data/
│   ├── raw/                 # Original downloads; never edit in place
│   ├── external/            # Third-party reference and validation datasets
│   ├── interim/             # Temporary/reprojected/derived working data
│   └── processed/           # Analysis-ready datasets
├── docs/                    # Methods, data dictionary, sources, and decisions
├── notebooks/               # Numbered exploratory and presentation notebooks
├── outputs/
│   ├── figures/             # Publication-ready plots and maps
│   ├── maps/                # Exported interactive/static maps
│   ├── reports/             # Generated reports
│   └── tables/              # Damage and exposure statistics
├── scripts/                 # Re-runnable command-line workflow entry points
├── src/nepal_flashflood/    # Importable Python package
├── tests/                   # Automated tests
└── web/                     # Before/after web-map application and assets
```

Large rasters, vectors, credentials, and generated outputs are excluded from
Git. Store source data in the appropriate `data/` directory and record its URL,
license, retrieval time, spatial extent, and checksum in a future data manifest.
For large files that must be versioned, configure Git LFS or use object storage.

## Quick start

Python 3.11 or newer is recommended. Geospatial wheels are generally easiest to
install in a fresh virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Then copy `configs/project.example.yaml` to `configs/project.yaml`, add the
verified area of interest and acquisition windows, and configure only the data
providers you intend to use. Never commit API keys.

## Candidate data sources

- PlanetScope/SkySat, where licensed and available
- Sentinel-1 SAR and Sentinel-2 optical imagery
- Landsat and harmonized optical archives
- DEMs such as Copernicus DEM or NASADEM
- Satellite precipitation and snow products
- OpenStreetMap and authoritative local infrastructure/boundary datasets

Availability, licensing, spatial resolution, cloud cover, terrain effects, and
cross-border data restrictions must be checked for each dataset.

## Suggested notebook sequence

1. `01_event_context.ipynb` — sources, timeline, AOI, and hypotheses
2. `02_data_discovery.ipynb` — catalogue and quality-screen observations
3. `03_preprocessing.ipynb` — masking, reprojection, and co-registration
4. `04_change_detection.ipynb` — flood/debris/landslide change products
5. `05_damage_statistics.ipynb` — exposure and uncertainty summaries
6. `06_historical_comparison.ipynb` — comparable previous events
7. `07_map_export.ipynb` — tiles and before/after slider deliverables

Exploration can begin in notebooks, but reusable processing belongs in `src/`
and repeatable pipeline entry points belong in `scripts/`.

## Reproducibility and safety

- Keep raw data immutable and preserve source metadata.
- Use a common CRS appropriate to the verified AOI; retain WGS84 exports for web maps.
- Report sensor resolution, temporal mismatch, classification thresholds, and uncertainty.
- Treat automated damage estimates as screening results until independently validated.
- Do not publish sensitive locations or restricted commercial imagery without permission.

## Git and GitHub

This directory is ready to initialize locally:

```bash
git init
git add .
git commit -m "Initialize Nepal flash-flood analysis project"
git branch -M main
git remote add origin https://github.com/aazizbau/nepal_flashflood.git
git push -u origin main
```

Git/GitHub initialization and remote creation are intentionally left for the
repository owner so the correct account, visibility, and licensing can be chosen.
