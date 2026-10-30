import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';

import {Maximize2,ZoomIn,ZoomOut,MousePointer2,Pencil,Check,X} from 'lucide-react';

import {Button} from './components/ui';

import {CellMark} from './components/CellMark';



export default function Viewer({project,layer,selected,onSelect,cells,onAdd,editingDisabled,focusRegion,onOpen}) {

  const host=useRef(null), drag=useRef(null);

  const [size,setSize]=useState({width:800,height:600});

  const [view,setView]=useState({scale:1,x:0,y:0});

  const [keyboardMode,setKeyboardMode]=useState(false);

  const [drawing,setDrawing]=useState(false),[points,setPoints]=useState([]);

  const projectId=project?.id, imageWidth=project?.width,imageHeight=project?.height;

  const fit=useCallback(()=>{if(!imageWidth||!imageHeight)return;const s=Math.min(size.width/imageWidth,size.height/imageHeight)*.94;setView({scale:s,x:(size.width-imageWidth*s)/2,y:(size.height-imageHeight*s)/2});},[imageWidth,imageHeight,size.width,size.height]);

  useLayoutEffect(()=>{const o=new ResizeObserver(([entry])=>setSize({width:entry.contentRect.width,height:entry.contentRect.height}));o.observe(host.current);return()=>o.disconnect();},[]);

  useEffect(()=>{fit();},[projectId,fit]);

  useEffect(()=>{setPoints([]);setDrawing(false);},[projectId]);

  useEffect(()=>{if(!selected)return;const cell=cells.find(c=>c.id===selected);if(!cell)return;setView(v=>{const s=Math.max(v.scale,1);return{scale:s,x:size.width/2-cell.x*s,y:size.height/2-cell.y*s};});},[selected,cells,size.width,size.height]);

  useEffect(()=>{if(!focusRegion)return;const s=Math.min(size.width/focusRegion.width,size.height/focusRegion.height)*.9;setView({scale:s,x:size.width/2-(focusRegion.x+focusRegion.width/2)*s,y:size.height/2-(focusRegion.y+focusRegion.height/2)*s});},[focusRegion,size.width,size.height]);

  useEffect(()=>{const escape=e=>{if(e.key==='Escape'){setDrawing(false);setPoints([]);}};window.addEventListener('keydown',escape);return()=>window.removeEventListener('keydown',escape);},[]);

  const zoom=useCallback((factor,anchor={x:size.width/2,y:size.height/2})=>setView(v=>{const scale=Math.max(.015,Math.min(8,v.scale*factor));return{scale,x:anchor.x-(anchor.x-v.x)*scale/v.scale,y:anchor.y-(anchor.y-v.y)*scale/v.scale};}),[size.width,size.height]);

  useEffect(()=>{const element=host.current;const wheel=e=>{if(!projectId)return;e.preventDefault();const r=element.getBoundingClientRect();zoom(Math.exp(-e.deltaY*.0015),{x:e.clientX-r.left,y:e.clientY-r.top});};element.addEventListener('wheel',wheel,{passive:false});return()=>element.removeEventListener('wheel',wheel);},[projectId,zoom]);

  const imagePoint=e=>{const r=host.current.getBoundingClientRect();return{x:(e.clientX-r.left-view.x)/view.scale,y:(e.clientY-r.top-view.y)/view.scale};};

  const actualPixels=()=>setView(v=>({scale:1,x:size.width/2-(size.width/2-v.x)/v.scale,y:size.height/2-(size.height/2-v.y)/v.scale}));

  const addPoint=p=>{if(p.x>=0&&p.y>=0&&p.x<project.width&&p.y<project.height)setPoints(v=>[...v,[p.x,p.y]]);};

  const inspectPoint=p=>{const near=cells.filter(c=>p.x>=c.bbox[1]&&p.x<c.bbox[3]&&p.y>=c.bbox[0]&&p.y<c.bbox[2]);onSelect(near.length?near.reduce((a,b)=>Math.hypot(a.x-p.x,a.y-p.y)<Math.hypot(b.x-p.x,b.y-p.y)?a:b).id:null);};

  const savePolygon=async()=>{if(points.length>=3&&!editingDisabled&&await onAdd(points)){setPoints([]);setDrawing(false);}};

  const keyDown=e=>{

    if(!project)return;

    const keys=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','f','F','0','1','Enter','Escape','Backspace'];

    if(!keys.includes(e.key))return;

    e.preventDefault();setKeyboardMode(true);

    const step=e.shiftKey?128:32;

    if(e.key.startsWith('Arrow'))setView(v=>({...v,x:v.x+(e.key==='ArrowLeft'?step:e.key==='ArrowRight'?-step:0),y:v.y+(e.key==='ArrowUp'?step:e.key==='ArrowDown'?-step:0)}));

    else if(e.key==='+'||e.key==='=')zoom(1.4);

    else if(e.key==='-')zoom(1/1.4);

    else if(['f','F','0'].includes(e.key))fit();

    else if(e.key==='1')actualPixels();

    else if(e.key==='Escape'){setDrawing(false);setPoints([]);onSelect(null);}

    else if(e.key==='Backspace'&&drawing)setPoints(v=>v.slice(0,-1));

    else if(e.key==='Enter'){const center={x:(size.width/2-view.x)/view.scale,y:(size.height/2-view.y)/view.scale};if(drawing){if(e.ctrlKey||e.metaKey)savePolygon();else addPoint(center);}else inspectPoint(center);}

  };

  const tiles=[];

  if(project){

    const level=Math.max(0,Math.min(8,Math.floor(Math.log2(1/view.scale))));

    const span=512*2**level;

    const x0=Math.max(0,Math.floor(-view.x/view.scale/span)),y0=Math.max(0,Math.floor(-view.y/view.scale/span));

    const x1=Math.min(Math.ceil(project.width/span),Math.ceil((size.width-view.x)/view.scale/span));

    const y1=Math.min(Math.ceil(project.height/span),Math.ceil((size.height-view.y)/view.scale/span));

    for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){

      const style={left:x*span,top:y*span,width:Math.min(span,project.width-x*span),height:Math.min(span,project.height-y*span)};

      const base=`/api/projects/${project.id}/tiles`;

      tiles.push(<div className="image-tile" style={style} key={`${level}-${x}-${y}`}><img draggable="false" alt="" src={`${base}/raw/${level}/${x}/${y}`} />{layer!=='raw'&&project.status==='complete'&&<img draggable="false" alt="" className="tile-layer" src={`${base}/${layer}/${level}/${x}/${y}?revision=${project.revision}`} />}</div>);

    }

  }

  const chosen=cells.find(c=>c.id===selected);

  const pointerDown=e=>{

    if(!project)return;

    e.currentTarget.focus();setKeyboardMode(false);

    if(drawing){addPoint(imagePoint(e));return;}

    drag.current={x:e.clientX,y:e.clientY,start:view,moved:false};e.currentTarget.setPointerCapture(e.pointerId);

  };

  const pointerMove=e=>{if(!drag.current)return;const d=drag.current;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.abs(dx)+Math.abs(dy)>3)d.moved=true;setView({...d.start,x:d.start.x+dx,y:d.start.y+dy});};

  const pointerUp=e=>{if(!drag.current)return;const moved=drag.current.moved;drag.current=null;if(!moved)inspectPoint(imagePoint(e));};

  return <div className="viewer-shell">

    <div className="viewer-toolbar"><div className="tool-group"><Button title="Zoom out" aria-label="Zoom out" disabled={!project} onClick={()=>zoom(1/1.4)}><ZoomOut size={17}/></Button><span className="zoom-value">{project?`${Math.round(view.scale*100)}%`:'—'}</span><Button title="Zoom in" aria-label="Zoom in" disabled={!project} onClick={()=>zoom(1.4)}><ZoomIn size={17}/></Button><Button onClick={fit} disabled={!project}><Maximize2 size={16}/>Fit image</Button><Button disabled={!project} onClick={actualPixels}>1:1</Button></div>

    {project?.status==='complete'&&<div className="tool-group"><Button className={drawing?'active':''} disabled={editingDisabled} onClick={()=>{setDrawing(!drawing);setPoints([]);host.current?.focus();}}>{drawing?<MousePointer2 size={16}/>:<Pencil size={16}/>} {drawing?'Stop drawing':'Add object'}</Button>{drawing&&<><Button disabled={points.length<3||editingDisabled} onClick={savePolygon}><Check size={16}/>Save polygon</Button><Button aria-label="Clear polygon" onClick={()=>setPoints([])}><X size={16}/></Button></>}</div>}</div>

    <div ref={host} tabIndex={project?0:-1} role="region" aria-label="Image viewer" onKeyDown={keyDown} onBlur={()=>setKeyboardMode(false)} className={`image-viewport ${drawing?'drawing':''}`} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={()=>{drag.current=null;}}>

      {!project?<div className="viewer-empty"><div className="empty-mark"><CellMark/></div><h2>Your field of view, in full detail.</h2><p>Open a microscopy image to start a saved local analysis.</p><Button variant="primary" onClick={onOpen}>Open image</Button></div>:<div className="image-world" style={{width:project.width,height:project.height,transform:`translate(${view.x}px,${view.y}px) scale(${view.scale})`}}>{tiles}<svg viewBox={`0 0 ${project.width} ${project.height}`} className="annotation-svg" aria-label="Image annotations">{focusRegion&&<rect x={focusRegion.x} y={focusRegion.y} width={focusRegion.width} height={focusRegion.height} fill="none" stroke="#efe0a9" strokeWidth={2/view.scale} strokeDasharray={`${6/view.scale} ${4/view.scale}`}/>}{chosen&&<><rect x={chosen.bbox[1]-4/view.scale} y={chosen.bbox[0]-4/view.scale} width={chosen.bbox[3]-chosen.bbox[1]+8/view.scale} height={chosen.bbox[2]-chosen.bbox[0]+8/view.scale} fill="none" stroke="#ffe66d" strokeWidth={2/view.scale}/><text x={chosen.bbox[1]} y={chosen.bbox[0]-8/view.scale} fontSize={14/view.scale} fill="#ffe66d">#{chosen.id}</text></>}{points.length>0&&<polygon points={points.map(p=>p.join(',')).join(' ')} fill="#51cc8070" stroke="#5fffa0" strokeWidth={2/view.scale}/>}</svg></div>}

      {project&&drawing&&<div className="viewer-hint" role="status">{points.length} vertices · {keyboardMode?'Enter adds a point · Ctrl+Enter saves':'Click around the object, then Save polygon'} · Esc cancels</div>}

      {project&&keyboardMode&&<div className="viewer-crosshair" aria-hidden="true"/>}

    </div>

  </div>;

}
