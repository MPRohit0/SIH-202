/* Educational local-inertial finite-volume routing. Not Delft3D or SPH.
   Regular metric approximation to WGS84 grid. Closed north/east/west,
   free outflow south boundary. Positivity-limited conservative face fluxes. */
function simulate(grid,p,progress=()=>{}) {
 const started=Date.now(),{nx,ny,dx,dy,z}=grid,N=nx*ny,g=9.81,A=dx*dy;
 const h=new Float64Array(N),maxDepth=new Float64Array(N),arrival=new Float64Array(N).fill(-1),maxVelocity=new Float64Array(N),velocity=new Float64Array(N),qx=new Float64Array(N),qy=new Float64Array(N),out=new Float64Array(N),factor=new Float64Array(N);
 const frames=[],hydrograph=[];let t=0,vin=0,vout=0,next=0,maxH=1,peak=0;
 const total=p.duration*60;const dtMax=2;const snap=total/24;const source=Math.min(N-1,Math.max(0,p.sourceIndex));
 function capture(flow){let area=0,volume=0,max=0;for(let i=0;i<N;i++){if(h[i]>=.3)area+=A/1e6;volume+=h[i]*A;max=Math.max(max,h[i]);}frames.push({time:t/60,depth:Array.from(h,v=>Math.round(v*1000)/1000),velocity:Array.from(velocity,v=>Math.round(v*1000)/1000),area,maxDepth:max,volume,inflow:flow});hydrograph.push({time:t/60,flow});progress(Math.round(100*t/total));}
 capture(0);next=snap;
 while(t<total-1e-7){let dt=Math.min(dtMax,.22*Math.min(dx,dy)/Math.sqrt(g*Math.max(maxH,.1)),total-t,next-t);if(dt<1e-8){next+=snap;continue;}
  let flow=p.mode==='release'?p.release*(p.gates||1)*Math.min(1,(t+dt/2)/Math.max(1,(p.ramp||0)*60)):1.7*p.width*Math.pow(p.head,1.5)*Math.min(1,(t+dt/2)/Math.max(60,p.formation*60))*Math.exp(-Math.max(0,t-p.formation*60)/Math.max(300,p.formation*120));
  if(p.hydrograph?.length){const rows=p.hydrograph;let j=0;while(j<rows.length-2&&rows[j+1].time*60<t)j++;const a=rows[j],b=rows[j+1],f=Math.max(0,Math.min(1,(t/60-a.time)/(b.time-a.time)));flow=a.flow+(b.flow-a.flow)*f;}
  flow=Math.min(flow,Math.max(0,p.volume*1e6-vin)/dt);h[source]+=flow*dt/A;vin+=flow*dt;peak=Math.max(peak,flow);
  out.fill(0);
  for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){const i=y*nx+x;
   if(x<nx-1){const j=i+1,H=Math.max(0,Math.max(z[i]+h[i],z[j]+h[j])-Math.max(z[i],z[j]));qx[i]=H>.001?(qx[i]-g*H*dt*((z[j]+h[j])-(z[i]+h[i]))/dx)/(1+g*dt*p.roughness**2*Math.abs(qx[i])/Math.pow(H,7/3)):0;const q=qx[i]*dy;out[q>0?i:j]+=Math.abs(q);}
   if(y<ny-1){const j=i+nx,H=Math.max(0,Math.max(z[i]+h[i],z[j]+h[j])-Math.max(z[i],z[j]));qy[i]=H>.001?(qy[i]-g*H*dt*((z[j]+h[j])-(z[i]+h[i]))/dy)/(1+g*dt*p.roughness**2*Math.abs(qy[i])/Math.pow(H,7/3)):0;const q=qy[i]*dx;out[q>0?i:j]+=Math.abs(q);}
   else {qy[i]=Math.sqrt(g)*Math.pow(h[i],1.5);out[i]+=qy[i]*dx;}
  }
  for(let i=0;i<N;i++)factor[i]=out[i]>0?Math.min(1,h[i]*A/(out[i]*dt)):1;
  for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){const i=y*nx+x;if(x<nx-1){const j=i+1;qx[i]*=factor[qx[i]>0?i:j];const v=qx[i]*dy*dt/A;h[i]-=v;h[j]+=v;}if(y<ny-1){const j=i+nx;qy[i]*=factor[qy[i]>0?i:j];const v=qy[i]*dx*dt/A;h[i]-=v;h[j]+=v;}else {qy[i]*=factor[i];const v=qy[i]*dx*dt;h[i]-=v/A;vout+=v;}}
  t+=dt;maxH=0;for(let i=0;i<N;i++){h[i]=Math.max(0,h[i]);if(!Number.isFinite(h[i]))throw Error('Numerical instability. Reduce inflow or use a finer DEM.');maxH=Math.max(maxH,h[i]);maxDepth[i]=Math.max(maxDepth[i],h[i]);const x=i%nx,y=Math.floor(i/nx);velocity[i]=h[i]>=.3?Math.hypot((qx[i]+(x>0?qx[i-1]:0))*.5,(qy[i]+(y>0?qy[i-nx]:0))*.5)/h[i]:0;maxVelocity[i]=Math.max(maxVelocity[i],velocity[i]);if(h[i]>=.3&&arrival[i]<0)arrival[i]=t/60;}
  if(t>=next-1e-7){capture(flow);next+=snap;}
 }
 const stored=h.reduce((a,b)=>a+b*A,0);return {frames,maxDepth:Array.from(maxDepth),maxVelocity:Array.from(maxVelocity),arrival:Array.from(arrival),hydrograph,massError:vin?Math.abs(vin-vout-stored)/vin*100:0,inflowVolume:vin,outflowVolume:vout,params:p,grid,peakFlow:peak,runtime:(Date.now()-started)/1000};
}
if(typeof self!=='undefined')self.onmessage=e=>{try {self.postMessage({type:'result',result:simulate(e.data.grid,e.data.params,value=>self.postMessage({type:'progress',value}))});}catch(error){self.postMessage({type:'error',message:error.message});}};
if(typeof module!=='undefined')module.exports={simulate};
