import {useEffect,useRef,useState} from 'react';
import {FolderOpen,Plus,PanelLeftClose,PanelRightClose,PanelLeftOpen,PanelRightOpen,Play,CheckCircle2,Download,Undo2,Trash2,Loader2,AlertCircle,FileImage,ScanLine,Layers,Image as ImageIcon,Grid2X2,List,X,Keyboard,ChevronDown,Cpu,Maximize2} from 'lucide-react';
import Viewer from './Viewer';
import TileLibrary from './TileLibrary';
import DensityPlot from './DensityPlot';
import ObjectExplorer from './ObjectExplorer';
import {CellMark,MetricGraphic} from './components/CellMark';
import {Button,Badge,SegmentedControl} from './components/ui';
import CollectionView from './CollectionView';
import BatchQueue from './BatchQueue';
import {duration,importFiles,downloadCsv} from './workflow';
import './workspace.css';

async function api(path,options={}) {
  const response=await fetch(`/api${path}`,options);
  if(!response.ok) {
    let detail;
    try {detail=(await response.json()).detail;} catch {detail=`The request could not be completed (${response.status}). Please try again.`;}
    throw new Error(typeof detail==='string'?detail:'The request could not be completed.');
  }
  return response.json();
}
const json=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const computeLabel=compute=>compute?.device==='gpu'?'GPU':compute?.device==='cpu'?'CPU':compute?.device==='mixed'?'GPU / CPU':'';
const statusLabel=status=>({ready:'Ready',complete:'Saved',running:'Analyzing',queued:'Queued',error:'Needs attention',interrupted:'Interrupted'}[status]||status);
const figure=n=>n.toLocaleString(undefined,{maximumFractionDigits:0});

function Disclosure({children,label,icon,className=''}) {
  const host=useRef(null);
  useEffect(()=>{
    const outside=event=>{if(!host.current?.contains(event.target))host.current?.removeAttribute('open');};
    document.addEventListener('pointerdown',outside);
    return()=>document.removeEventListener('pointerdown',outside);
  },[]);
  return <details ref={host} className={`toolbar-disclosure ${className}`} onKeyDown={event=>{if(event.key==='Escape'){event.currentTarget.open=false;event.currentTarget.querySelector('summary')?.focus();}}}>
    <summary aria-label={label}>{icon}<span>{label}</span><ChevronDown size={13} aria-hidden="true"/></summary>
    <div className="disclosure-content">{children}</div>
  </details>;
}

function SelectedCell({cell,busy,onClear,onRemove}) {
  return <section className="selected-object" aria-label={`Selected cell ${cell.id}`}>
    <div className="selected-cell-heading"><strong>Cell #{cell.id}</strong><div>
      <Button disabled={busy} onClick={onRemove} aria-label={`Remove detection ${cell.id}`} title="Remove detection"><Trash2 size={15}/></Button>
      <Button onClick={onClear} aria-label="Clear cell selection" title="Clear selection"><X size={16}/></Button>
    </div></div>
    <div className="metrics selected-cell-metrics">
      <div className="metric-card metric-pink"><span>Area</span><strong>{figure(cell.area)}<small> px²</small></strong><MetricGraphic type="area"/></div>
      <div className="metric-card metric-sand"><span>Circularity</span><strong>{cell.circularity.toFixed(3)}</strong><MetricGraphic type="circularity" value={cell.circularity}/></div>
    </div>
  </section>;
}

export default function App() {
  const [projects,setProjects]=useState([]),[project,setProject]=useState(null),[cells,setCells]=useState([]);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[uploading,setUploading]=useState(false),[opening,setOpening]=useState(false);
  const [layer,setLayer]=useState('raw'),[selected,setSelected]=useState(null),[leftOpen,setLeftOpen]=useState(true),[rightOpen,setRightOpen]=useState(true);
  const [filter,setFilter]=useState(''),[projectFilter,setProjectFilter]=useState(''),[tick,setTick]=useState(Date.now()),[tableLimit,setTableLimit]=useState(100);
  const [showTiles,setShowTiles]=useState(false),[focusRegion,setFocusRegion]=useState(null),[exploring,setExploring]=useState(false);
  const [mobilePane,setMobilePane]=useState('image'),[compute,setCompute]=useState(null),[connectionAttempt,setConnectionAttempt]=useState(0);
  const [workspaceView,setWorkspaceView]=useState('review'),[queue,setQueue]=useState(null),[importProgress,setImportProgress]=useState(null),[importIssues,setImportIssues]=useState([]),[exporting,setExporting]=useState(false);
  const input=useRef(null),folderInput=useRef(null),active=useRef(null),shownVersion=useRef(''),stopImport=useRef(false);
  const running=project&&['queued','running'].includes(project.status);
  const queueActive=Boolean(queue?.active_id||(!queue?.paused&&queue?.pending_ids?.length));
  const importBlocked=uploading||queueActive||project?.status==='running';
  const refreshList=async()=>{const list=await api('/projects');setProjects(list);return list;};
  const open=async id=>{
    active.current=id;shownVersion.current='';setWorkspaceView('review');setExploring(false);setError('');setSelected(null);setFocusRegion(null);setFilter('');setTableLimit(100);setCells([]);setOpening(true);setMobilePane('image');
    try {
      const p=await api(`/projects/${id}`);
      if(active.current!==id)return;
      setProject(p);setProjects(list=>list.map(item=>item.id===p.id?p:item));
      if(p.error)setError(p.error);
      localStorage.setItem('oclast.lastProject',id);
      if(p.status==='complete') {
        setLayer('labels');const rows=await api(`/projects/${id}/cells`);
        if(active.current===id){setCells(rows);shownVersion.current=`${id}:${p.revision}`;}
      }else setLayer('raw');
    } catch(e) {setError(e.message);} finally {if(active.current===id)setOpening(false);}
  };
  useEffect(()=>{
    let live=true,timer;
    const sync=async()=>{
      let interval=5000;
      try {
        const [health,list,nextQueue]=await Promise.all([api('/health'),api('/projects'),api('/queue')]);
        if(!live)return;
        setCompute(health.compute);setProjects(list);setQueue(nextQueue);setTick(Date.now());
        setError(previous=>previous.startsWith('Cannot reach the local OCLAST service.')?'':previous);
        const id=active.current,p=list.find(item=>item.id===id);
        if(p){
          if(p.status==='complete'&&shownVersion.current!==`${id}:${p.revision}`){
            const [meta,rows]=await Promise.all([api(`/projects/${id}`),api(`/projects/${id}/cells`)]);
            if(live&&active.current===id){setProject(meta);setCells(rows);setLayer('labels');shownVersion.current=`${id}:${meta.revision}`;}
          }else setProject(previous=>previous?.id===id?{...previous,...p}:previous);
        }
        if(nextQueue.active_id||nextQueue.pending_ids?.length||p?.status==='running')interval=1000;
      }catch(e){if(live)setError(`Cannot reach the local OCLAST service. ${e.message}`);}
      if(live)timer=setTimeout(sync,interval);
    };
    (async()=>{
      try{
        const list=await refreshList(),last=localStorage.getItem('oclast.lastProject');
        if(live&&list.some(p=>p.id===last))await open(last);
      }catch(e){if(live)setError(e.message);}
      if(live)sync();
    })();
    return()=>{live=false;clearTimeout(timer);};
  },[connectionAttempt]);
  const upload=async event=>{
    const chosen=Array.from(event.target.files||[]);event.target.value='';if(!chosen.length)return;
    const {accepted,issues}=importFiles(chosen);
    if(!accepted.length){setError('Choose nonempty TIFF, PNG or JPEG images up to 512 MB each.');setImportIssues(issues);return;}
    if(importBlocked){setError('Pause the queue and let the current image finish before importing more images.');return;}
    setUploading(true);setError('');setImportIssues(issues);stopImport.current=false;
    const imported=[];let failed=[...issues];
    if(accepted.length>1)setWorkspaceView('collection');
    try {
      for(let index=0;index<accepted.length;index++){
        if(stopImport.current)break;
        const file=accepted[index];setImportProgress({name:file.webkitRelativePath||file.name,done:index,total:accepted.length});
        try{
          const body=new FormData();body.append('file',file);body.append('source_path',file.webkitRelativePath||file.name);body.append('reuse_existing','true');
          const p=await api('/projects',{method:'POST',body});imported.push(p.id);
          setProjects(previous=>[p,...previous.filter(item=>item.id!==p.id)]);
        }catch(e){failed.push({name:file.webkitRelativePath||file.name,error:e.message});setImportIssues([...failed]);}
        setImportProgress({name:file.webkitRelativePath||file.name,done:index+1,total:accepted.length});
      }
      await refreshList();
      if(accepted.length===1&&imported.length)await open(imported[0]);
      if(!imported.length)setError('No images were imported. Check the files listed below.');
    }catch(e){setError(e.message);}finally{setImportIssues(failed);setUploading(false);setImportProgress(null);}
  };
  const enqueue=async ids=>{
    if(uploading){setError('Finish importing before starting analysis.');return;}
    if(!ids.length)return;
    setError('');
    try {
      setQueue(await api('/queue',json({project_ids:ids})));
      const list=await refreshList(),p=list.find(item=>item.id===active.current);
      if(p)setProject(previous=>previous?.id===p.id?{...previous,...p}:previous);
    }catch(e){setError(e.message);}
  };
  const controlQueue=async action=>{
    try{setQueue(await api('/queue/control',json({action})));await refreshList();}
    catch(e){setError(e.message);}
  };
  const analyze=()=>enqueue(project?[project.id]:[]);
  const edit=async body=>{
    if(!project)return false;
    const id=project.id;setBusy(true);setError('');
    try {
      const p=await api(`/projects/${id}/edits`,json({...body,revision:project.revision})),rows=await api(`/projects/${id}/cells`);
      if(active.current===id){setProject(p);setCells(rows);setSelected(null);shownVersion.current=`${id}:${p.revision}`;}await refreshList();return true;
    }catch(e){setError(e.message);return false;}finally{setBusy(false);}
  };
  const undo=async()=>{
    const id=project.id;setBusy(true);setError('');
    try {
      const p=await api(`/projects/${id}/undo`,json({revision:project.revision})),rows=await api(`/projects/${id}/cells`);
      if(active.current===id){setProject(p);setCells(rows);setSelected(null);shownVersion.current=`${id}:${p.revision}`;}await refreshList();
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };
  const exportMeasurements=async()=>{
    setExporting(true);setError('');
    try{await downloadCsv(`/api/projects/${project.id}/export/measurements.csv`,'oclast_measurements.csv');}
    catch(e){setError(e.message);}finally{setExporting(false);}
  };
  const selectCell=id=>{setSelected(id);if(id!==null){setShowTiles(false);setRightOpen(true);setMobilePane('inspector');}};
  const inspectCell=id=>{selectCell(id);if(id!==null)setMobilePane('image');};
  const selectedCell=cells.find(c=>c.id===selected);
  const elapsed=project?.status==='running'&&project.started_at?Math.max(0,tick/1000-project.started_at):project?.status==='queued'?0:project?.elapsed_seconds||0;
  const filtered=cells.filter(c=>!filter||String(c.id).includes(filter)),tableRows=filtered.slice(0,tableLimit),tableHasSelected=tableRows.some(c=>c.id===selected);
  const visibleProjects=projects.filter(p=>(p.source_path||p.name).toLowerCase().includes(projectFilter.toLowerCase()));
  const focusImage=()=>{const focus=leftOpen||rightOpen;setLeftOpen(!focus);setRightOpen(!focus);setMobilePane('image');};
  const tableKey=(event,index)=>{
    let next;
    if(event.key==='ArrowDown')next=Math.min(tableRows.length-1,index+1);
    else if(event.key==='ArrowUp')next=Math.max(0,index-1);
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=tableRows.length-1;
    else return;
    event.preventDefault();inspectCell(tableRows[next].id);
    event.currentTarget.closest('tbody').querySelectorAll('button')[next]?.focus();
  };

  return <div className="app">
    <header className="app-header">
      <div className="brand"><div className="brand-mark"><CellMark/></div><strong>OCLAST</strong>
        <a className="brand-github" href="https://github.com/yuvipaloozie/OCLAST" target="_blank" rel="noopener noreferrer" aria-label="OCLAST paper repository on GitHub (opens in a new tab)" title="Paper and research code on GitHub"><svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.23c-3.34.73-4.04-1.42-4.04-1.42-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23A11.5 11.5 0 0 1 12 6.3c1.02 0 2.05.14 3.01.4 2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.8 5.63-5.48 5.93.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .5Z"/></svg></a>
      </div>
      <div className="workspace-switcher"><SegmentedControl value={workspaceView} onChange={setWorkspaceView} label="Workspace view" options={[{value:'review',label:'Review'},{value:'collection',label:'Images'}]}/></div>
      <div className="header-actions">
        {computeLabel(compute)&&<span className="runtime-status" title={`Current inference runtime: ${compute.active_provider}`}><Cpu size={14} aria-hidden="true"/>Runtime · {computeLabel(compute)}</span>}
        <Disclosure label="Shortcuts" icon={<Keyboard size={16}/>} className="keyboard-help">
          <strong>Image review</strong><dl><div><dt>Pan</dt><dd>Arrow keys</dd></div><div><dt>Zoom</dt><dd>+ / −</dd></div><div><dt>Fit image</dt><dd>F or 0</dd></div><div><dt>Native pixels</dt><dd>1</dd></div><div><dt>Inspect center</dt><dd>Enter</dd></div><div><dt>Cancel / clear</dt><dd>Escape</dd></div></dl>
          <p>Click the image or press Tab to focus the viewer first. In drawing mode, Enter places a vertex, Backspace removes one, and Ctrl+Enter saves.</p>
        </Disclosure>
        <Button className="open-folder" onClick={()=>folderInput.current.click()} disabled={importBlocked} title={queueActive?'Pause the queue to import more images':'Open a folder of images'} aria-label="Open folder"><FolderOpen size={16}/><span>Open folder</span></Button>
        <Button variant="primary" className="primary" onClick={()=>input.current.click()} disabled={importBlocked} title={queueActive?'Pause the queue to import more images':'Open one or more images'}><Plus size={16}/>{uploading?'Importing…':'Open images'}</Button>
      </div>
      <input ref={input} type="file" accept=".tif,.tiff,.png,.jpg,.jpeg" multiple onChange={upload} hidden/>
      <input ref={folderInput} type="file" accept=".tif,.tiff,.png,.jpg,.jpeg" multiple webkitdirectory="" directory="" onChange={upload} hidden/>
    </header>
    {error&&<div role="alert" className="error-banner"><AlertCircle size={18}/><span>{error}</span>{error.includes('local OCLAST service')&&<Button onClick={()=>{setError('');setConnectionAttempt(n=>n+1);}}>Retry connection</Button>}<Button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></Button></div>}
    {uploading&&<div className="upload-banner" role="status"><Loader2 size={16} className="spin"/><span>Importing {importProgress?.done||0} / {importProgress?.total||'—'}<span className="import-filename"> · {importProgress?.name}</span></span><Button size="sm" onClick={()=>{stopImport.current=true;}}>Stop after image</Button></div>}
    {importIssues.length>0&&<details className="import-issues"><summary>{importIssues.length} {importIssues.length===1?'file needs':'files need'} attention</summary><ul>{importIssues.map((item,index)=><li key={`${item.name}-${index}`}><strong>{item.name}</strong> · {item.error}</li>)}</ul><Button size="sm" onClick={()=>setImportIssues([])}>Dismiss</Button></details>}
    <BatchQueue queue={queue} projects={projects} onControl={controlQueue} onRetry={enqueue} importing={uploading}/>
    {workspaceView==='collection'?<CollectionView projects={projects} queue={queue} onOpen={open} onEnqueue={enqueue} onError={setError} importing={uploading}/>:<>
    <nav className="mobile-workspace-nav" aria-label="Workspace panels">
      <Button aria-pressed={mobilePane==='projects'} onClick={()=>{setLeftOpen(true);setMobilePane('projects');}}><FolderOpen size={16}/>Library</Button>
      <Button aria-pressed={mobilePane==='image'} onClick={()=>setMobilePane('image')}><ImageIcon size={16}/>Viewer</Button>
      <Button aria-pressed={mobilePane==='inspector'} onClick={()=>{setRightOpen(true);setMobilePane('inspector');}}><List size={16}/>Inspect</Button>
    </nav>
    <div className={`workspace ${leftOpen?'':'left-collapsed'} ${rightOpen?'':'right-collapsed'}`} data-mobile-pane={mobilePane}>
      {leftOpen&&<aside className="projects-panel">
        <div className="panel-heading"><h2>Images <span className="panel-count">{projects.length}</span></h2><Button aria-label="Hide images" title="Hide images" onClick={()=>{setLeftOpen(false);setMobilePane('image');}}><PanelLeftClose size={17}/></Button></div>
        {projects.length>3&&<label className="project-search">Find image<input type="search" value={projectFilter} onChange={e=>setProjectFilter(e.target.value)} placeholder="Image name"/></label>}
        <div className="project-list">
          {projects.length===0?<Button className="empty-project" onClick={()=>input.current.click()}><FolderOpen/><span>Open your first image</span></Button>:visibleProjects.map(p=><Button className={`project-card ${p.id===project?.id?'selected':''}`} aria-pressed={p.id===project?.id} key={p.id} onClick={()=>open(p.id)} disabled={busy} title={p.source_path||p.name}>
            <div className="project-file-icon"><FileImage size={18}/></div><span className="project-name">{p.name}</span><span className="project-meta">{figure(p.width)} × {figure(p.height)} px</span><span className="project-status"><Badge status={p.status}>{statusLabel(p.status)}</Badge>{p.status==='complete'&&<span>{figure(p.count)} {p.count===1?'object':'objects'}</span>}</span>
          </Button>)}
          {projects.length>0&&!visibleProjects.length&&<p className="panel-message">No matching images.</p>}
        </div>
        <div className="storage-note"><CheckCircle2 size={15}/><span>Autosaved locally</span></div>
      </aside>}
      <main className="analysis-panel" aria-busy={opening}>
        <div className="analysis-heading"><div className="heading-title">
          {!leftOpen&&<Button aria-label="Show images" title="Show images" onClick={()=>setLeftOpen(true)}><PanelLeftOpen size={18}/></Button>}
          <div><h1 title={project?.name}>{project?.name||'New analysis'}</h1><p>{project?`${figure(project.width)} × ${figure(project.height)} px${project.storage_bytes?` · ${(project.storage_bytes/1e6).toFixed(1)} MB`:''}`:'TRAP-stained osteoclast microscopy'}</p></div>
        </div><div className="heading-actions">
          {project&&['ready','error','interrupted'].includes(project.status)&&<Button variant="primary" className="primary" onClick={analyze} disabled={busy||opening}><Play size={16}/>Analyze image</Button>}
          {project?.status==='complete'&&<><span className="saved-indicator" role="status"><CheckCircle2 size={15}/>{busy?'Saving…':'Saved'}</span>
            <Button disabled={!project.can_undo||busy} onClick={undo} title="Undo last edit"><Undo2 size={15}/><span>Undo edit</span></Button>
            <Disclosure label={exporting?'Preparing…':'Export'} icon={exporting?<Loader2 size={15} className="spin"/>:<Download size={15}/>} className="export-menu"><span className="export-scope">All {figure(project.count)} objects · this image</span><Button disabled={exporting} onClick={exportMeasurements}>All objects CSV</Button>{queueActive||uploading?<><span className="export-unavailable">Pause the queue for image archives</span></>:<><a download href={`/api/projects/${project.id}/export/analysis.zip`}>Analysis bundle</a><a download href={`/api/projects/${project.id}/export/training.zip`}>Image / mask pairs</a></>}</Disclosure>
          </>}
          {!rightOpen&&<Button aria-label="Show inspector" title="Show inspector" onClick={()=>setRightOpen(true)}><PanelRightOpen size={18}/></Button>}
        </div></div>
        {opening&&<div className="opening-status" role="status"><Loader2 size={14} className="spin"/>Opening saved image…</div>}
        {running&&<div className="job-status" role="status"><div><Loader2 className="spin" size={17}/><strong>{project.stage}</strong><span>{project.progress}% · {duration(elapsed)}</span></div><progress max="100" value={project.progress}/><small>{project.completed_tiles} / {project.total_tiles||'—'} tiles predicted{computeLabel(project.compute)?` · ${computeLabel(project.compute)}`:''}</small></div>}
        {project?.status==='complete'&&<div className="metrics image-summary">
          <div className="metric-card metric-mint"><span>Detected objects</span><strong>{figure(project.count)}</strong><MetricGraphic type="count"/></div>
          <div className="metric-card metric-pink"><span>Mean area</span><strong>{project.count?project.mean_area.toFixed(1):'—'}{project.count>0&&<small> px²</small>}</strong><MetricGraphic type="area"/></div>
          <div className="metric-card metric-sand"><span>Mean circularity</span><strong>{project.count?project.mean_circularity.toFixed(3):'—'}</strong><MetricGraphic type="circularity" value={project.mean_circularity}/></div>
          <div className="metric-card metric-lilac"><span>Analysis time</span><strong>{duration(project.elapsed_seconds||0)}</strong><MetricGraphic type="time"/></div>
        </div>}
        {project&&<div className="layer-bar"><span><Layers size={14}/>Display</span><SegmentedControl value={layer} onChange={setLayer} label="Image display layer" options={[{value:'raw',label:'Original',icon:<ImageIcon size={13}/>},{value:'labels',label:'Objects',icon:<ScanLine size={13}/>,disabled:project.status!=='complete'},{value:'probability',label:'Probability',disabled:project.status!=='complete'}]}/><Button className="focus-image" onClick={focusImage} aria-pressed={!leftOpen&&!rightOpen} title="Toggle side panels"><Maximize2 size={15}/>Focus image</Button></div>}
        <Viewer focusRegion={focusRegion} project={project} layer={layer} selected={selected} onSelect={selectCell} cells={cells} onAdd={points=>edit({points})} editingDisabled={busy||opening} onOpen={()=>input.current.click()}/>
      </main>
      {rightOpen&&<aside className={`inspector ${exploring&&!showTiles?'exploring':''}`}>
        <div className="panel-heading inspector-mode-heading"><SegmentedControl value={showTiles?'tiles':'measurements'} onChange={value=>setShowTiles(value==='tiles')} label="Inspector view" options={[{value:'measurements',label:'Measurements',icon:<List size={14}/>},{value:'tiles',label:'Tiles',icon:<Grid2X2 size={14}/>}]} /><Button aria-label="Hide inspector" title="Hide inspector" onClick={()=>{setRightOpen(false);setMobilePane('image');}}><PanelRightClose size={17}/></Button></div>
        {!showTiles&&selectedCell&&<SelectedCell cell={selectedCell} busy={busy} onClear={()=>setSelected(null)} onRemove={()=>edit({delete_id:selectedCell.id})}/>}
        {showTiles&&project?<TileLibrary project={project} cells={cells} onNavigate={tile=>{setSelected(null);setFocusRegion({...tile,sequence:Date.now()});setMobilePane('image');}}/>:project?.status==='complete'?<>
          <ObjectExplorer key={project.id} project={project} cells={cells} selected={selected} onInspect={inspectCell} expanded={exploring} onExpandedChange={setExploring}/>
          {!exploring&&<div className="measurement-body">
            <section className="distributions" aria-label="Image distributions"><DensityPlot cells={cells} field="area" title="Area (px²)"/><DensityPlot cells={cells} field="circularity" title="Circularity"/></section>
            <div className="object-list-heading"><h2>Objects <span>{cells.length.toLocaleString()}</span></h2><label className="search-label">Find by ID<input type="search" inputMode="numeric" value={filter} onChange={e=>{setFilter(e.target.value);setTableLimit(100);}} placeholder="Cell ID"/></label></div>
            <div className="object-range">{filtered.length?`1–${Math.min(tableLimit,filtered.length)} of ${figure(filtered.length)}`:'0 objects'}</div>
            <div className="object-table" tabIndex={0} role="region" aria-label="Object measurements"><table><thead><tr><th scope="col">Cell</th><th scope="col">Area px²</th><th scope="col">Circularity</th></tr></thead><tbody>{tableRows.map((c,index)=><tr key={c.id} className={selected===c.id?'selected':''}><td><Button tabIndex={selected===c.id||(!tableHasSelected&&index===0)?0:-1} onKeyDown={event=>tableKey(event,index)} aria-pressed={selected===c.id} onClick={()=>inspectCell(c.id)}>#{c.id}{c.manual?' · M':''}</Button></td><td>{figure(c.area)}</td><td>{c.circularity.toFixed(3)}</td></tr>)}</tbody></table>
              {filtered.length>tableLimit&&<Button className="load-objects" onClick={()=>setTableLimit(value=>value+100)}>Show {Math.min(100,filtered.length-tableLimit)} more objects</Button>}
              {!filtered.length&&<p className="table-note">{opening?'Loading measurements…':filter?'No matching cell ID.': 'No objects detected. The full image remains available to inspect.'}</p>}
            </div>
          </div>}
        </>:<div className="inspector-empty"><FolderOpen size={26}/><p>{running?'Measurements will appear when analysis finishes.':'Analyze an image to inspect its objects and measurements.'}</p></div>}
      </aside>}
    </div>
    </>}
  </div>;
}
