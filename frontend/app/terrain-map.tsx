'use client';
import {useEffect,useRef,useState} from 'react';
import {Plus,Minus,LocateFixed,Layers,Navigation,MapPin} from 'lucide-react';
import {Grid,Result} from '@/lib/model';
import type {FloodRasterOverlay} from '@/src/data/source';
import type {BreachMarker} from './sentriq/terrain-3d';
import {Switch} from '@/components/ui/switch';
// Near-field satellite imagery pre-fetched offline from GEE (contract §5 #19/#20, `getObserved`),
// already resolved to an absolute URL by the caller. Real bounds, not a guess.
export type GeeImageryItem={event_id:string;phase:string;date:string;url:string;bounds_latlng:number[][]};
// Public ArcGIS "export" REST endpoint for the World Imagery basemap: a single warped PNG sized to
// an arbitrary bbox, no API key or tile math needed. This is a live fetch to Esri's servers, which
// is why it is opt-in only (CLAUDE.md §11: "Localhost only... GEE only for offline prep, with cache
// + screenshot fallback" — the cached GEE imagery above is the default; this is the explicit,
// clearly-labelled exception for whoever turns it on).
function esriWorldImageryUrl(west:number,south:number,east:number,north:number):string{
 const w=1024,h=Math.max(128,Math.min(2048,Math.round(w*(north-south)/(east-west))));
 return `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=${west},${south},${east},${north}&bboxSR=4326&imageSR=4326&size=${w},${h}&format=png32&f=image`;
}
// Fallback class breaks, used until a site's contracts/styles.json (contract
// §6, GET /styles) provides real ones via the `styles` prop. Descending, to
// match the >bands[i] comparisons below. See STYLE_GUIDE.md §2.6.
const fallbackBands:Record<string,number[]>={depth:[20,10,3,1],velocity:[5,2,1,.5],arrival:[60,30,15,5]};
function bandsFor(valueKind:string,styles:any):number[]{
 const fallback=fallbackBands[valueKind]??fallbackBands.depth;
 const cfg=styles?.[valueKind==='velocity'?'velocity_p50':valueKind==='arrival'?'arrival_p50':'depth_p50'];
 const raw=cfg?.breaks_m??cfg?.breaks_ms??cfg?.breaks_s;
 if(!Array.isArray(raw)||raw.length!==4)return fallback;
 const minutes=cfg?.breaks_s?raw.map((v:number)=>v/60):raw; // contract arrival breaks are seconds; this UI works in minutes
 return [...minutes].reverse();
}
function legendLabels(valueKind:string,bands:number[]):string[]{
 const fmt=(v:number)=>{const s=String(v);return s.startsWith('0.')?s.slice(1):s;};
 const ascending=[...bands].reverse();
 const first=valueKind==='depth'?0.3:0;
 const rest=ascending[0]===first?ascending.slice(1):ascending; // don't repeat the wet threshold if a break already equals it
 return [String(first),...rest.slice(0,-1).map(fmt),fmt(rest[rest.length-1])+'+'];
}
export function TerrainMap({grid,result,frame,layer,valueKind="depth",wetMask,assets,observed,onSource,sourceIndex,picking=false,styles,rasterLayer,breachMarker,geeImagery}:{grid:Grid|null;result:Result|null;frame:number;layer:string;valueKind?:string;wetMask?:number[];assets:any[];observed?:any;onSource?:(i:number)=>void;sourceIndex?:number;picking?:boolean;styles?:any;rasterLayer?:FloodRasterOverlay|null;breachMarker?:BreachMarker|null;geeImagery?:GeeImageryItem[]}){
 const ref=useRef<HTMLCanvasElement>(null);const [zoom,setZoom]=useState(grid?.hillshade?2:1),[pan,setPan]=useState(grid?.hillshade?{x:.48,y:.1}:{x:0,y:0}),[hover,setHover]=useState<any>(null),[showAssets,setShowAssets]=useState(true),[showWater,setShowWater]=useState(true),[controls,setControls]=useState(false);const drag=useRef<any>(null);
 const depth=result?(layer==='max'?result.maxDepth:result.frames[Math.min(frame,result.frames.length-1)]?.depth):null;
 const bands=bandsFor(valueKind,styles);
 useEffect(()=>{const canvas=ref.current;if(!canvas||!grid)return;const ctx=canvas.getContext('2d');if(!ctx)return;canvas.width=grid.nx;canvas.height=grid.ny;const im=ctx.createImageData(grid.nx,grid.ny);if(depth&&showWater)for(let i=0;i<depth.length;i++){const d=depth[i];if(wetMask?wetMask[i]<.3:valueKind==='arrival'?d<0:d<.3)continue;const c=d>bands[0]?[68,86,238]:d>bands[1]?[31,140,239]:d>bands[2]?[29,198,229]:d>bands[3]?[67,222,212]:[157,245,223];im.data.set([...c,225],i*4);}ctx.putImageData(im,0,0);},[depth,grid,showWater,wetMask,valueKind,bands]);
 if(rasterLayer)return <ContractRasterMap overlay={rasterLayer} styles={styles} breachMarker={breachMarker} geeImagery={geeImagery}/>;
 if(!grid)return <div className="terrain-map" aria-label="No terrain or flood raster available"><div className="map-topline"><span className="map-chip muted">No flood raster available</span></div></div>;
 const percent=(lon:number,lat:number)=>({x:(lon-grid.west)/(grid.east-grid.west)*100,y:(grid.north-lat)/(grid.north-grid.south)*100});
 const getPoint=(e:any)=>{const b=e.currentTarget.getBoundingClientRect();const x=((e.clientX-b.left)/b.width-.5-pan.x)*100/zoom+50,y=((e.clientY-b.top)/b.height-.5-pan.y)*100/zoom+50;const ix=Math.floor(x/100*grid.nx),iy=Math.floor(y/100*grid.ny);return {x,y,i:iy*grid.nx+ix,valid:ix>=0&&iy>=0&&ix<grid.nx&&iy<grid.ny};};
 const source=sourceIndex??result?.params.sourceIndex??grid.sourceIndex;const sp={x:(source%grid.nx+.5)/grid.nx*100,y:(Math.floor(source/grid.nx)+.5)/grid.ny*100};
 return <div className={'terrain-map '+(picking?'picking':'')} onPointerDown={e=>{drag.current={x:e.clientX,y:e.clientY,px:pan.x,py:pan.y};}} onPointerMove={e=>{if(drag.current&&e.buttons===1&&!picking){const b=e.currentTarget.getBoundingClientRect();setPan({x:drag.current.px+(e.clientX-drag.current.x)/b.width,y:drag.current.py+(e.clientY-drag.current.y)/b.height});}const pt=getPoint(e);setHover(pt.valid?{...pt,depth:depth?.[pt.i]??0,z:grid.z[pt.i]}:null);}} onPointerUp={e=>{if(picking){const p=getPoint(e);if(p.valid)onSource?.(p.i);}drag.current=null;}} onPointerLeave={()=>{setHover(null);drag.current=null;}}>
  <div className="map-world" style={{transform:`translate(${pan.x*100}%,${pan.y*100}%) scale(${zoom})`}}>
   {grid.hillshade?<img src={grid.hillshade} className="relief" alt={'Hillshaded elevation data of '+grid.name} draggable={false}/>:<ElevationCanvas grid={grid}/>}
   <div className="map-grid"/><canvas ref={ref} className="flood-canvas" aria-label="Computed flood depth raster"/>
   {observed&&<svg viewBox="0 0 100 100" preserveAspectRatio="none" className="observed-polygons">{observed.features.slice(0,20000).map((f:any,i:number)=><polygon key={i} points={f.geometry.coordinates[0].map((p:number[])=>{const a=percent(p[0],p[1]);return `${a.x},${a.y}`;}).join(' ')} fill="#fcbb55" fillOpacity=".4" stroke="#fcbb55" strokeWidth=".08"/>)}</svg>}
   <div className="dam-pin" style={{left:sp.x+'%',top:sp.y+'%'}}><span><WavesMini/></span><b>INFLOW LOCATION</b><em>Selected source</em></div>
   {showAssets&&assets.map((a,i)=>{const p=percent(a.lon,a.lat);return <span key={i} className="asset-dot" style={{left:p.x+'%',top:p.y+'%'}} title={a.name}/>;})}
  </div>
  <div className="map-topline"><span className="map-chip"><span className="tiny-dot"/>{valueKind==='velocity'?'Maximum cell velocity':valueKind==='arrival'?'First wetting time':layer==='max'?'Maximum inundation':'Flood progression'}</span><span className="map-chip muted">{Math.round(grid.dx)} m grid · EPSG:4326</span></div>
  <div className="map-tools" onPointerDown={e=>e.stopPropagation()}><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(4,z+.3))}><Plus size={17}/></button><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(1,z-.3))}><Minus size={17}/></button><i/><button aria-label="Reset map view" onClick={()=>{setZoom(1);setPan({x:0,y:0});}}><LocateFixed size={17}/></button><button aria-label="Map layers" onClick={()=>setControls(!controls)}><Layers size={17}/></button></div>
  {controls&&<div className="map-layer-menu" onPointerDown={e=>e.stopPropagation()}><label>Flood depth<Switch checked={showWater} onCheckedChange={setShowWater}/></label><label>Exposure points<Switch checked={showAssets} onCheckedChange={setShowAssets}/></label></div>}
  <div className="north"><Navigation size={23}/><b>N</b></div>
  {picking&&<div className="pick-message"><MapPin size={15}/> Click a terrain cell to set the inflow source</div>}
  <div className="depth-legend"><b>{valueKind==='velocity'?'VELOCITY':valueKind==='arrival'?'ARRIVAL TIME':'WATER DEPTH'} <span>{valueKind==='velocity'?'m/s':valueKind==='arrival'?'min':'m'}</span></b><div className="color-ramp"/>{styles?<div>{legendLabels(valueKind,bands).map(v=><span key={v}>{v}</span>)}</div>:<div>Awaiting style classes</div>}</div>
  <div className="map-bottom"><span>Terrain: {grid.source}</span><span>{hover?`${hover.z.toFixed(0)} m elevation · ${(valueKind==='arrival'&&hover.depth<0?'Not reached':hover.depth.toFixed(2))} ${valueKind==='velocity'?'m/s velocity':valueKind==='arrival'?'min arrival':'m depth'}`:'Drag to pan · Hover to inspect'}</span></div>
 </div>;
}
function ContractRasterMap({overlay,styles,breachMarker,geeImagery}:{overlay:FloodRasterOverlay;styles:any;breachMarker?:BreachMarker|null;geeImagery?:GeeImageryItem[]}){
 const cfg=styles?.[overlay.styleId],colors:string[]=Array.isArray(cfg?.colors)?cfg.colors:[];
 const breaks:number[]=cfg?.breaks_m??cfg?.breaks_ms??cfg?.breaks_s??[];
 const labels=breaks.length?[String(breaks[0]),...breaks.slice(1,-1).map((n:number)=>String(n)),`${breaks[breaks.length-1]}+`]:[];
 const ramp=colors.length?`linear-gradient(90deg,${colors.join(',')})`:undefined;
 const [zoom,setZoom]=useState(1),[pan,setPan]=useState({x:0,y:0}),[controls,setControls]=useState(false),[basemap,setBasemap]=useState<'none'|'cached'|'live'>('cached'),[breachOpen,setBreachOpen]=useState(false);
 const drag=useRef<any>(null);
 // Contract §1.3: bounds_latlng is [[south_lat,west_lon],[north_lat,east_lon]] from every path,
 // including the real direct-solver path -- fixed at the source (docs/progress.md 2026-09-28
 // "STEP 2"); this used to need a per-path un-swap keyed on floodQuery.method, not anymore.
 const [[south,west],[north,east]]=overlay.boundsLatLng;
 const pct=(lon:number,lat:number)=>({x:(lon-west)/(east-west)*100,y:(north-lat)/(north-south)*100});
 const cachedTiles=(geeImagery??[]).map(item=>{
  const [iSouth,iWest]=item.bounds_latlng[0],[iNorth,iEast]=item.bounds_latlng[1];
  if(iEast<west||iWest>east||iNorth<south||iSouth>north)return null; // no overlap with this query's extent
  const tl=pct(iWest,iNorth),br=pct(iEast,iSouth);
  return {...item,left:tl.x,top:tl.y,width:br.x-tl.x,height:br.y-tl.y};
 }).filter((t):t is GeeImageryItem&{left:number;top:number;width:number;height:number}=>!!t)
  .sort((a,b)=>a.date.localeCompare(b.date)); // oldest first, so the most recent acquisition draws last (on top)
 const breachPos=breachMarker?pct(breachMarker.lonLat[0],breachMarker.lonLat[1]):null;
 const transform=`translate(${pan.x*100}%,${pan.y*100}%) scale(${zoom})`;
 const onPointerDown=(e:any)=>{drag.current={x:e.clientX,y:e.clientY,px:pan.x,py:pan.y};};
 const onPointerMove=(e:any)=>{if(drag.current&&e.buttons===1){const b=e.currentTarget.getBoundingClientRect();setPan({x:drag.current.px+(e.clientX-drag.current.x)/b.width,y:drag.current.py+(e.clientY-drag.current.y)/b.height});}};
 const onPointerUp=()=>{drag.current=null;};
 return <div className="terrain-map contract-raster-map" data-layer-id={overlay.layerId} data-style-id={overlay.styleId} data-bounds-latlng={JSON.stringify(overlay.boundsLatLng)} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}>
  <div className="map-world" style={{transform}}>
   {basemap==='live'&&<img className="relief" src={esriWorldImageryUrl(west,south,east,north)} alt="Live satellite basemap (Esri World Imagery)" draggable={false} onError={e=>{e.currentTarget.dataset.loadError='true';}}/>}
   {basemap==='cached'&&cachedTiles.map((t,i)=><img key={`${t.event_id}-${t.date}-${i}`} src={t.url} alt={`${t.event_id} ${t.phase} satellite image, acquired ${t.date}`} draggable={false} style={{position:'absolute',left:t.left+'%',top:t.top+'%',width:t.width+'%',height:t.height+'%'}}/>)}
   <img className="contract-flood-raster" src={overlay.url} alt={`Backend flood raster: ${overlay.layerId}`} data-artifact-url={overlay.url} onError={e=>{e.currentTarget.dataset.loadError='true';}}/>
   <div className="map-grid"/>
  </div>
  {/* Rendered after the topline/tools/legend chips (DOM order, no z-index needed) so the marker
      is never painted over by them, wherever the point happens to fall; shares map-world's
      transform so it pans/zooms with the raster instead of sitting fixed like the HUD chips. */}
  <div className="map-topline"><span className="map-chip"><span className="tiny-dot"/>{layerTitle(overlay.layerId)}</span><span className="map-chip muted">WGS 84{overlay.unit?` · ${overlay.unit}`:''}</span></div>
  <div className="map-tools" onPointerDown={e=>e.stopPropagation()}><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(4,z+.3))}><Plus size={17}/></button><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(1,z-.3))}><Minus size={17}/></button><i/><button aria-label="Reset map view" onClick={()=>{setZoom(1);setPan({x:0,y:0});}}><LocateFixed size={17}/></button><button aria-label="Map layers" onClick={()=>setControls(!controls)}><Layers size={17}/></button></div>
  {controls&&<div className="map-layer-menu" onPointerDown={e=>e.stopPropagation()}><label>Satellite basemap<Switch checked={basemap!=='none'} onCheckedChange={v=>setBasemap(v?'cached':'none')}/></label>{basemap!=='none'&&<label>Live imagery (needs internet)<Switch checked={basemap==='live'} onCheckedChange={v=>setBasemap(v?'live':'cached')}/></label>}</div>}
  <div className="north"><Navigation size={23}/><b>N</b></div>
  <div className="depth-legend"><b>{layerTitle(overlay.layerId).toUpperCase()} <span>{overlay.unit??''}</span></b><div className="color-ramp" style={ramp?{background:ramp}:undefined}/><div>{labels.length?labels.map((label,i)=><span key={`${label}-${i}`}>{label}</span>):<span>Contract styles</span>}</div></div>
  <div className="map-bottom"><span>Georeferenced flood layer</span><span>{basemap==='live'?'Satellite: Esri World Imagery · live, requires internet · date varies by area':basemap==='cached'?(cachedTiles.length?`Satellite: ${cachedTiles[cachedTiles.length-1].event_id} · acquired ${cachedTiles[cachedTiles.length-1].date} · cached (offline)`:'No cached satellite imagery covers this extent'):'Backend-rendered artifact'}</span></div>
  <div className="marker-layer" style={{transform,position:'absolute',inset:0,pointerEvents:'none'}}>
   {breachPos&&<span title="Breach location" onPointerDown={e=>e.stopPropagation()} onClick={()=>setBreachOpen(o=>!o)} onMouseEnter={()=>setBreachOpen(true)} onMouseLeave={()=>setBreachOpen(false)} className="asset-dot" style={{left:breachPos.x+'%',top:breachPos.y+'%',width:11,height:11,background:'#e5453f',borderColor:'#7a1f1c',boxShadow:'0 0 0 4px #e5453f33',cursor:'pointer',pointerEvents:'auto'}}/>}
   {breachPos&&breachOpen&&<div style={{position:'absolute',left:breachPos.x+'%',top:breachPos.y+'%',transform:'translate(14px,-50%)',background:'#372e1d',color:'#cab28e',border:'1px solid #4e422e',borderRadius:6,padding:'8px 10px',fontSize:11,lineHeight:1.6,width:200,pointerEvents:'none'}}><strong style={{display:'block',marginBottom:4,color:'#e6edf3'}}>{breachMarker!.title}</strong>{breachMarker!.lines.map((l,i)=><div key={i}>{l}</div>)}<small style={{display:'block',marginTop:4,opacity:.85}}>{breachMarker!.caveat}</small></div>}
  </div>
 </div>;
}
// Readable names for the contract layer ids shown on the map chips and legend.
const LAYER_TITLES:Record<string,string>={depth_p50:'Maximum depth',depth_high:'Depth · high confidence',depth_possible:'Depth · possible',p_inundation:'Inundation probability',velocity_p50:'Maximum velocity',arrival_p50:'Arrival time',timeline_depth:'Flood depth'};
function layerTitle(id:string){return LAYER_TITLES[id]??id.replaceAll('_',' ');}
function WavesMini(){return <svg width="18" height="18" viewBox="0 0 20 20"><path d="M2 6q4-5 8 0t8 0M2 12q4-5 8 0t8 0" fill="none" stroke="currentColor" strokeWidth="2"/></svg>}
function ElevationCanvas({grid}:{grid:Grid}){const ref=useRef<HTMLCanvasElement>(null);useEffect(()=>{const c=ref.current;if(!c)return;c.width=grid.nx;c.height=grid.ny;const ctx=c.getContext('2d')!;const im=ctx.createImageData(grid.nx,grid.ny),min=Math.min(...grid.z),range=Math.max(...grid.z)-min||1;grid.z.forEach((v,i)=>{const t=(v-min)/range;im.data.set([25+t*60,42+t*70,39+t*67,255],i*4);});ctx.putImageData(im,0,0);},[grid]);return <canvas className="relief" ref={ref}/>;}
