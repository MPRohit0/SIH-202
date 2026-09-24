import SentriqApp from '../sentriq/app';
import {notFound} from 'next/navigation';
export default async function Page({params}:{params:Promise<{view:string}>}){const {view}=await params;if(!['dashboard','simulation','library','compare','lab','impact','data','monitoring','exports','sites','settings'].includes(view))notFound();return <SentriqApp initialView={view}/>;}
