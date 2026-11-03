import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowUpRight,Download,Loader2,Play,Search} from 'lucide-react';
import {Badge,Button} from './components/ui';
import {collectionSelection,formatMeasurement,sortImageRows} from './collectionModel';
import './batch-workspace.css';

const statusLabel=status=>({ready:'Ready',complete:'Saved',running:'Analyzing',queued:'Queued',error:'Needs attention',interrupted:'Interrupted'}[status]||status);

async function responseError(response) {
  try {const body=await response.json();if(typeof body.detail==='string')return body.detail;} catch { /* Use the readable status fallback. */ }
  return `The request could not be completed (${response.status}). Please try again.`;
}

export default function CollectionView({projects,queue,onOpen,onEnqueue,onError,importing=false}) {
  const [query,setQuery]=useState(''),[sort,setSort]=useState('name');
  const [excluded,setExcluded]=useState(()=>new Set());
  const [summaries,setSummaries]=useState([]),[loading,setLoading]=useState(false),[loadError,setLoadError]=useState(''),[retry,setRetry]=useState(0);
  const [downloading,setDownloading]=useState('');
  const allCheckbox=useRef(null);
  const completedKey=projects.filter(p=>p.status==='complete').map(p=>`${p.id}:${p.revision}`).sort().join('|');
  const completedIds=useMemo(()=>completedKey?completedKey.split('|').map(value=>value.split(':')[0]):[],[completedKey]);
  const selectedIds=useMemo(()=>collectionSelection(completedIds,excluded),[completedIds,excluded]);
  const summaryById=useMemo(()=>new Map(summaries.map(row=>[row.id,row])),[summaries]);
  const visible=useMemo(()=>sortImageRows(projects,summaryById,query,sort),[projects,summaryById,query,sort]);
  const visibleIds=useMemo(()=>new Set(visible.map(p=>p.id)),[visible]);
  const outsideSearch=selectedIds.filter(id=>!visibleIds.has(id)).length;
  const waitingIds=visible.filter(p=>['ready','error','interrupted'].includes(p.status)).map(p=>p.id);
  const allSelected=completedIds.length>0&&selectedIds.length===completedIds.length;
  const someSelected=selectedIds.length>0&&!allSelected;
  const queueBusy=Boolean(queue?.active_id||queue?.pending_ids?.length);

  useEffect(()=>{if(allCheckbox.current)allCheckbox.current.indeterminate=someSelected;},[someSelected]);
  useEffect(()=>{
    if(!completedKey){setSummaries([]);setLoadError('');setLoading(false);return;}
    const controller=new AbortController();
    setLoading(true);setLoadError('');
    const ids=completedKey.split('|').map(value=>value.split(':')[0]);
    (async()=>{
      try {
        const response=await fetch('/api/collection/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_ids:ids}),signal:controller.signal});
        if(!response.ok)throw new Error(await responseError(response));
        const rows=await response.json();
        if(!controller.signal.aborted)setSummaries(rows);
      }catch(error){if(!controller.signal.aborted)setLoadError(error.message);}
      finally{if(!controller.signal.aborted)setLoading(false);}
    })();
    return()=>controller.abort();
  },[completedKey,retry]);

  const toggleImage=(id,checked)=>setExcluded(previous=>{const next=new Set(previous);if(checked)next.delete(id);else next.add(id);return next;});
  const toggleAll=checked=>setExcluded(previous=>{const next=new Set(previous);for(const id of completedIds){if(checked)next.delete(id);else next.add(id);}return next;});
  const download=async kind=>{
    if(!selectedIds.length||downloading)return;
    setDownloading(kind);
    let objectUrl;
    try {
      const search=new URLSearchParams({ids:selectedIds.join(',')});
      const response=await fetch(`/api/collection/export/${kind}?${search}`);
      if(!response.ok)throw new Error(await responseError(response));
      const blob=await response.blob();objectUrl=URL.createObjectURL(blob);
      const disposition=response.headers.get('content-disposition')||'';
      const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i);
      const plain=disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
      let filename=`oclast_${kind==='summary.csv'?'image_summary':'all_objects'}_${selectedIds.length}_images.csv`;
      if(encoded){try{filename=decodeURIComponent(encoded[1]);}catch{/* Keep the safe scope filename. */}}
      else if(plain)filename=(plain[1]||plain[2]).trim();
      const anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=filename;document.body.append(anchor);anchor.click();anchor.remove();
    }catch(error){onError?.(error.message);}
    finally{
      // Give the browser's download handoff time to retain its Blob reference.
      if(objectUrl)setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
      setDownloading('');
    }
  };

  return <main className="collection-view" aria-label="Image collection">
    <header className="collection-heading">
      <div><h1>Images <span>{projects.length.toLocaleString()}</span></h1><p>{completedIds.length.toLocaleString()} analyzed{queueBusy?queue.paused?' · queue paused':' · queue running':''}</p></div>
      {waitingIds.length>0&&<Button variant="primary" onClick={()=>onEnqueue(waitingIds)} disabled={importing} title={importing?'Finish importing before starting analysis':undefined}><Play size={16}/>Analyze {waitingIds.length} {waitingIds.length===1?'image':'images'}</Button>}
    </header>
    <div className="collection-toolbar">
      <label className="collection-search"><Search size={16} aria-hidden="true"/><span className="collection-sr-only">Find images in collection</span><input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Find images"/></label>
      <label className="collection-sort">Sort by<select value={sort} onChange={event=>setSort(event.target.value)}><option value="name">Image name</option><option value="count">Object count</option><option value="area">Median area</option><option value="circularity">Median circularity</option></select></label>
      <div className="collection-export">
        <Button onClick={()=>download('summary.csv')} disabled={!selectedIds.length||Boolean(downloading)||loading}>{downloading==='summary.csv'?<Loader2 size={15} className="spin"/>:<Download size={15}/>}Image summary CSV</Button>
        <Button onClick={()=>download('objects.csv')} disabled={!selectedIds.length||Boolean(downloading)}>{downloading==='objects.csv'?<Loader2 size={15} className="spin"/>:<Download size={15}/>}All objects CSV</Button>
      </div>
    </div>
    <div className="collection-scope" role="status"><strong>{selectedIds.length.toLocaleString()} {selectedIds.length===1?'image':'images'} selected</strong><span>All objects{outsideSearch?` · ${outsideSearch} selected outside search`:''}</span>{loading&&<span className="collection-loading"><Loader2 size={13} className="spin"/>Updating measurements</span>}</div>
    {loadError&&<div className="collection-error" role="alert"><span>{loadError}</span><Button size="sm" onClick={()=>setRetry(value=>value+1)}>Retry measurements</Button></div>}
    <div className="collection-table-wrap" tabIndex={0} role="region" aria-label="Per-image comparison" aria-busy={loading}>
      <table className="collection-table"><thead><tr>
        <th scope="col" className="collection-check"><input ref={allCheckbox} type="checkbox" aria-label="Select all completed images" checked={allSelected} disabled={!completedIds.length} onChange={event=>toggleAll(event.target.checked)}/></th>
        <th scope="col">Image</th><th scope="col">Status</th><th scope="col" className="collection-number">Objects</th><th scope="col" className="collection-number">Median area <small>px²</small></th><th scope="col" className="collection-number">Median circularity</th><th scope="col"><span className="collection-sr-only">Review</span></th>
      </tr></thead><tbody>{visible.map(project=>{
        const row=summaryById.get(project.id),complete=project.status==='complete';
        const current=row&&row.revision===project.revision;
        const hasObjects=complete&&project.count>0;
        return <tr key={project.id} data-selected={complete&&!excluded.has(project.id)}>
          <td className="collection-check"><input type="checkbox" aria-label={`Include ${project.name} in CSV exports`} checked={complete&&!excluded.has(project.id)} disabled={!complete} onChange={event=>toggleImage(project.id,event.target.checked)}/></td>
          <td className="collection-image"><Button variant="ghost" className="collection-name" onClick={()=>onOpen(project.id)} title={project.source_path||project.name}>{project.name}</Button><span>{project.source_path&&project.source_path!==project.name?project.source_path:`${project.width.toLocaleString()} × ${project.height.toLocaleString()} px`}</span></td>
          <td><Badge status={project.status}>{statusLabel(project.status)}</Badge>{project.status==='running'&&<small className="collection-row-progress">{project.progress||0}%</small>}</td>
          <td className="collection-number">{complete?project.count.toLocaleString():'—'}</td>
          <td className="collection-number">{hasObjects&&current?formatMeasurement(row.median_area):'—'}{hasObjects&&current&&row.area_q1!=null&&row.area_q3!=null&&<small className="collection-iqr">IQR {formatMeasurement(row.area_q1)}–{formatMeasurement(row.area_q3)}</small>}</td>
          <td className="collection-number">{hasObjects&&current?formatMeasurement(row.median_circularity,3):'—'}</td>
          <td className="collection-review"><Button variant="ghost" size="sm" aria-label={`Review ${project.name}`} onClick={()=>onOpen(project.id)}><ArrowUpRight size={16}/><span>Review</span></Button></td>
        </tr>;
      })}</tbody></table>
      {!visible.length&&<p className="collection-empty">{projects.length?'No matching images.':'Open images or a folder to start a collection.'}</p>}
    </div>
  </main>;
}
