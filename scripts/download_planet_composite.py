#!/usr/bin/env python3
"""Search, download, and median-composite Planet imagery for an AOI.

This command-line program uses the synchronous interface introduced in the
Planet Python SDK 3.x. It adapts the basic ``Planet().data.search(...)``
pattern into a reproducible workflow that:

1. reads an AOI from GeoJSON or a WGS84 bounding box;
2. searches a Planet item type over an inclusive date range;
3. filters scenes by cloud cover, standard quality, download permission, and
   availability of the requested asset type;
4. activates and downloads each accessible raster asset; and
5. reprojects the rasters to a common AOI grid and calculates a per-pixel,
   per-band median composite in blocks.

Requirements
------------
Install ``requirements.txt`` in the project virtual environment. Set your
Planet API key in the environment; never put the key in this script or commit
it to Git::

    export PL_API_KEY="your-planet-api-key"

Your Planet account must be licensed for the selected imagery and asset type.
The default ``ortho_analytic_4b_sr`` asset is four-band, orthorectified surface
reflectance. Availability depends on the scene and your subscription.

AOI input
---------
Use exactly one of:

* ``--aoi path.geojson`` for a Polygon/MultiPolygon geometry or Feature; or
* ``--bbox WEST SOUTH EAST NORTH`` in WGS84 longitude/latitude degrees.

Dates use ISO ``YYYY-MM-DD`` and are inclusive. Cloud cover is a fraction from
0 to 1, so ``--max-cloud 0.2`` means at most 20 percent scene-level cloud.
Scene-level cloud filtering is not a cloud mask: cloudy pixels can remain in
the composite. For analysis-quality results, apply UDM2 pixel masking in a
separate preprocessing step.

Example
-------
From the repository root, with ``.venv`` activated::

    python scripts/download_planet_composite.py \
      --bbox 84.9 28.0 86.0 29.1 \
      --start-date 2026-08-01 \
      --end-date 2026-08-31 \
      --max-cloud 0.20 \
      --limit 20 \
      --download-dir data/raw/planet/2026-08 \
      --output data/processed/planet_median_202608.tif

To inspect matching scene IDs without downloading data, append
``--search-only``. If that returns zero results, append ``--catalog-search``
as well. Catalogue mode omits the download-permission filter and therefore
helps distinguish "no imagery exists" from "your account cannot download the
imagery." Catalogue results are not necessarily downloadable. Existing files
are reused unless ``--overwrite`` is given.

Output and limitations
----------------------
The composite is a tiled, compressed float32 GeoTIFF. Its CRS and native pixel
size come from the first downloaded raster; all other rasters are warped to
that grid with bilinear resampling. The extent is the AOI bounding rectangle,
and pixels with no valid observation are written as -9999. A JSON manifest is
written beside the downloads with search arguments, selected scene metadata,
and local paths.

A median reduces isolated cloud and haze only when enough clear observations
exist. It does not guarantee radiometric normalization, exact co-registration,
or cloud-free output. Review licensing before sharing downloaded Planet data
or derived products.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date, datetime, time, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Sequence
import warnings

import numpy as np
from planet import Planet, data_filter
import rasterio
from rasterio.features import bounds as geometry_bounds
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_geom


DEFAULT_ITEM_TYPE = "PSScene"
DEFAULT_ASSET_TYPE = "ortho_analytic_4b_sr"
OUTPUT_NODATA = -9999.0


def parse_date(value: str) -> date:
    """Parse an ISO calendar date for argparse."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Planet scenes and build an AOI median composite.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    aoi_group = parser.add_mutually_exclusive_group(required=True)
    aoi_group.add_argument("--aoi", type=Path, help="GeoJSON AOI file")
    aoi_group.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="WGS84 AOI bounding box",
    )
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument(
        "--max-cloud",
        type=float,
        default=0.20,
        help="maximum scene cloud-cover fraction (0 to 1)",
    )
    parser.add_argument("--limit", type=int, default=20, help="maximum scenes")
    parser.add_argument("--item-type", default=DEFAULT_ITEM_TYPE)
    parser.add_argument("--asset-type", default=DEFAULT_ASSET_TYPE)
    parser.add_argument(
        "--download-dir", type=Path, default=Path("data/raw/planet")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/planet_median.tif"),
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="list matches and write a manifest without downloading",
    )
    parser.add_argument(
        "--catalog-search",
        action="store_true",
        help="omit download-permission filtering (requires --search-only)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace downloads and output"
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.start_date > args.end_date:
        parser.error("--start-date must be on or before --end-date")
    if not 0 <= args.max_cloud <= 1:
        parser.error("--max-cloud must be between 0 and 1")
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.catalog_search and not args.search_only:
        parser.error("--catalog-search requires --search-only")
    if args.bbox:
        west, south, east, north = args.bbox
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            parser.error("--bbox must satisfy west < east and south < north")


def load_aoi(aoi_path: Path | None, bbox: Sequence[float] | None) -> dict:
    """Return one Polygon or MultiPolygon geometry in WGS84 GeoJSON."""
    if bbox:
        west, south, east, north = bbox
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        }
    else:
        assert aoi_path is not None
        try:
            document = json.loads(aoi_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read AOI {aoi_path}: {exc}") from exc
        document_type = document.get("type")
        if document_type == "Feature":
            geometry = document.get("geometry")
        elif document_type == "FeatureCollection":
            features = document.get("features", [])
            if len(features) != 1:
                raise ValueError("AOI FeatureCollection must contain exactly one feature")
            geometry = features[0].get("geometry")
        else:
            geometry = document

    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "Polygon",
        "MultiPolygon",
    }:
        raise ValueError("AOI must be a GeoJSON Polygon or MultiPolygon")
    if not geometry.get("coordinates"):
        raise ValueError("AOI geometry has no coordinates")
    return geometry


def make_search_filter(args: argparse.Namespace) -> dict:
    start = datetime.combine(args.start_date, time.min, tzinfo=timezone.utc)
    # Planet's upper comparison is exclusive, so advance one day to make the
    # user-facing end date inclusive.
    end_exclusive = datetime.combine(
        args.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    filters = [
        data_filter.date_range_filter("acquired", gte=start, lt=end_exclusive),
        data_filter.range_filter("cloud_cover", lte=args.max_cloud),
        data_filter.asset_filter([args.asset_type]),
        data_filter.std_quality_filter(),
    ]
    if not args.catalog_search:
        filters.append(data_filter.permission_filter())
    return data_filter.and_filter(filters)


def print_scene(scene: dict) -> None:
    properties = scene.get("properties", {})
    cloud = properties.get("cloud_cover")
    cloud_text = "unknown" if cloud is None else f"{100 * cloud:.1f}%"
    permissions = scene.get("_permissions", [])
    downloadable = any(
        permission == "assets:download" or permission.endswith(":download")
        for permission in permissions
    )
    print(
        f"{scene.get('id')}  acquired={properties.get('acquired')}  "
        f"cloud={cloud_text}  downloadable={downloadable}"
    )


def download_scenes(
    planet: Planet, scenes: list[dict], args: argparse.Namespace
) -> tuple[list[Path], list[dict]]:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    records: list[dict] = []

    for index, scene in enumerate(scenes, start=1):
        scene_id = scene["id"]
        print(f"[{index}/{len(scenes)}] Preparing {scene_id}")
        record = {
            "id": scene_id,
            "item_type": args.item_type,
            "asset_type": args.asset_type,
            "catalog_search": args.catalog_search,
            "properties": scene.get("properties", {}),
        }
        try:
            asset = planet.data.get_asset(
                args.item_type, scene_id, args.asset_type
            )
            if asset.get("status") != "active":
                planet.data.activate_asset(asset)
                asset = planet.data.wait_asset(
                    asset,
                    callback=lambda status, sid=scene_id: print(
                        f"  {sid}: {status}", flush=True
                    ),
                )
            filename = f"{scene_id}_{args.asset_type}.tif"
            path = planet.data.download_asset(
                asset,
                filename=filename,
                directory=args.download_dir,
                overwrite=args.overwrite,
                progress_bar=True,
            )
            path = Path(path).resolve()
            planet.data.validate_checksum(asset, path)
            record.update({"status": "downloaded", "path": str(path)})
            paths.append(path)
        except Exception as exc:  # continue so one unavailable asset is non-fatal
            record.update({"status": "failed", "error": str(exc)})
            print(f"  WARNING: {scene_id} failed: {exc}", file=sys.stderr)
        records.append(record)
    return paths, records


def create_median_composite(
    raster_paths: Sequence[Path], aoi_wgs84: dict, output_path: Path, overwrite: bool
) -> None:
    """Warp inputs to one grid and calculate a block-wise nanmedian."""
    if not raster_paths:
        raise ValueError("no raster assets were downloaded; cannot composite")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"output exists: {output_path}; use --overwrite to replace it"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        sources = [stack.enter_context(rasterio.open(path)) for path in raster_paths]
        reference = sources[0]
        if reference.crs is None:
            raise ValueError(f"first raster has no CRS: {raster_paths[0]}")
        band_count = reference.count
        if any(source.count != band_count for source in sources):
            raise ValueError("downloaded rasters do not have the same band count")

        projected_aoi = transform_geom("EPSG:4326", reference.crs, aoi_wgs84)
        left, bottom, right, top = geometry_bounds(projected_aoi)
        x_resolution = abs(reference.transform.a)
        y_resolution = abs(reference.transform.e)
        width = max(1, math.ceil((right - left) / x_resolution))
        height = max(1, math.ceil((top - bottom) / y_resolution))
        transform = from_origin(left, top, x_resolution, y_resolution)

        vrts = [
            stack.enter_context(
                WarpedVRT(
                    source,
                    crs=reference.crs,
                    transform=transform,
                    width=width,
                    height=height,
                    src_nodata=source.nodata,
                    nodata=OUTPUT_NODATA,
                    resampling=Resampling.bilinear,
                )
            )
            for source in sources
        ]

        profile = reference.profile.copy()
        profile.update(
            driver="GTiff",
            dtype="float32",
            count=band_count,
            crs=reference.crs,
            transform=transform,
            width=width,
            height=height,
            nodata=OUTPUT_NODATA,
            compress="deflate",
            predictor=3,
            tiled=True,
            blockxsize=256,
            blockysize=256,
            BIGTIFF="IF_SAFER",
        )

        with rasterio.open(output_path, "w", **profile) as destination:
            for _, window in destination.block_windows(1):
                arrays = [
                    vrt.read(window=window, masked=True, out_dtype="float32").filled(
                        np.nan
                    )
                    for vrt in vrts
                ]
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message="All-NaN slice encountered"
                    )
                    median = np.nanmedian(np.stack(arrays), axis=0)
                median = np.where(np.isfinite(median), median, OUTPUT_NODATA)
                destination.write(median.astype("float32"), window=window)

    print(f"Median composite written to {output_path}")


def write_manifest(
    args: argparse.Namespace, aoi: dict, scene_records: list[dict]
) -> Path:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.download_dir / "manifest.json"
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "aoi": aoi,
        "search": {
            "start_date": args.start_date.isoformat(),
            "end_date": args.end_date.isoformat(),
            "max_cloud": args.max_cloud,
            "limit": args.limit,
            "item_type": args.item_type,
            "asset_type": args.asset_type,
            "catalog_search": args.catalog_search,
        },
        "scenes": scene_records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written to {manifest_path}")
    return manifest_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args, parser)

    if not os.environ.get("PL_API_KEY"):
        parser.error("PL_API_KEY is not set in the environment")

    try:
        aoi = load_aoi(args.aoi, args.bbox)
        planet = Planet()
        scenes = list(
            planet.data.search(
                [args.item_type],
                search_filter=make_search_filter(args),
                geometry=aoi,
                sort="acquired asc",
                limit=args.limit,
            )
        )
        print(f"Found {len(scenes)} matching scene(s).")
        for scene in scenes:
            print_scene(scene)

        if not scenes:
            write_manifest(args, aoi, [])
            return 2
        if args.search_only:
            records = [
                {
                    "id": scene["id"],
                    "item_type": args.item_type,
                    "status": "search-result",
                    "permissions": scene.get("_permissions", []),
                    "properties": scene.get("properties", {}),
                }
                for scene in scenes
            ]
            write_manifest(args, aoi, records)
            return 0

        raster_paths, records = download_scenes(planet, scenes, args)
        write_manifest(args, aoi, records)
        create_median_composite(raster_paths, aoi, args.output, args.overwrite)
        return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
