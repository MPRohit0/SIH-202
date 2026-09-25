"""Tests for backend.m1_terrain.domain."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m1_terrain import domain
from backend.shared.grid import CanonicalGrid


def _grid(h=20, w=20, cs=10.0):
    return CanonicalGrid(site_id="test", grid_id="farfield", crs_epsg=32645, origin_x=0.0,
                          origin_y=h * cs, cell_size_m=cs, width=w, height=h)


def test_domain_mask_matches_hand_threshold_and_contains_channel():
    h, w = 20, 20
    rows, _ = np.indices((h, w))
    hand = np.abs(rows - 10).astype(np.float32) * 5
    channel_mask = np.zeros((h, w), dtype=bool)
    channel_mask[10, :] = True

    mask = domain.domain_mask(hand, channel_mask, max_hand_m=20)
    assert mask[channel_mask].all()
    assert np.array_equal(mask.astype(bool), hand <= 20)


def test_domain_mask_excludes_disconnected_low_hand_patch():
    h, w = 20, 20
    rows, _ = np.indices((h, w))
    hand = np.abs(rows - 10).astype(np.float32) * 5
    hand[0:3, 0:3] = 0.0  # a disconnected low-HAND patch in a neighbouring valley
    channel_mask = np.zeros((h, w), dtype=bool)
    channel_mask[10, :] = True

    mask = domain.domain_mask(hand, channel_mask, max_hand_m=5)
    assert not mask[0:3, 0:3].any()
    assert mask[10, :].all()


def test_domain_mask_grows_with_larger_max_hand():
    h, w = 20, 20
    rows, _ = np.indices((h, w))
    hand = np.abs(rows - 10).astype(np.float32) * 5
    channel_mask = np.zeros((h, w), dtype=bool)
    channel_mask[10, :] = True

    small = domain.domain_mask(hand, channel_mask, max_hand_m=5)
    large = domain.domain_mask(hand, channel_mask, max_hand_m=20)
    assert large.sum() > small.sum()
    assert np.all(large[small.astype(bool) == 1])


def test_domain_polygon_area_matches_mask_area():
    grid = _grid()
    h, w = grid.shape
    rows, cols = np.indices((h, w))
    mask = ((rows - 10) ** 2 + (cols - 10) ** 2 <= 25).astype(np.uint8)
    gdf = domain.domain_polygon(mask, grid)
    cell_area = grid.cell_size_m ** 2
    assert gdf.geometry.iloc[0].area == pytest.approx(mask.sum() * cell_area, rel=0.05)
