import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {ChevronDown,Eye,EyeOff,SlidersHorizontal} from 'lucide-react';
import {Button} from './components/ui';
import {axisFor,describe,fields,inRange,presetIds} from './objectInsights';
import './object-explorer.css';

const number=(v,d=0)=>v==null?'—':v.toLocaleString(undefined,{maximumFractionDigits:d});
const display=(v,field)=>number(v,field==='area'?0:3);
const interval=(low,high)=>low==null?'—':`${number(low)}–${number(high)}`;
const frame={left:42,right:288,top:12,bottom:177,width:300,height:214};

function ShapePlot({cells,selected,selection,onSelect,onRange,xField,yField,logArea}) {
  const svg=useRef(null),start=useRef(null);
  const [brush,setBrush]=useState(null),[hover,setHover]=useState(null);
  const x=useMemo(()=>axisFor(cells,xField,logArea),[cells,xField,logArea]);
  const y=useMemo(()=>axisFor(cells,yField,logArea),[cells,yField,logArea]);
  const ordered=useMemo(()=>[...cells].sort((a,b)=>a[xField]-b[xField]||a.id-b.id),[cells,xField]);
  const [active,setActive]=useState(null);
  const activeId=ordered.some(c=>c.id===active)?active:(selected??ordered[0]?.id);
  const selectedSet=useMemo(()=>selection===null?null:new Set(selection),[selection]);
  const point=e=>{const r=svg.current.getBoundingClientRect();return{x:Math.max(frame.left,Math.min(frame.right,(e.clientX-r.left)/r.width*frame.width)),y:Math.max(frame.top,Math.min(frame.bottom,(e.clientY-r.top)/r.height*frame.height))};};
  const finish=e=>{
    if(!start.current)return;
    const first=start.current,last=point(e);start.current=null;setBrush(null);
    if(Math.abs(first.x-last.x)+Math.abs(first.y-last.y)<5)return;
    onRange({x0:x.value((Math.min(first.x,last.x)-frame.left)/(frame.right-frame.left)),x1:x.value((Math.max(first.x,last.x)-frame.left)/(frame.right-frame.left)),
      y0:y.value((frame.bottom-Math.max(first.y,last.y))/(frame.bottom-frame.top)),y1:y.value((frame.bottom-Math.min(first.y,last.y))/(frame.bottom-frame.top))});
  };
  const keyPoint=(e,cell)=>{
    if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(cell.id,e.ctrlKey||e.metaKey||e.shiftKey);return;}
    const direction=['ArrowLeft','ArrowDown'].includes(e.key)?-1:['ArrowRight','ArrowUp'].includes(e.key)?1:0;
    if(!direction)return;e.preventDefault();
    const index=ordered.findIndex(c=>c.id===cell.id),next=ordered[(index+direction+ordered.length)%ordered.length];
    setActive(next.id);svg.current.querySelector(`[data-object-id="${next.id}"]`)?.focus();
  };
  return <figure className="object-plot">
    <div className="object-axis-label">{fields[yField].label}{yField==='area'?' (px²)':''}{logArea&&yField==='area'?' · log scale':''}</div>
    <svg ref={svg} viewBox={`0 0 ${frame.width} ${frame.height}`} role="group" aria-label="Object shape plot" onPointerDown={e=>{
      if(e.button!==0||e.target.closest('[data-object-id]'))return;
      start.current=point(e);setBrush({first:start.current,last:start.current});e.currentTarget.setPointerCapture(e.pointerId);
    }} onPointerMove={e=>{if(start.current)setBrush({first:start.current,last:point(e)});}} onPointerUp={finish} onPointerCancel={()=>{start.current=null;setBrush(null);}}>
      {[0,.5,1].map(p=><g key={p}><line x1={frame.left} x2={frame.right} y1={frame.bottom-p*(frame.bottom-frame.top)} y2={frame.bottom-p*(frame.bottom-frame.top)} className="object-gridline"/><text x={frame.left-6} y={frame.bottom-p*(frame.bottom-frame.top)+3} textAnchor="end">{display(y.value(p),yField)}</text><text x={frame.left+p*(frame.right-frame.left)} y={frame.bottom+16} textAnchor={p===0?'start':p===1?'end':'middle'}>{display(x.value(p),xField)}</text></g>)}
      {ordered.map(c=><circle key={c.id} data-object-id={c.id} cx={frame.left+x.position(c[xField])*(frame.right-frame.left)} cy={frame.bottom-y.position(c[yField])*(frame.bottom-frame.top)} r={c.id===selected?4.5:3} className={`object-dot ${selectedSet&&!selectedSet.has(c.id)?'muted':''} ${c.id===selected?'active':''}`} tabIndex={c.id===activeId?0:-1} role="button" aria-label={`Cell ${c.id}, ${fields[xField].label} ${display(c[xField],xField)}, ${fields[yField].label} ${display(c[yField],yField)}`} onClick={e=>onSelect(c.id,e.ctrlKey||e.metaKey||e.shiftKey)} onKeyDown={e=>keyPoint(e,c)} onMouseEnter={()=>setHover(c)} onMouseLeave={()=>setHover(null)} onFocus={()=>{setActive(c.id);setHover(c);}} onBlur={()=>setHover(null)}><title>{`Cell #${c.id} · ${fields[xField].label} ${display(c[xField],xField)} · ${fields[yField].label} ${display(c[yField],yField)}`}</title></circle>)}
      {brush&&<rect x={Math.min(brush.first.x,brush.last.x)} y={Math.min(brush.first.y,brush.last.y)} width={Math.abs(brush.last.x-brush.first.x)} height={Math.abs(brush.last.y-brush.first.y)} className="object-brush"/>}
      <text x={(frame.left+frame.right)/2} y={frame.height-3} textAnchor="middle" className="object-x-label">{fields[xField].label}{xField==='area'?' (px²)':''}{logArea&&xField==='area'?' · log scale':''}</text>
    </svg>
    <figcaption>{hover?`#${hover.id} · ${display(hover[xField],xField)} / ${display(hover[yField],yField)}`:'Click a point to inspect · drag to select a group'}</figcaption>
  </figure>;
}

function ObjectGallery({project,cells,selected,onInspect}) {
  const [sort,setSort]=useState('area-desc'),[masks,setMasks]=useState(true),[limit,setLimit]=useState(60);
  const host=useRef(null),sentinel=useRef(null),sortId=useId();
  const sorted=useMemo(()=>{
    const [field,direction]=sort.split('-');
    return [...cells].sort((a,b)=>(direction==='desc'?-1:1)*(a[field]-b[field])||a.id-b.id);
  },[cells,sort]);
  useEffect(()=>{setLimit(60);if(host.current)host.current.scrollTop=0;},[cells,sort,project.id]);
  useEffect(()=>{if(!sentinel.current||limit>=sorted.length)return;const observer=new IntersectionObserver(entries=>{if(entries[0].isIntersecting)setLimit(n=>Math.min(sorted.length,n+60));},{root:host.current,rootMargin:'120px'});observer.observe(sentinel.current);return()=>observer.disconnect();},[sorted.length,limit]);
  return <div className="object-gallery">
    <div className="object-gallery-controls"><label htmlFor={sortId}>Sort cells<select id={sortId} value={sort} onChange={e=>setSort(e.target.value)}><option value="area-desc">Largest first</option><option value="area-asc">Smallest first</option><option value="circularity-asc">Least circular first</option><option value="solidity-asc">Lowest solidity first</option><option value="eccentricity-desc">Most elongated first</option><option value="id-asc">Object ID</option></select></label><Button title="Toggle individual mask overlays" aria-label="Toggle object masks" aria-pressed={masks} onClick={()=>setMasks(v=>!v)}>{masks?<Eye size={14}/>:<EyeOff size={14}/>}</Button></div>
    <div className="object-gallery-grid" ref={host} role="region" aria-label="Individual cell gallery" tabIndex={0}>
      {sorted.slice(0,limit).map(c=><button key={c.id} className={`object-crop ${selected===c.id?'selected':''}`} aria-label={`Inspect cell ${c.id}, area ${number(c.area)} pixels squared, circularity ${c.circularity.toFixed(3)}`} aria-pressed={selected===c.id} onClick={()=>onInspect(c.id)}>
        <div className="object-crop-image"><img loading="lazy" decoding="async" alt={`Cell ${c.id}${masks?' with its mask':''}`} src={`/api/projects/${project.id}/objects/${c.id}/thumbnail?revision=${project.revision}&masks=${masks}`}/><span>#{c.id}</span></div><div className="object-crop-caption"><strong>{number(c.area)} <small>px²</small></strong><span>Circularity {c.circularity.toFixed(3)}</span></div>
      </button>)}
      {!cells.length&&<p className="object-gallery-empty">No objects in this selection.</p>}
      {limit<sorted.length&&<div ref={sentinel} className="object-gallery-more"><Button onClick={()=>setLimit(n=>Math.min(sorted.length,n+60))}>Show more cells</Button></div>}
    </div>
  </div>;
}

export default function ObjectExplorer({project,cells,selected,onInspect,expanded,onExpandedChange}) {
  const [xField,setXField]=useState('area'),[yField,setYField]=useState('circularity'),[logArea,setLogArea]=useState(false);
  const [selection,setSelection]=useState(null),[selectionLabel,setSelectionLabel]=useState('All objects'),[rangeOpen,setRangeOpen]=useState(false),[range,setRange]=useState({x0:'',x1:'',y0:'',y1:''}),[rangeError,setRangeError]=useState('');
  const xId=useId(),yId=useId();
  const validIds=useMemo(()=>new Set(cells.map(c=>c.id)),[cells]);
  const subset=useMemo(()=>{if(selection===null)return cells;const ids=new Set(selection);return cells.filter(c=>ids.has(c.id));},[cells,selection]);
  const stats=useMemo(()=>describe(subset),[subset]);
  useEffect(()=>{setSelection(null);setSelectionLabel('All objects');setRangeError('');},[project.id]);
  const selectRange=bounds=>{setSelection(inRange(cells,xField,yField,bounds));setSelectionLabel('Plot range');setRangeError('');onInspect(null);};
  const selectPoint=(id,add)=>{
    setSelection(previous=>{if(!add||previous===null)return[id];const ids=previous.filter(v=>validIds.has(v));return ids.includes(id)?ids.filter(v=>v!==id):[...ids,id];});
    setSelectionLabel('Selected objects');onInspect(id);
  };
  const setAxis=(axis,value)=>{if(axis==='x')setXField(value);else setYField(value);setRange({x0:'',x1:'',y0:'',y1:''});setRangeError('');};
  const applyRange=e=>{e.preventDefault();const bounds={};for(const key of ['x0','x1','y0','y1']){const v=range[key];bounds[key]=v.trim()===''?(key.endsWith('0')?-Infinity:Infinity):Number(v);if(Number.isNaN(bounds[key])){setRangeError('Enter numeric limits.');return;}}if(bounds.x0>bounds.x1||bounds.y0>bounds.y1){setRangeError('Each minimum must be less than or equal to its maximum.');return;}selectRange(bounds);};
  return <section className={`object-explorer ${expanded?'expanded':''}`} aria-label="Explore objects">
    <button className="explorer-toggle" aria-expanded={expanded} onClick={()=>onExpandedChange(!expanded)}><span>Explore objects <small>{cells.length.toLocaleString()}</small></span><ChevronDown size={15}/></button>
    {expanded&&<div className="explorer-content">
      <div className="object-axis-controls"><label htmlFor={xId}>Plot X<select id={xId} value={xField} onChange={e=>setAxis('x',e.target.value)}>{Object.entries(fields).map(([key,field])=><option key={key} value={key} disabled={key===yField}>{field.label}</option>)}</select></label><label htmlFor={yId}>Plot Y<select id={yId} value={yField} onChange={e=>setAxis('y',e.target.value)}>{Object.entries(fields).map(([key,field])=><option key={key} value={key} disabled={key===xField}>{field.label}</option>)}</select></label></div>
      <div className="object-plot-tools"><label><input type="checkbox" checked={logArea} onChange={e=>setLogArea(e.target.checked)} disabled={xField!=='area'&&yField!=='area'}/>Log area</label><Button aria-expanded={rangeOpen} onClick={()=>setRangeOpen(v=>!v)}><SlidersHorizontal size={12}/>Range</Button></div>
      <ShapePlot cells={cells} selected={selected} selection={selection} onSelect={selectPoint} onRange={selectRange} xField={xField} yField={yField} logArea={logArea}/>
      {rangeOpen&&<form className="object-range-form" onSubmit={applyRange}><div>{[['x0','X minimum'],['x1','X maximum'],['y0','Y minimum'],['y1','Y maximum']].map(([key,label])=><label key={key}>{label}<input type="number" step="any" placeholder="Any" value={range[key]} onChange={e=>setRange(r=>({...r,[key]:e.target.value}))}/></label>)}</div><Button type="submit">Select range</Button>{rangeError&&<p role="alert">{rangeError}</p>}</form>}
      <div className="object-presets">{[['all','All'],['largest','Largest 10%'],['least-round','Least circular 10%'],['edge','Image edges']].map(([key,label])=><Button key={key} aria-pressed={key==='all'?selection===null:selectionLabel===label} onClick={()=>{setSelection(presetIds(cells,key,project.width,project.height));setSelectionLabel(key==='all'?'All objects':label);setRangeError('');onInspect(null);}}>{label}</Button>)}</div>
      <div className="object-selection-heading"><strong>{selectionLabel}</strong><span>{subset.length.toLocaleString()} / {cells.length.toLocaleString()}</span></div>
      <dl className="object-summary"><div><dt>Median area</dt><dd>{number(stats.medianArea)} <small>px²</small></dd></div><div><dt>Median circularity</dt><dd>{number(stats.medianCircularity,3)}</dd></div><div><dt>Middle 50% of areas</dt><dd>{interval(stats.q1,stats.q3)}</dd></div><div><dt>10th–90th percentile</dt><dd>{interval(stats.p10,stats.p90)}</dd></div></dl>
      <ObjectGallery project={project} cells={subset} selected={selected} onInspect={onInspect}/>
      <p className="object-explorer-note">Shapes describe masks. Extreme values and edge contact are review cues, not biological classifications. Ctrl/Shift-click adds or removes plot points.</p>
    </div>}
  </section>;
}
