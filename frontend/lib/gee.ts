import type {Grid} from './model';
export function geeScript(g:Grid,before:string,after:string,threshold:number){return `// Sentriq / SIH 26161 — Sentinel-1 screening workflow
// Run in an authorised Earth Engine Code Editor project. Not a live forecast.
var aoi = ee.Geometry.Rectangle([${g.west},${g.south},${g.east},${g.north}]);
var beforeStart = ee.Date('${before}');
var afterStart = ee.Date('${after}');
var collection = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(aoi)
 .filter(ee.Filter.eq('instrumentMode','IW'))
 .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VV'))
 .filter(ee.Filter.eq('orbitProperties_pass','DESCENDING'));
var beforeAll = collection.filterDate(beforeStart,beforeStart.advance(14,'day'));
var afterAll = collection.filterDate(afterStart,afterStart.advance(14,'day'));
var counts = ee.Dictionary({before: beforeAll.aggregate_histogram('relativeOrbitNumber_start'), after: afterAll.aggregate_histogram('relativeOrbitNumber_start')});
counts.evaluate(function(counts,error) {
 if(error) {print('Acquisition lookup failed',error);return;}
 var common = Object.keys(counts.before).filter(function(key){return counts.after[key]>0;});
 if(!common.length) {print('No matching orbit in both windows. Choose different date windows.');return;}
 var orbit = Number(common.sort(function(a,b){return Math.min(counts.before[b],counts.after[b])-Math.min(counts.before[a],counts.after[a]);})[0]);
 print('Selected relative orbit',orbit);print('Scene counts',counts);
 var before = beforeAll.filter(ee.Filter.eq('relativeOrbitNumber_start',orbit));
 var after = afterAll.filter(ee.Filter.eq('relativeOrbitNumber_start',orbit));
 var beforePower = ee.Image(10).pow(before.select('VV').median().divide(10)).focal_median(30,'circle','meters');
 var afterPower = ee.Image(10).pow(after.select('VV').median().divide(10)).focal_median(30,'circle','meters');
 var ratio = beforePower.divide(afterPower);
 var slope = ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003'));
 var permanent = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('seasonality').gte(10);
 var flood = ratio.gt(${threshold}).and(afterPower.lt(0.0631)).and(slope.lt(5)).and(permanent.not()).selfMask().clip(aoi);
 flood = flood.updateMask(flood.connectedPixelCount(100,true).gte(8));
 Map.centerObject(aoi,11);
 Map.addLayer(afterPower.log10().multiply(10).clip(aoi),{min:-25,max:0},'After VV dB');
 Map.addLayer(flood,{palette:['19c8cb']},'Candidate inundation');
 var vectors = flood.toInt().reduceToVectors({geometry:aoi,scale:30,geometryType:'polygon',eightConnected:true,maxPixels:1e9,tileScale:4});
 Export.table.toDrive({collection:vectors,description:'Sentriq_observed_flood',fileFormat:'GeoJSON'});
});
// Validate thresholds, radar shadow, land cover and timing before interpretation.
// Simplify to non-overlapping single-ring polygons before dashboard import.
`;}
