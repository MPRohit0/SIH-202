import math,json,numpy as np
from PIL import Image,ImageFilter
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'public'/'data'
a=np.asarray(Image.open(p/'terrain-source.png').convert('RGB'),dtype=float)
z=a[:,:,0]*256+a[:,:,1]+a[:,:,2]/256-32768
west=735/1024*360-180;east=736/1024*360-180
lat=lambda y: math.degrees(math.atan(math.sinh(math.pi*(1-2*y/1024))))
north=lat(421);south=lat(422)
# Regrid Mercator pixel samples onto an evenly spaced latitude/longitude raster.
lats=np.linspace(north,south,256,endpoint=False)+(south-north)/512
ys=(1-np.arcsinh(np.tan(np.radians(lats)))/np.pi)/2*1024*256-421*256-.5
z=np.stack([np.interp(ys,np.arange(256),z[:,i]) for i in range(256)],axis=1)
dy,dx=np.gradient(z);shade=np.clip((-.65*dx-.5*dy+25)/np.sqrt(dx*dx+dy*dy+625),0,1)
base=np.clip((z-400)/2500,0,1)
rgb=np.stack([17+shade*52+base*9,30+shade*61+base*12,29+shade*50+base*10],axis=-1)
contours=(np.mod(z,100)<6);rgb[contours]*=.80
Image.fromarray(np.uint8(np.clip(rgb,0,255))).resize((1024,1024),Image.Resampling.BICUBIC).save(p/'tehri-relief.webp',quality=92)
zz=z.reshape(128,2,128,2).mean(axis=(1,3));nx=ny=128
x=round((78.483-west)/(east-west)*nx);y=round((north-30.370)/(north-south)*ny)
# Place hypothetical inflow at the lowest nearby downstream cell.
sub=zz[y-2:y+3,x-2:x+3];sy,sx=np.unravel_index(np.argmin(sub),sub.shape);idx=(y-2+sy)*nx+x-2+sx
out=dict(name='Tehri · Bhagirathi',source='Mapzen Terrain Tiles / AWS Open Data; SRTM-derived regional terrain',nx=nx,ny=ny,west=west,east=east,north=north,south=south,dx=(east-west)*111320*math.cos(math.radians((north+south)/2))/nx,dy=(north-south)*111320/ny,z=np.round(zz,2).ravel().tolist(),sourceIndex=int(idx),hillshade='/data/tehri-relief.webp')
(p/'tehri-grid.json').write_text(json.dumps(out,separators=(',',':')))
(p/'provenance.json').write_text(json.dumps({'terrain_url':'https://elevation-tiles-prod.s3.amazonaws.com/terrarium/10/735/421.png','catalog':'https://registry.opendata.aws/terrain-tiles/','attribution':'https://github.com/tilezen/joerd/blob/master/docs/attribution.md','processing':'Terrarium decode, latitude regrid, 2x2 mean aggregation; no channel bathymetry or dam modification.','retrieved':'2026-09-22','bounds':[west,south,east,north],'cellsize_m':[out['dx'],out['dy']],'source_index':int(idx)},indent=2))
print({k:v for k,v in out.items() if k!='z'})
