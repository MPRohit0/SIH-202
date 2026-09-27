# Scene3D binary format

`GET /api/v1/scene3d/{query_id}?vertical_exaggeration=1.5` returns metadata for a compact
Three.js scene. `vertical_exaggeration` is optional, defaults to `1.5`, and accepts values from
`0.1` through `10`. It describes a client-side multiplier on the local Z axis; stored elevation
and depth values remain in physical metres. XY distance and all Z values use metres.

## Coordinate frame and arrays

`frame.origin_x_utm_m` and `frame.origin_y_utm_m` are the UTM coordinates of the lower-left
origin from `terrain/nearfield_frame.json`. The EPSG code identifies the site's UTM CRS. Local
coordinates are east/north/up: `x = UTM easting - origin_x_utm_m`,
`y = UTM northing - origin_y_utm_m`, and `z = elevation_m`. Both raster surfaces and GLB meshes
use this same frame. `vertical_exaggeration` is applied by the renderer to Z only.

`terrain.url` and `flood_surface.url` point to raw, headerless `float32_le_row_major` arrays:
IEEE-754 binary32, little endian, row-major, with `width * height` samples and no padding.
Array index `row * width + column` starts at the upper-left cell. The affine `transform` is the
GDAL six-number transform for that reduced terrain grid; `cell_size_x_m` and `cell_size_y_m`
are its sample spacing. `origin_x_utm_m` and `origin_y_utm_m` mark the upper-left grid corner,
and `origin_local_x_m`/`origin_local_y_m` are that corner relative to the shared frame.
`nodata` is `-9999.0`.

The terrain array stores downsampled DEM elevation. The flood array has identical dimensions and
alignment. Wet cells store `terrain + depth_p50` (water-surface elevation); dry and nodata cells
store `-9999.0`. Thus the flood surface does not encode depth by itself. The renderer may draw
the flood surface only where its value is not nodata.

## Near-field comparison assets

`comparison.nearfield_bounds_local` is `[[min_x, min_y], [max_x, max_y]]` in metres in the
shared frame. `delft3d_surface_url` is null if the query has no paired Delft3D near-field maximum
depth asset; when present it serves a geometry-only glTF 2.0 binary (`.glb`) built from
`dem_nearfield + summary_nearfield/max_depth.tif`. This cellwise maximum is not a simultaneous
time snapshot; `delft3d_surface_basis` states this in the response.
`sph_surfaces` lists available SPH geometry-only glTF binary snapshots, with `t_s` seconds since
t0 and a URL for each. These GLB files are already in the shared local metric frame; their
positions are metres and clients apply vertical exaggeration to Z.

## Size and asset URLs

`payload_bytes` is the sum of the byte lengths of every binary asset referenced by the response,
including terrain, flood surface, and included comparison GLBs. The server limits that sum to
19,950,000 bytes so the JSON metadata also remains under 20 MB (20,000,000 bytes). The terrain grid is
downsampled to leave room for comparison files, and SPH snapshots are included in time order only
while they fit, up to 128 snapshots. `terrain.byte_length` and
`flood_surface.byte_length` give exact array sizes; GLB lengths are available from HTTP headers.

Asset URLs are same-origin paths under `/api/v1/files/`. They are query-scoped for the terrain,
emulated surface, and generated Delft3D surface, and run-scoped for source SPH GLB snapshots.
Missing scene inputs retain M0's contract mock behavior. An invalid exaggeration returns 422;
an assembled scene exceeding the budget returns 413.
