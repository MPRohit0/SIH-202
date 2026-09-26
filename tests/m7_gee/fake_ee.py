"""A minimal fake of the `ee` (Earth Engine) module, just enough of its chained-call API
surface for `backend.m7_gee.scene_search` to run against a small in-memory scene catalogue,
with no network access and no real `earthengine-api` install required.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _iso_to_millis(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _millis_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class _Value:
    """Stands in for anything the real client would need `.getInfo()` on."""

    def __init__(self, value):
        self._value = value

    def getInfo(self):
        return self._value


class FakeEE:
    """Holds an in-memory scene catalogue and exposes it as the subset of the `ee` API that
    `scene_search.py` calls. Build one, assign scenes, then install it as `sys.modules["ee"]`.
    """

    def __init__(self):
        # {collection: {scene_id: {"date": iso, "cloud_pct": float|None, "cloud_pct_aoi": float|None,
        #                           "orbit_pass": str|None}}}
        self.scenes: dict[str, dict[str, dict]] = {}
        self.initialized_with_project: str | None = "unset"
        self._install_namespaces()

    def add_scene(self, collection: str, scene_id: str, date: str, cloud_pct: float | None = None,
                  cloud_pct_aoi: float | None = None, orbit_pass: str | None = None,
                  instrument_mode: str = "IW") -> None:
        self.scenes.setdefault(collection, {})[scene_id] = {
            "date": date, "cloud_pct": cloud_pct, "cloud_pct_aoi": cloud_pct_aoi,
            "orbit_pass": orbit_pass, "instrument_mode": instrument_mode,
        }

    # -- ee.Initialize -------------------------------------------------------------------

    def Initialize(self, credentials=None, project=None):
        self.initialized_with_project = project
        self.initialized_with_credentials = credentials

    def ServiceAccountCredentials(self, email, key_file):
        return ("service_account_credentials", email, key_file)

    # -- namespaces used as `ee.Geometry`, `ee.Filter`, `ee.Reducer`, `ee.Date`, `ee.Image` ----

    def _install_namespaces(self):
        outer = self

        class Geometry:
            @staticmethod
            def Rectangle(coords):
                return ("rect", tuple(coords))

        class Filter:
            @staticmethod
            def lte(field, value):
                return ("lte", field, value)

            @staticmethod
            def eq(field, value):
                return ("eq", field, value)

        class Reducer:
            @staticmethod
            def mean():
                return "mean"

        class Date:
            def __init__(self, millis):
                self._millis = millis

            def format(self, fmt):
                assert fmt == "YYYY-MM-dd"
                return _Value(_millis_to_date(self._millis))

        class ImageCollection:
            def __init__(self, name, records=None):
                self.name = name
                self._records = records if records is not None else [
                    {"scene_id": sid, **rec} for sid, rec in outer.scenes.get(name, {}).items()
                ]

            def filterBounds(self, aoi):
                return self  # the fake AOI always "contains" every fixture scene

            def filterDate(self, start, end):
                kept = [r for r in self._records if start <= r["date"] < end]
                return ImageCollection(self.name, kept)

            def filter(self, condition):
                kind, field, value = condition
                if field == "instrumentMode":
                    kept = [r for r in self._records if r.get("instrument_mode") == value]
                elif field == "CLOUDY_PIXEL_PERCENTAGE":
                    kept = [r for r in self._records
                            if r.get("cloud_pct") is not None and r["cloud_pct"] <= value]
                else:
                    raise NotImplementedError(field)
                return ImageCollection(self.name, kept)

            def sort(self, field, ascending):
                assert field == "system:time_start"
                kept = sorted(self._records, key=lambda r: r["date"], reverse=not ascending)
                return ImageCollection(self.name, kept)

            def limit(self, n):
                return ImageCollection(self.name, self._records[:n])

            def aggregate_array(self, field):
                assert field == "system:index"
                return _Value([r["scene_id"] for r in self._records])

        class Image:
            def __init__(self, full_id):
                collection, scene_id = full_id.rsplit("/", 1)
                self.collection = collection
                self.scene_id = scene_id
                self._record = outer.scenes[collection][scene_id]

            def select(self, band):
                return self

            def clip(self, aoi):
                return self

            def remap(self, from_list, to_list, default):
                return self

            def toDictionary(self, keys):
                props = {
                    "system:time_start": _iso_to_millis(self._record["date"]),
                    "CLOUDY_PIXEL_PERCENTAGE": self._record.get("cloud_pct"),
                    "orbitProperties_pass": self._record.get("orbit_pass"),
                }
                return _Value({k: props[k] for k in keys})

            def reduceRegion(self, reducer, geometry, scale, maxPixels, bestEffort):
                return _Value({"SCL": self._record.get("cloud_pct_aoi")})

            def getThumbURL(self, params):
                return f"https://fake-ee.example/{self.scene_id}.png"

        self.Geometry = Geometry
        self.Filter = Filter
        self.Reducer = Reducer
        self.Date = Date
        self.ImageCollection = ImageCollection
        self.Image = Image
