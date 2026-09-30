'use client';
// Compare page (design/target-state-preview, preview mode only): two live,
// grid-computed cards -- SPH vs D-Flow FM (Card A) and Emulator vs physics
// (Card B) -- fed by the demo engine's compare workbench
// (src/data/preview/engine/compare.ts). Reuses existing components/classes
// only (frontend/CLAUDE.md); the only new CSS is the 3-column map row and the
// confidence chip's layout in src/preview/preview.css.
import {useEffect,useState} from 'react';
import {AlertTriangle,Box,Layers,Pause,Play,RotateCcw,GitCompareArrows} from 'lucide-react';
import {Tabs,TabsList,TabsTrigger} from '@/components/ui/tabs';
import {Select,SelectTrigger,SelectValue,SelectContent,SelectGroup,SelectLabel,SelectItem} from '@/components/ui/select';
import {Table,TableHeader,TableBody,TableRow,TableHead,TableCell} from '@/components/ui/table';
import {Slider} from '@/components/ui/slider';
import {ChartContainer,ChartTooltip,ChartTooltipContent} from '@/components/ui/chart';
import {ComposedChart,Scatter,Line,XAxis,YAxis,CartesianGrid} from 'recharts';
import * as source from '@/src/data/source';
import type {CompareWorkbench} from '@/src/data/preview/engine/compare';
import {THRESHOLDS_M, TIME_FRAME_COUNT, type Domain} from '@/src/data/preview/engine/compare';
import type {Scene3DArrays} from '@/src/data/source';
import {nf} from '@/lib/sentriq';
import uiText from '@/src/content/ui_text.json';
import Terrain3D from './terrain-3d';
import {TerrainMap} from '../terrain-map';
import {Badge,Empty,SelectField,ConfidenceBadge,MiniMetric} from './ui';
import PreviewWatermark from '@/src/preview/PreviewWatermark';
import type {SiteSummary} from '@/src/data/source';

const fmt=(v:unknown)=>{const n=typeof v==='number'?v:NaN;return Number.isFinite(n)?nf(n,3):'—';};
const caveatText=(id:string)=>(uiText.floodQuery.caveats as Record<string,string>)[id]??uiText.floodQuery.unknownCaveat;

function overlayFor(layerId:string,url:string,bounds:[[number,number],[number,number]],styleId:'depth_p50'|'depth_diff'):source.FloodRasterOverlay{
 return {layerId,url,boundsLatLng:bounds,styleId,unit:'m'};
}

/** Loads a scene's terrain/flood Float32Arrays for the 3D tab. Keyed by the
 * scene's own data: URL (which embeds the actual grid bytes), not query_id --
 * the compare workbench's query_id is stable across a domain/threshold/time
 * change for the same site+inputs (only the underlying grid values change),
 * so keying on query_id would silently reuse stale arrays. */
function useSceneArrays(scene:Awaited<ReturnType<typeof source.getScene3d>>|null|undefined):Scene3DArrays|null{
 const [arrays,setArrays]=useState<Scene3DArrays|null>(null);
 useEffect(()=>{if(!scene){setArrays(null);return;}let current=true;source.getScene3dArrays(scene).then(a=>{if(current)setArrays(a);}).catch(()=>{if(current)setArrays(null);});return()=>{current=false;};},[scene?.terrain.url,scene?.flood_surface.url]);
 return arrays;
}

const STAT_ROWS:Array<[string,keyof CompareWorkbench['stats']]> = [
 ['Intersection over union (IoU)','iou'],['F1 score','f1_0_3'],['True positive rate','tpr'],['False positive rate','fpr'],
 ['Wet-depth RMSE (m)','depth_rmse_wet_m'],['Wet-depth RMSLE','depth_rmsle'],['Peak-depth bias (m)','peak_depth_bias_m'],['Arrival-time MAE (s)','arrival_mae_s'],
];

export default function CompareView({sites}:{sites:SiteSummary[]}){
 const [siteId,setSiteId]=useState('');
 const [domain,setDomain]=useState<Domain>('nf1');
 const [threshold,setThreshold]=useState(0.3);
 const [tIndex,setTIndex]=useState(TIME_FRAME_COUNT-1);
 const [playing,setPlaying]=useState(false);
 const [mapMode,setMapMode]=useState<'2d'|'3d'>('2d');
 const [runId,setRunId]=useState('HO-1');
 const [wb,setWb]=useState<CompareWorkbench|null>(null);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState(false);

 useEffect(()=>{if(!siteId&&sites.length)setSiteId(sites[0].site_id);},[sites]);
 useEffect(()=>{setRunId('HO-1');},[siteId]);
 useEffect(()=>{
  if(!siteId)return;
  let current=true;setLoading(true);setError(false);
  source.getCompareWorkbench(siteId,{domain,threshold,tIndex,runId}).then(w=>{if(current)setWb(w);}).catch(()=>{if(current)setError(true);}).finally(()=>{if(current)setLoading(false);});
  return()=>{current=false;};
 },[siteId,domain,threshold,tIndex,runId]);
 useEffect(()=>{if(!playing)return;const id=setInterval(()=>setTIndex(t=>{if(t>=TIME_FRAME_COUNT-1){setPlaying(false);return t;}return t+1;}),260);return()=>clearInterval(id);},[playing]);

 const sphArrays=useSceneArrays(wb?.sphScene);
 const fmArrays=useSceneArrays(wb?.fmScene);
 const truthArrays=useSceneArrays(wb?.selectedRun.truthScene);
 const predArrays=useSceneArrays(wb?.selectedRun.predScene);

 if(!siteId||(loading&&!wb))return <div className="job-progress"><span>Loading model comparison…</span></div>;
 if(error&&!wb)return <div className="s-notice warning"><AlertTriangle size={16}/><span>{uiText.comparison.error}</span></div>;
 if(!wb)return <Empty title={uiText.comparison.empty}>{uiText.comparison.emptyDetail}</Empty>;

 const domainLengthM=wb.ny*wb.cellM;
 const caveatIds=['preview_simulated','arrival_proxy',...(domain==='far'?['sph_far_field_illustrative']:[])];
 const sphOverlay=overlayFor('depth_sph',wb.sphLayerUrl,wb.bounds,'depth_p50');
 const fmOverlay=overlayFor('depth_fm',wb.fmLayerUrl,wb.bounds,'depth_p50');
 const diffOverlay=overlayFor('depth_diff_nearfield',wb.diffLayerUrl,wb.bounds,'depth_diff');
 const predOverlay=overlayFor('depth_pred',wb.selectedRun.predLayerUrl,wb.bounds,'depth_p50');
 const truthOverlay=overlayFor('depth_true',wb.selectedRun.truthLayerUrl,wb.bounds,'depth_p50');
 const runDiffOverlay=overlayFor('depth_diff_emulator',wb.selectedRun.diffLayerUrl,wb.bounds,'depth_diff');
 const heldOutRuns=wb.runs.filter(r=>r.kind==='holdout');
 const loocvRuns=wb.runs.filter(r=>r.kind==='loocv');
 const poiMax=Math.max(0.01,...wb.selectedRun.poiPairs.flatMap(p=>[p.truth_m,p.pred_m]));
 const diagonal=[{truth_m:0,pred_m:0},{truth_m:poiMax,pred_m:poiMax}];

 return <>
  <div className="command-strip">
   <div><GitCompareArrows size={16}/><strong>Compare page</strong><span>Live preview simulation -- not real solver output</span></div>
   <SelectField ariaLabel="Site" value={siteId} onChange={setSiteId} options={sites.map(s=>[s.site_id,s.name])}/>
  </div>

  <section className="s-panel no-padding">
   <div className="engine-header">
    <span className="engine-symbol">∴</span>
    <div><p className="eyebrow">Domain: {domain==='nf1'?'Near-field reach (NF-1)':'Far-field reach'}, 0-{Math.round(domainLengthM)} m</p><h2>SPH vs D-Flow FM (simulated)</h2><p>Time window: {nf(wb.timeWindowS,0)} s</p></div>
    <Badge tone="ready">AVAILABLE</Badge>
   </div>
   <div style={{padding:'0 16px'}}>
    <div className="two-fields">
     <Tabs value={domain} onValueChange={v=>setDomain(v as Domain)}><TabsList><TabsTrigger value="nf1">NF-1 (near-field)</TabsTrigger><TabsTrigger value="far">Far-field</TabsTrigger></TabsList></Tabs>
     <Tabs value={mapMode} onValueChange={v=>setMapMode(v as '2d'|'3d')}><TabsList><TabsTrigger value="3d"><Box size={14}/>3D</TabsTrigger><TabsTrigger value="2d"><Layers size={14}/>2D</TabsTrigger></TabsList></Tabs>
    </div>
    <div className="layer-pills">{THRESHOLDS_M.map(t=><button key={t} className={threshold===t?'selected':''} onClick={()=>setThreshold(t)}>{t} m</button>)}</div>
    <div className="playback">
     <button aria-label={playing?'Pause playback':'Play playback'} onClick={()=>{if(tIndex>=TIME_FRAME_COUNT-1)setTIndex(0);setPlaying(!playing);}}>{playing?<Pause size={16}/>:<Play size={16}/>}</button>
     <strong>T + {nf(wb.frameTimesS[tIndex],0)} <small>s</small></strong>
     <Slider aria-label="Compare time" value={[tIndex]} min={0} max={TIME_FRAME_COUNT-1} step={1} onValueChange={v=>{setTIndex(v[0]);setPlaying(false);}}/>
     <span>{nf(wb.timeWindowS,0)} s</span>
     <button aria-label="Reset time" onClick={()=>{setTIndex(0);setPlaying(false);}}><RotateCcw size={15}/></button>
    </div>
    <div className="compare-map-row">
     <div><span className="compare-map-caption">DualSPHysics (simulated)</span><PreviewWatermark small>{mapMode==='3d'?<Terrain3D grid={null} result={null} scene={wb.sphScene} arrays={sphArrays} label="SPH"/>:<TerrainMap grid={null} result={null} frame={0} layer="max" assets={[]} rasterLayer={sphOverlay}/>}</PreviewWatermark></div>
     <div><span className="compare-map-caption">D-Flow FM (simulated)</span><PreviewWatermark small>{mapMode==='3d'?<Terrain3D grid={null} result={null} scene={wb.fmScene} arrays={fmArrays} label="FM"/>:<TerrainMap grid={null} result={null} frame={0} layer="max" assets={[]} rasterLayer={fmOverlay}/>}</PreviewWatermark></div>
     <div><span className="compare-map-caption">SPH − D-Flow FM (2D only)</span><PreviewWatermark small><TerrainMap grid={null} result={null} frame={0} layer="max" assets={[]} rasterLayer={diffOverlay}/></PreviewWatermark></div>
    </div>
    <div className="compare-kpis">
     <MiniMetric label={uiText.comparison.iou} value={fmt(wb.stats.iou)} unit=""/>
     <MiniMetric label={uiText.comparison.f1} value={fmt(wb.stats.f1_0_3)} unit=""/>
     <MiniMetric label={uiText.comparison.depthRmse} value={fmt(wb.stats.depth_rmse_wet_m)} unit="m"/>
     <MiniMetric label={uiText.comparison.velocityMae} value={fmt(wb.stats.velocity_mae_ms)} unit="m/s"/>
    </div>
    <Table><TableHeader><TableRow><TableHead>Metric</TableHead><TableHead>Value</TableHead></TableRow></TableHeader><TableBody>
     {STAT_ROWS.map(([label,key])=><TableRow key={key as string}><TableCell>{label}</TableCell><TableCell data-testid={`compare-stat-${String(key)}`}>{fmt(wb.stats[key])}</TableCell></TableRow>)}
    </TableBody></Table>
    {wb.probes.length>0&&<Table><TableHeader><TableRow><TableHead>{uiText.comparison.probe}</TableHead><TableHead>{uiText.comparison.delftArrival}</TableHead><TableHead>{uiText.comparison.sphArrival}</TableHead><TableHead>{uiText.comparison.difference}</TableHead></TableRow></TableHeader><TableBody>
     {wb.probes.map(p=><TableRow key={p.poi_id}><TableCell>{p.name}</TableCell><TableCell>{nf(p.arrival_delft3d_s,0)} s</TableCell><TableCell>{nf(p.arrival_sph_s,0)} s</TableCell><TableCell>{nf(p.diff_s,0)} s</TableCell></TableRow>)}
    </TableBody></Table>}
    <p className="fine-print">{caveatText('arrival_proxy')}</p>
   </div>
  </section>

  <section className="s-panel no-padding">
   <div className="engine-header">
    <span className="engine-symbol">▦</span>
    <div><p className="eyebrow">Held-out run: {wb.selectedRun.run_id}</p><h2>Emulator vs physics</h2><p>Scenario: {domain==='nf1'?'near-field':'far-field'} · {wb.selectedRun.label}</p></div>
    <Badge tone="ready">AVAILABLE</Badge>
   </div>
   <div style={{padding:'0 16px'}}>
    <label className="s-field"><span>Held-out / LOOCV run</span>
     <Select value={runId} onValueChange={setRunId}>
      <SelectTrigger aria-label="Emulator run" className="s-select"><SelectValue/></SelectTrigger>
      <SelectContent>
       <SelectGroup><SelectLabel>Held-out</SelectLabel>{heldOutRuns.map(r=><SelectItem key={r.run_id} value={r.run_id}>{r.run_id}</SelectItem>)}</SelectGroup>
       <SelectGroup><SelectLabel>LOOCV folds</SelectLabel>{loocvRuns.map(r=><SelectItem key={r.run_id} value={r.run_id}>{r.label}</SelectItem>)}</SelectGroup>
      </SelectContent>
     </Select>
    </label>
    <div className="compare-map-row">
     <div><span className="compare-map-caption">Predicted (GP emulator)</span><PreviewWatermark small>{mapMode==='3d'?<Terrain3D grid={null} result={null} scene={wb.selectedRun.predScene} arrays={predArrays} label="Predicted"/>:<TerrainMap grid={null} result={null} frame={0} layer="max" assets={[]} rasterLayer={predOverlay}/>}</PreviewWatermark></div>
     <div><span className="compare-map-caption">True (FM physics)</span><PreviewWatermark small>{mapMode==='3d'?<Terrain3D grid={null} result={null} scene={wb.selectedRun.truthScene} arrays={truthArrays} label="True"/>:<TerrainMap grid={null} result={null} frame={0} layer="max" assets={[]} rasterLayer={truthOverlay}/>}</PreviewWatermark></div>
     <div><span className="compare-map-caption">Predicted − true (2D only)</span><PreviewWatermark small><TerrainMap grid={null} result={null} frame={0} layer="max" assets={[]} rasterLayer={runDiffOverlay}/></PreviewWatermark></div>
    </div>
    <div className="compare-kpis">
     <MiniMetric label={uiText.comparison.depthRmse} value={fmt(wb.selectedRun.metrics.rmse_m)} unit="m"/>
     <MiniMetric label="Extent F1 (0.3 m)" value={fmt(wb.selectedRun.metrics.f1)} unit=""/>
     <MiniMetric label="Arrival RMSE" value={fmt(wb.selectedRun.metrics.arrival_rmse_s)} unit="s"/>
     <MiniMetric label="90% interval coverage" value={fmt(wb.selectedRun.metrics.coverage_90*100)} unit="%"/>
    </div>
    <ConfidenceBadge level={wb.selectedRun.confidence.level} reasonKey={wb.selectedRun.confidence.reason_key}/>
    {wb.selectedRun.poiPairs.length>0&&<ChartContainer config={{pred_m:{label:'Predicted depth (m)',color:'#4fd6ff'}}} className="monitoring-chart">
     <ComposedChart margin={{left:4,right:8,top:4,bottom:0}}>
      <CartesianGrid strokeDasharray="3 3"/>
      <XAxis type="number" dataKey="truth_m" name="True depth (m)" tick={{fontSize:9}} tickMargin={6}/>
      <YAxis type="number" dataKey="pred_m" name="Predicted depth (m)" tick={{fontSize:9}} width={44}/>
      <ChartTooltip content={<ChartTooltipContent/>}/>
      <Line data={diagonal} dataKey="pred_m" stroke="#5b6b76" strokeDasharray="4 3" dot={false} isAnimationActive={false} name="1:1"/>
      <Scatter data={wb.selectedRun.poiPairs} dataKey="pred_m" fill="var(--color-pred_m)" name="POI"/>
     </ComposedChart>
    </ChartContainer>}
   </div>
  </section>

  <section className="s-panel">
   <div className="panel-title"><h2>{uiText.comparison.gpLinearTitle}</h2><Badge>{uiText.comparison.notValidation}</Badge></div>
   <div className="agreement-grid">
    <MiniMetric label={uiText.comparison.gpIou} value={fmt(wb.gpVsLinear.iou_median_gp)} unit=""/>
    <MiniMetric label={uiText.comparison.linearIou} value={fmt(wb.gpVsLinear.iou_median_linear)} unit=""/>
    <MiniMetric label={uiText.comparison.gpArrival} value={fmt(wb.gpVsLinear.arrival_mae_s_gp)} unit="s"/>
    <MiniMetric label={uiText.comparison.linearArrival} value={fmt(wb.gpVsLinear.arrival_mae_s_linear)} unit="s"/>
   </div>
   <p className="fine-print">{uiText.comparison.whenToUse}</p>
  </section>

  {caveatIds.map(id=><div className={id==='sph_far_field_illustrative'?'s-notice warning':'s-notice'} key={id}><AlertTriangle size={16}/><span>{caveatText(id)}</span></div>)}
 </>;
}
