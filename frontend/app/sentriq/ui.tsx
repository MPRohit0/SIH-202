'use client';
import {useEffect,useState} from 'react';
import {Slider} from '@/components/ui/slider';
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from '@/components/ui/select';
import {Check,ArrowUpRight,Navigation,ShieldCheck} from 'lucide-react';
export function SelectField({value,onChange,options,label,ariaLabel}:any){return <label className="s-field">{label&&<span>{label}</span>}<Select value={value} onValueChange={onChange}><SelectTrigger aria-label={ariaLabel??label??'Select option'} className="s-select"><SelectValue/></SelectTrigger><SelectContent>{options.map(([v,l]:string[])=><SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></label>}
export function Num({label,value,onChange,min=0,max=10000,step=1,unit}:any){const [draft,setDraft]=useState(String(value));useEffect(()=>setDraft(String(value)),[value]);return <label className="s-field"><span>{label}</span><div className="num-input"><input type="number" aria-label={label} min={min} max={max} step={step} value={draft} onChange={e=>{setDraft(e.target.value);const v=Number(e.target.value);if(e.target.value!==''&&Number.isFinite(v)&&v>=min&&v<=max)onChange(v);}} onBlur={()=>{const v=Number(draft),next=draft!==''&&Number.isFinite(v)?Math.min(max,Math.max(min,v)):value;setDraft(String(next));onChange(next);}}/><small>{unit}</small></div></label>}
export function Range({label,value,onChange,min=25,max=100,step=1,unit='%',disabled=false}:any){return <div className="s-range"><div><span>{label}</span><strong>{value}<small>{unit}</small></strong></div><Slider aria-label={label} value={[value]} min={min} max={max} step={step} disabled={disabled} onValueChange={a=>onChange(a[0])}/><div className="range-labels"><span>{min}{unit}</span><span>{max}{unit}</span></div></div>}
export function Badge({children,tone='neutral'}:any){return <span className={'s-badge '+tone}>{tone==='ready'&&<Check size={11}/>} {children}</span>}
export function MiniMetric({label,value,unit}:any){return <div className="mini-metric"><span>{label}</span><strong>{value}<small>{unit}</small></strong></div>}
// m5_specs.md §6 confidence rule: HIGH/MODERATE/LOW with a stated reason.
// Shared by the Simulation screen's ScenarioConfidencePanel (app.tsx) and the
// Compare page (compare-view.tsx) -- the compare page's own S/C/U chip, which
// shows the real level (displayConfidence() in app.tsx force-shows HIGH
// elsewhere and is deliberately left untouched).
export function ConfidenceBadge({level,reasonKey}:{level:string;reasonKey?:string|null}){
 const tone=level==='HIGH'?'ready':level==='MODERATE'?'amber':'danger';
 return <div className="confidence-box"><ShieldCheck size={16}/><div><strong><Badge tone={tone}>{level}</Badge></strong>{reasonKey&&<p>{reasonKey}</p>}</div></div>;
}
export function Empty({title,children,icon:Icon}:any){return <div className="s-empty">{Icon&&<Icon size={29}/>}<h3>{title}</h3><p>{children}</p></div>}
export function SourceLink({href,children}:any){return <a className="source-link" href={href} target="_blank" rel="noreferrer">{children}<ArrowUpRight size={15}/></a>}
// A geometry-accurate outline of a GEE lake_latest FeatureCollection, scaled to its own bounding
// box (padded) rather than a shared terrain grid -- the flood-simulation Grid used by TerrainMap
// is not available on the monitoring path (no DEM/flood domain is loaded there), so this reuses
// TerrainMap's visual language (`.terrain-map`/`.map-topline`/`.map-chip`/`.north`) without its
// grid dependency. It draws the polygon only, not a photographic satellite basemap -- there is no
// tile provider wired into this app (frontend/CLAUDE.md: no new UI libraries) -- so the caption
// says so rather than implying imagery that isn't there.
export function LakeOutlineMap({fc,label}:{fc:any;label?:string}){
 const rings:number[][][]=fc.features.flatMap((f:any)=>f.geometry.type==='MultiPolygon'?f.geometry.coordinates.map((p:number[][][])=>p[0]):f.geometry.type==='Polygon'?[f.geometry.coordinates[0]]:[]);
 const coords=rings.flat();
 if(!coords.length)return null;
 const lons=coords.map((c:number[])=>c[0]),lats=coords.map((c:number[])=>c[1]);
 const west=Math.min(...lons),east=Math.max(...lons),south=Math.min(...lats),north=Math.max(...lats);
 const padX=(east-west)*0.18||0.001,padY=(north-south)*0.18||0.001;
 const bounds={west:west-padX,east:east+padX,south:south-padY,north:north+padY};
 const percent=(lon:number,lat:number)=>({x:(lon-bounds.west)/(bounds.east-bounds.west)*100,y:(bounds.north-lat)/(bounds.north-bounds.south)*100});
 return <div className="terrain-map lake-outline-map">
  <div className="map-world">
   <div className="map-grid"/>
   <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="observed-polygons">
    {rings.map((ring,i)=><polygon key={i} points={ring.map(p=>{const a=percent(p[0],p[1]);return `${a.x},${a.y}`;}).join(' ')} fill="#4fd6ff" fillOpacity=".35" stroke="#4fd6ff" strokeWidth=".3"/>)}
   </svg>
  </div>
  <div className="map-topline"><span className="map-chip"><span className="tiny-dot"/>{label??'Lake extent'}</span><span className="map-chip muted">EPSG:4326 geometry · not a satellite photo</span></div>
  <div className="north"><Navigation size={23}/><b>N</b></div>
 </div>;
}
