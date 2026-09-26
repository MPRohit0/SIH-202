"""Tests for backend.m7_gee.provider.

`walk_upstream_basin_ids` is pure and needs no Earth Engine. `EarthEngineProvider._pixel_grid` is
pure too -- it just needs no live `ee` session to build the REST request shape. The rest of
`EarthEngineProvider` (the actual `computePixels`/HydroBASINS/CHIRPS calls) is exercised only by
the manual live smoke test (`docs/decisions.md` "M7 GEE fetch"), not here.
"""

from __future__ import annotations

from backend.m7_gee.lake_area import AoiGrid
from backend.m7_gee.provider import EarthEngineProvider, MAX_UPSTREAM_HOPS, walk_upstream_basin_ids


class TestWalkUpstreamBasinIds:
    def test_single_headwater_basin_has_no_upstream(self):
        assert walk_upstream_basin_ids(1, lambda frontier: []) == [1]

    def test_walks_a_short_chain(self):
        graph = {1: [2, 3], 2: [4], 3: [], 4: []}  # NEXT_DOWN -> [ids whose NEXT_DOWN is it]

        def next_upstream(frontier):
            return [i for f in frontier for i in graph.get(f, [])]

        assert sorted(walk_upstream_basin_ids(1, next_upstream)) == [1, 2, 3, 4]

    def test_does_not_revisit_ids_already_found(self):
        # a diamond: 2 and 3 both drain into 1, and 4 drains into both 2 and 3
        graph = {1: [2, 3], 2: [4], 3: [4], 4: []}
        calls = []

        def next_upstream(frontier):
            calls.append(sorted(frontier))
            return [i for f in frontier for i in graph.get(f, [])]

        result = walk_upstream_basin_ids(1, next_upstream)
        assert sorted(result) == [1, 2, 3, 4]
        assert len(result) == len(set(result))  # 4 is not duplicated even though it appears twice

    def test_stops_at_max_upstream_hops_on_an_unbounded_graph(self):
        # every basin has exactly one further-upstream neighbour, forever
        def next_upstream(frontier):
            return [max(frontier) + 1]

        result = walk_upstream_basin_ids(0, next_upstream)
        assert len(result) == MAX_UPSTREAM_HOPS + 1  # the seed, plus one per hop


class TestPixelGrid:
    def test_matches_the_rest_pixelgrid_shape(self):
        grid = AoiGrid(epsg=32645, origin_x=500000.0, origin_y=3090000.0, cell_size_m=10.0, width=600, height=600)
        params = EarthEngineProvider()._pixel_grid(grid)
        assert params == {
            "dimensions": {"width": 600, "height": 600},
            "affineTransform": {
                "scaleX": 10.0, "shearX": 0.0, "translateX": 500000.0,
                "shearY": 0.0, "scaleY": -10.0, "translateY": 3090000.0,
            },
            "crsCode": "EPSG:32645",
        }
