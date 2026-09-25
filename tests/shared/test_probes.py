import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from backend.shared.probes import Probe, load_probes


def _write_pois_gpkg(path, rows: list[dict]):
    df = pd.DataFrame(rows)
    gdf = gpd.GeoDataFrame(df, geometry=[Point(r["x_m"], r["y_m"]) for r in rows], crs="EPSG:32645")
    gdf.drop(columns=["x_m", "y_m"]).to_file(path, driver="GPKG")


def test_load_probes_round_trips_pois_gpkg(tmp_path):
    _write_pois_gpkg(tmp_path / "pois.gpkg", [
        {"poi_id": "synth__poi__chungthang", "name": "Chungthang", "kind": "town",
         "chainage_m": 1200.0, "dist_to_channel_m": 30.0, "row": 5, "col": 10, "x_m": 500100.0, "y_m": 3099950.0},
        {"poi_id": "synth__poi__bridge1", "name": "Bridge 1", "kind": "bridge",
         "chainage_m": 800.0, "dist_to_channel_m": 5.0, "row": 8, "col": 12, "x_m": 500160.0, "y_m": 3099920.0},
    ])

    probes = load_probes(tmp_path)

    assert probes == [
        Probe("synth__poi__chungthang", "Chungthang", "town", 500100.0, 3099950.0),
        Probe("synth__poi__bridge1", "Bridge 1", "bridge", 500160.0, 3099920.0),
    ]


def test_load_probes_missing_file_returns_empty_list(tmp_path):
    assert load_probes(tmp_path) == []
