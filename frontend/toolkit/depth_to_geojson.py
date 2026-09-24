"""Convert a georeferenced depth GeoTIFF (SPH/Delft3D export) to WGS84 cells.
Example: python depth_to_geojson.py max_depth.tif result.geojson
Streaming windows limit working memory; output contains one polygon per wet cell.
Use a non-overlapping raster clipped to the active dashboard DEM bounds.
"""
import argparse,json,math
import numpy as np
import rasterio
from rasterio.warp import transform
p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('output');p.add_argument('--threshold',type=float,default=.3);p.add_argument('--max-features',type=int,default=100000);a=p.parse_args()
count=0
try:
 with rasterio.open(a.input) as src,open(a.output,'w') as out:
  if not src.crs:raise ValueError('Raster must have a CRS')
  out.write('{"type":"FeatureCollection","features":[')
  for _,window in src.block_windows(1):
   data=src.read(1,window=window,masked=True)
   ys,xs=np.where((data.filled(-1)>=a.threshold)&np.isfinite(data.filled(-1)))
   for y,x in zip(ys,xs):
    if count>=a.max_features:raise ValueError('Too many wet cells. Coarsen the depth raster before import.')
    col=int(window.col_off)+int(x);row=int(window.row_off)+int(y)
    ring=[src.transform*(col,row),src.transform*(col+1,row),src.transform*(col+1,row+1),src.transform*(col,row+1),src.transform*(col,row)]
    lon,lat=transform(src.crs,'EPSG:4326',[v[0] for v in ring],[v[1] for v in ring])
    feature={'type':'Feature','properties':{'depth_m':float(data[y,x])},'geometry':{'type':'Polygon','coordinates':[list(map(list,zip(lon,lat)))]}}
    out.write((',' if count else '')+json.dumps(feature,separators=(',',':')));count+=1
  out.write(']}')
except Exception:
 import pathlib
 pathlib.Path(a.output).unlink(missing_ok=True)
 raise
print(f'Exported {count} wet cells. Verify datum, units, time window and non-overlap before comparing.')
