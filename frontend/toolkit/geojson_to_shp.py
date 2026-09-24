"""Convert dashboard GeoJSON export to a Shapefile bundle.
python geojson_to_shp.py jaldrishti-inundation.geojson inundation
Creates .shp, .shx, .dbf, .prj and .cpg in the chosen directory.
"""
import argparse,json,pathlib,fiona
p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('output_dir');a=p.parse_args()
fc=json.load(open(a.input));out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
schema={'geometry':'Polygon','properties':{'depth_m':'float:18.3','arrival_m':'float:18.3'}}
with fiona.open(out/'inundation.shp','w',driver='ESRI Shapefile',schema=schema,crs='EPSG:4326',encoding='UTF-8') as dst:
 for f in fc['features']:
  dst.write({'geometry':f['geometry'],'properties':{'depth_m':f['properties']['depth_m'],'arrival_m':f['properties'].get('arrival_min')}})
print(out/'inundation.shp')
