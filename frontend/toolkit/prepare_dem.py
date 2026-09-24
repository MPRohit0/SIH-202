"""Reproject/crop a large DEM to a bounded WGS84 ASCII grid.
Example: python prepare_dem.py input.tif output.asc --bounds 78.40 30.15 78.75 30.45
Source rasters are accessed through GDAL rather than read in full into RAM.
"""
import argparse, math
import numpy as np
import rasterio
from rasterio.warp import reproject, transform_bounds, Resampling
from rasterio.transform import from_origin
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('input');p.add_argument('output');p.add_argument('--bounds',nargs=4,type=float,metavar=('W','S','E','N'));p.add_argument('--max-cells',type=int,default=40000)
a=p.parse_args()
if not 9<=a.max_cells<=60000:p.error('--max-cells must be 9..60000 for the browser prototype')
with rasterio.open(a.input) as src:
 if not src.crs:raise ValueError('Input needs a declared coordinate reference system')
 w,s,e,n=a.bounds or transform_bounds(src.crs,'EPSG:4326',*src.bounds,densify_pts=21)
 if not (-180<=w<e<=180 and -85<=s<n<=85):raise ValueError('Invalid WGS84 bounds')
 cell=max(math.sqrt((e-w)*(n-s)/a.max_cells),.00001)
 while math.ceil((e-w)/cell)*math.ceil((n-s)/cell)>a.max_cells:cell*=1.005
 nx=math.ceil((e-w)/cell);ny=math.ceil((n-s)/cell)
 out=np.full((ny,nx),-9999.,dtype=np.float32)
 reproject(rasterio.band(src,1),out,src_transform=src.transform,src_crs=src.crs,src_nodata=src.nodata,dst_transform=from_origin(w,n,cell,cell),dst_crs='EPSG:4326',dst_nodata=-9999,resampling=Resampling.average,warp_mem_limit=64)
 if np.any(out==-9999) or not np.all(np.isfinite(out)):raise ValueError('Output contains NoData. Crop to fully covered bounds or fill source voids in GIS first.')
 with open(a.output,'w') as f:
  f.write(f'ncols {nx}\nnrows {ny}\nxllcorner {w}\nyllcorner {n-ny*cell}\ncellsize {cell}\nNODATA_value -9999\n')
  np.savetxt(f,out,fmt='%.3f')
 print(f'Wrote {nx} x {ny} cells to {a.output}. Elevation units must be metres; verify source vertical datum.')
