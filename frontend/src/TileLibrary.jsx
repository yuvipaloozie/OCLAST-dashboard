import {useEffect,useMemo,useRef,useState} from 'react';
import {Eye,EyeOff} from 'lucide-react';
import {Button} from './components/ui';

export default function TileLibrary({project,cells,onNavigate}) {
  const [masks,setMasks]=useState(true),[selected,setSelected]=useState(null);
  const grid=useRef(null);
  const columns=Math.ceil(project.width/512),rows=Math.ceil(project.height/512);
  const tiles=useMemo(()=>{
    const counts=new Map();
    for(const cell of cells){const key=`${Math.floor(cell.y/512)}:${Math.floor(cell.x/512)}`;counts.set(key,(counts.get(key)||0)+1);}
    return Array.from({length:columns*rows},(_,index)=>{
      const row=Math.floor(index/columns),column=index%columns;
      return {index,row,column,x:column*512,y:row*512,width:Math.min(512,project.width-column*512),height:Math.min(512,project.height-row*512),count:counts.get(`${row}:${column}`)||0};
    });
  },[columns,rows,project.width,project.height,cells]);
  useEffect(()=>{setSelected(null);if(grid.current)grid.current.scrollTop=0;},[project.id]);
  const complete=project.status==='complete';
  return <section className="tile-library" aria-label="Image tile library">
    <div className="tile-library-controls"><div><strong>{tiles.length.toLocaleString()} tiles</strong><small>Up to 512 × 512 px · all image regions</small></div><Button disabled={!complete} aria-pressed={masks} onClick={()=>setMasks(v=>!v)} title="Toggle mask overlays">{masks?<Eye size={14}/>:<EyeOff size={14}/>}Masks {masks?'on':'off'}</Button></div>
    <div ref={grid} className="tile-library-grid" role="region" aria-label="Tile thumbnails" tabIndex={0}>
      {tiles.map(tile=>{
        const base=`/api/projects/${project.id}/tiles`;
        return <button key={`${project.id}-${tile.index}`} className={`tile-card ${selected===tile.index?'selected':''}`} aria-pressed={selected===tile.index} aria-label={`View tile ${tile.index+1}, y ${tile.y}, x ${tile.x}${complete?`, ${tile.count} object centers`:''}`} onClick={()=>{setSelected(tile.index);onNavigate(tile);}}>
          <div className="tile-thumbnail"><img loading="lazy" alt={`Original tile ${tile.index+1}`} src={`${base}/raw/0/${tile.column}/${tile.row}`}/>{masks&&complete&&<img loading="lazy" className="tile-mask-thumbnail" alt="" src={`${base}/labels/0/${tile.column}/${tile.row}?revision=${project.revision}`}/>}<span className="tile-number">{String(tile.index+1).padStart(3,'0')}</span></div>
          <div className="tile-caption"><strong>Tile {tile.index+1}</strong><small>y{tile.y} · x{tile.x}</small><span>{complete?`${tile.count} object ${tile.count===1?'center':'centers'}`:`${tile.width} × ${tile.height} px`}</span></div>
        </button>;
      })}
    </div>
  </section>;
}
