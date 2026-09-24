import {Result} from './model';
export type Scenario=Result&{id:string;severity:number;engine:string;createdAt:string;validation:string;interpolated?:boolean};
export type Exposure={name:string;lon:number;lat:number;population:number;type:string;buildings?:number;area_ha?:number};
export const nf=(n:number,d=1)=>Number.isFinite(n)?n.toLocaleString('en-IN',{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
export function stats(r:Result|null){if(!r)return {area:NaN,depth:NaN,velocity:NaN,peak:NaN};return {area:r.maxDepth.filter(v=>v>=.3).length*r.grid.dx*r.grid.dy/1e6,depth:Math.max(...r.maxDepth),velocity:Math.max(...(r.maxVelocity??[0])),peak:r.peakFlow??Math.max(...r.hydrograph.map(h=>h.flow))};}
