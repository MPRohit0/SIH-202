'use client';
import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import type {Grid,Result} from '@/lib/model';
import type {Scene3DResponse} from '@/src/data/api';
import type {Scene3DArrays} from '@/src/data/source';
import {RotateCcw,Move3D,Mountain} from 'lucide-react';
import TerrainCanvas from './terrain-canvas';

// Real scenes are cropped to the wet flood_surface bounding box (the actual reach
// with water, e.g. South Lhonak -> Chungthang) plus a cell margin, then subsampled
// to about this many samples per axis -- roughly the same vertex budget as the
// legacy synthetic window below, so perf/style stay the same.
const REAL_TARGET_SAMPLES = 140;
const REAL_CROP_MARGIN_CELLS = 12;

function realCropBounds(width: number, height: number, flood: Float32Array, nodata: number) {
  let minR = Infinity, maxR = -Infinity, minC = Infinity, maxC = -Infinity;
  for (let r = 0; r < height; r++) {
    const base = r * width;
    for (let c = 0; c < width; c++) {
      if (flood[base + c] !== nodata) {
        if (r < minR) minR = r; if (r > maxR) maxR = r;
        if (c < minC) minC = c; if (c > maxC) maxC = c;
      }
    }
  }
  if (!Number.isFinite(minR)) return {r0: 0, r1: height - 1, c0: 0, c1: width - 1};
  return {
    r0: Math.max(0, minR - REAL_CROP_MARGIN_CELLS), r1: Math.min(height - 1, maxR + REAL_CROP_MARGIN_CELLS),
    c0: Math.max(0, minC - REAL_CROP_MARGIN_CELLS), c1: Math.min(width - 1, maxC + REAL_CROP_MARGIN_CELLS),
  };
}

function sampleIndices(lo: number, hi: number, target: number) {
  const span = hi - lo + 1;
  const step = Math.max(1, Math.ceil(span / target));
  const out: number[] = [];
  for (let v = lo; v <= hi; v += step) out.push(v);
  if (out[out.length - 1] !== hi) out.push(hi);
  return out;
}

export default function Terrain3D({grid,result,frame=24,mode='terrain',className='',wire=false,scene=null,arrays=null,label}:{grid:Grid|null;result:Result|null;frame?:number;mode?:string;className?:string;wire?:boolean;scene?:Scene3DResponse|null;arrays?:Scene3DArrays|null;label?:string}){
 const [reset,setReset]=useState(0);const host=useRef<HTMLDivElement>(null),engine=useRef<any>(null),[failed,setFailed]=useState(false);const latest=useRef({result,frame});latest.current={result,frame};
 const real=!!(scene&&arrays);
 useEffect(()=>{const el=host.current;if(!el)return;if(!real&&!grid)return;let renderer:THREE.WebGLRenderer;try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'high-performance'});}catch{setFailed(true);return;}renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.6));renderer.setClearColor(0x07131e,0);renderer.outputColorSpace=THREE.SRGBColorSpace;el.appendChild(renderer.domElement);
 const scn=new THREE.Scene(),camera=new THREE.PerspectiveCamera(39,1,.1,120);camera.position.set(9,11.5,11);const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,1.1,0);controls.enableDamping=true;controls.enablePan=false;controls.minDistance=8;controls.maxDistance=25;controls.maxPolarAngle=Math.PI*.47;controls.minPolarAngle=.28;controls.autoRotate=false;controls.enableZoom=true;controls.zoomSpeed=.6;
 scn.add(new THREE.HemisphereLight(0x9acee0,0x071421,2.5));const sun=new THREE.DirectionalLight(0xd8f2ff,3.4);sun.position.set(-5,12,4);scn.add(sun);const rim=new THREE.DirectionalLight(0x1c788b,2);rim.position.set(8,3,-9);scn.add(rim);
 const ground=new THREE.GridHelper(19,38,0x18323c,0x0f2935);ground.position.y=-.4;scn.add(ground);
 let water:THREE.Group|null=null,updateWater:(()=>void)|null=null;

 if(real&&scene&&arrays){
  // Real scene: crop to the wet flood_surface bounding box (the actual flooded reach)
  // plus a margin, then subsample -- so the default camera already frames the reach
  // instead of the whole far-field DEM.
  const {width,height,nodata:terrainNodata}=scene.terrain;
  const floodNodata=scene.flood_surface.nodata;
  const bounds=realCropBounds(width,height,arrays.flood,floodNodata);
  const sampleRows=sampleIndices(bounds.r0,bounds.r1,REAL_TARGET_SAMPLES);
  const sampleCols=sampleIndices(bounds.c0,bounds.c1,REAL_TARGET_SAMPLES);
  const cols=sampleCols.length,rows=sampleRows.length;
  const minZ=scene.terrain.min_elev_m??0,maxZ=scene.terrain.max_elev_m??minZ+1,range=Math.max(maxZ-minZ,1);
  const ve=scene.frame.vertical_exaggeration;
  const scaleY=(3.1*(ve/1.5))/range;
  const bed=(r:number,c:number)=>{const v=arrays.terrain[r*width+c];return v===terrainNodata?minZ:v;};
  const worldXY=(ri:number,ci:number)=>({x:(ci/(cols-1))*12-6,y:(ri/(rows-1))*10-5});
  const worldPoint=(ri:number,ci:number,z:number)=>new THREE.Vector3((ci/(cols-1))*12-6,(z-minZ)*scaleY,(ri/(rows-1))*10-5);

  const vertices:number[]=[],colors:number[]=[],indices:number[]=[];const color=new THREE.Color();
  for(let ri=0;ri<rows;ri++)for(let ci=0;ci<cols;ci++){const z=bed(sampleRows[ri],sampleCols[ci]);const p=worldPoint(ri,ci,z);vertices.push(p.x,p.y,p.z);const t=(z-minZ)/range;color.setRGB(.11+t*.19,.21+t*.24,.24+t*.23);if(z%120<12)color.multiplyScalar(.68);colors.push(color.r,color.g,color.b);}
  for(let ri=0;ri<rows-1;ri++)for(let ci=0;ci<cols-1;ci++){const a=ri*cols+ci;indices.push(a,a+cols,a+1,a+1,a+cols,a+cols+1);}
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geo.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geo.setIndex(indices);geo.computeVertexNormals();
  const material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:.94,metalness:.12,side:THREE.DoubleSide});const terrainMesh=new THREE.Mesh(geo,material);scn.add(terrainMesh);
  const meshLines=new THREE.LineSegments(new THREE.WireframeGeometry(geo),new THREE.LineBasicMaterial({color:0x4c919c,transparent:true,opacity:wire?.17:.065}));scn.add(meshLines);

  // Exposed sides, sampled from the same crop perimeter as the legacy synthetic block.
  const edge:number[]=[];const ring:[number,number][]=[];for(let ci=0;ci<cols;ci++)ring.push([0,ci]);for(let ri=1;ri<rows;ri++)ring.push([ri,cols-1]);for(let ci=cols-2;ci>=0;ci--)ring.push([rows-1,ci]);for(let ri=rows-2;ri>=0;ri--)ring.push([ri,0]);
  for(let i=0;i<ring.length;i++){const [ar,ac]=ring[i],[br,bc]=ring[(i+1)%ring.length];const a=worldPoint(ar,ac,bed(sampleRows[ar],sampleCols[ac])),b=worldPoint(br,bc,bed(sampleRows[br],sampleCols[bc]));edge.push(a.x,a.y,a.z,a.x,-.35,a.z,b.x,b.y,b.z,b.x,b.y,b.z,a.x,-.35,a.z,b.x,-.35,b.z);}
  const eg=new THREE.BufferGeometry();eg.setAttribute('position',new THREE.Float32BufferAttribute(edge,3));eg.computeVertexNormals();scn.add(new THREE.Mesh(eg,new THREE.MeshStandardMaterial({color:0x183242,roughness:1,side:THREE.DoubleSide})));

  // Single median flood surface (no time dimension in the contract) -- built once.
  const wgroup=new THREE.Group();scn.add(wgroup);water=wgroup;
  const wverts:number[]=[],wcolors:number[]=[];
  for(let ri=0;ri<rows-1;ri++)for(let ci=0;ci<cols-1;ci++){
   const r=sampleRows[ri],c=sampleCols[ci];const wse=arrays.flood[r*width+c];if(wse===floodNodata)continue;
   const groundZ=bed(r,c),depth=wse-groundZ;const {x:x0,y:y0}=worldXY(ri,ci),{x:x1,y:y1}=worldXY(ri+1,ci+1);const zw=(wse-minZ)*scaleY;
   const corners=[[x0,y0],[x0,y1],[x1,y0],[x1,y0],[x0,y1],[x1,y1]];
   const cc=new THREE.Color(depth>20?'#279ce4':depth>3?'#3dd7e7':'#72f2d7');
   for(const [x,y] of corners){wverts.push(x,zw,y);wcolors.push(cc.r,cc.g,cc.b);}
  }
  if(wverts.length){const wg=new THREE.BufferGeometry();wg.setAttribute('position',new THREE.Float32BufferAttribute(wverts,3));wg.setAttribute('color',new THREE.Float32BufferAttribute(wcolors,3));wg.computeVertexNormals();wgroup.add(new THREE.Mesh(wg,new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:.87,side:THREE.DoubleSide})));}
 } else if(grid){
  const sx=grid.sourceIndex%grid.nx,sy=Math.floor(grid.sourceIndex/grid.nx);const x0=Math.max(0,sx-25),x1=Math.min(grid.nx-1,sx+35),y0=Math.max(0,sy-19),y1=Math.min(grid.ny-1,sy+55);const minZ=Math.min(...grid.z),range=Math.max(...grid.z)-minZ;const scaleY=3.1/Math.max(range,1);const world=(x:number,y:number,z:number)=>new THREE.Vector3((x-x0)/(x1-x0)*12-6,(z-minZ)*scaleY,(y-y0)/(y1-y0)*10-5);
  const vertices:number[]=[],colors:number[]=[],uv:number[]=[],indices:number[]=[];const cols=x1-x0+1,rows=y1-y0+1;const color=new THREE.Color();for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){const z=grid.z[y*grid.nx+x],p=world(x,y,z);vertices.push(p.x,p.y,p.z);const t=(z-minZ)/Math.max(range,1);color.setRGB(.11+t*.19,.21+t*.24,.24+t*.23);if(z%120<12)color.multiplyScalar(.68);colors.push(color.r,color.g,color.b);uv.push((x-x0)/(x1-x0),(y-y0)/(y1-y0));}for(let y=0;y<rows-1;y++)for(let x=0;x<cols-1;x++){const a=y*cols+x;indices.push(a,a+cols,a+1,a+1,a+cols,a+cols+1);}const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geo.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geo.setIndex(indices);geo.computeVertexNormals();const material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:.94,metalness:.12,side:THREE.DoubleSide});const terrain=new THREE.Mesh(geo,material);scn.add(terrain);
  const mesh=new THREE.LineSegments(new THREE.WireframeGeometry(geo),new THREE.LineBasicMaterial({color:0x4c919c,transparent:true,opacity:wire?.17:.065}));scn.add(mesh);
  const edge:number[]=[];const ring:number[][]=[];for(let x=x0;x<=x1;x++)ring.push([x,y0]);for(let y=y0+1;y<=y1;y++)ring.push([x1,y]);for(let x=x1-1;x>=x0;x--)ring.push([x,y1]);for(let y=y1-1;y>=y0;y--)ring.push([x0,y]);for(let i=0;i<ring.length;i++){const a=world(ring[i][0],ring[i][1],grid.z[ring[i][1]*grid.nx+ring[i][0]]),b=world(ring[(i+1)%ring.length][0],ring[(i+1)%ring.length][1],grid.z[ring[(i+1)%ring.length][1]*grid.nx+ring[(i+1)%ring.length][0]]);edge.push(a.x,a.y,a.z,a.x,-.35,a.z,b.x,b.y,b.z,b.x,b.y,b.z,a.x,-.35,a.z,b.x,-.35,b.z);}const eg=new THREE.BufferGeometry();eg.setAttribute('position',new THREE.Float32BufferAttribute(edge,3));eg.computeVertexNormals();scn.add(new THREE.Mesh(eg,new THREE.MeshStandardMaterial({color:0x183242,roughness:1,side:THREE.DoubleSide})));
  const source=world(sx,sy,grid.z[grid.sourceIndex]);const marker=new THREE.Mesh(new THREE.BoxGeometry(.48,.13,.12),new THREE.MeshStandardMaterial({color:0xf2ba7b,emissive:0x8b4e15,emissiveIntensity:.3}));marker.position.copy(source).add(new THREE.Vector3(0,.12,0));scn.add(marker);
  const pin=new THREE.Mesh(new THREE.CylinderGeometry(.006,.006,.8,6),new THREE.MeshBasicMaterial({color:0x78efe0}));pin.position.copy(source).add(new THREE.Vector3(0,.6,0));scn.add(pin);const cap=new THREE.Mesh(new THREE.SphereGeometry(.045,12,12),new THREE.MeshBasicMaterial({color:0x9effed}));cap.position.copy(source).add(new THREE.Vector3(0,1,0));scn.add(cap);
  const wgroup=new THREE.Group();scn.add(wgroup);water=wgroup;let last:Result|null=null,lastFrame=-1;updateWater=function(){const {result:r,frame:f}=latest.current;if(last===r&&lastFrame===f)return;last=r;lastFrame=f;wgroup.children.forEach((o:any)=>{o.geometry?.dispose();o.material?.dispose();});wgroup.clear();if(!r)return;const depth=r.frames[f]?.depth??r.maxDepth,verts:number[]=[],colors2:number[]=[];for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){const i=y*grid.nx+x,d=depth[i];if(d<.3)continue;const z=grid.z[i]+d+8;const corners=[world(x,y,z),world(x,y+1,z),world(x+1,y,z),world(x+1,y,z),world(x,y+1,z),world(x+1,y+1,z)];const c=new THREE.Color(d>20?'#279ce4':d>3?'#3dd7e7':'#72f2d7');for(const p of corners){verts.push(p.x,p.y,p.z);colors2.push(c.r,c.g,c.b);}}const wg=new THREE.BufferGeometry();wg.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));wg.setAttribute('color',new THREE.Float32BufferAttribute(colors2,3));wg.computeVertexNormals();const wm=new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:.87,side:THREE.DoubleSide});wgroup.add(new THREE.Mesh(wg,wm));if(mode==='particles'&&verts.length){const pg=new THREE.BufferGeometry();const p:number[]=[];for(let i=0;i<verts.length;i+=3){for(let j=0;j<5;j++)p.push(verts[i]+Math.sin(i+j)*.035,verts[i+1]+.02+j*.004,verts[i+2]+Math.cos(i+j)*.035);}pg.setAttribute('position',new THREE.Float32BufferAttribute(p,3));wgroup.add(new THREE.Points(pg,new THREE.PointsMaterial({color:0x9bfff5,size:.04,transparent:true,opacity:.85})));}};
 }

 let raf=0;const resize=()=>{const {width,height}=el.getBoundingClientRect();renderer.setSize(width,height);camera.aspect=width/Math.max(height,1);camera.updateProjectionMatrix();};const observer=new ResizeObserver(resize);observer.observe(el);resize();function animate(){raf=requestAnimationFrame(animate);updateWater?.();controls.update();renderer.render(scn,camera);}animate();engine.current={reset:()=>{camera.position.set(9,11.5,11);controls.target.set(0,1.1,0);controls.update();}};
 return()=>{cancelAnimationFrame(raf);observer.disconnect();controls.dispose();scn.traverse((o:any)=>{o.geometry?.dispose();if(Array.isArray(o.material))o.material.forEach((m:any)=>m.dispose());else o.material?.dispose();});renderer.dispose();renderer.domElement.remove();engine.current=null;};},[grid,scene,arrays,mode,wire]);

 const ve=real&&scene?scene.frame.vertical_exaggeration:null;
 const coordLine=real&&scene
  ?<>EPSG:{scene.terrain.crs_epsg??'—'} <span>{label??'scene'}</span></>
  :grid?<>{((grid.north+grid.south)/2).toFixed(3)}° N &nbsp; {((grid.west+grid.east)/2).toFixed(3)}° E <span>{grid.name}</span></>:null;
 return <div className={'terrain-three '+className}><div ref={host} className="three-host" aria-label="Interactive 3D elevation model with simulated inundation"/>{failed&&grid&&<TerrainCanvas grid={grid} result={result} frame={frame} reset={reset}/>}<div className="scene-coordinates">{coordLine}</div><div className="scene-tools"><span><Move3D size={14}/>Drag to orbit · scroll to zoom</span><button aria-label="Reset 3D camera" onClick={()=>{engine.current?.reset();setReset(r=>r+1);}}><RotateCcw size={15}/></button></div><div className="scene-caption">{real?<>REAL TERRAIN <i/> EXAGGERATED RELIEF ×{ve?.toFixed(1)} <i/> REAL D-FLOW SURFACE <i/> NEAR-FIELD SPH: UNDER INVESTIGATION</>:<>REAL TERRAIN <i/> EXAGGERATED RELIEF <i/> SIMULATED WATER {failed&&<> <i/> SOFTWARE 3D</>}</>}</div></div>;
}
