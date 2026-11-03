import {useMemo,useState} from 'react';
import {AlertCircle,CheckCircle2,Loader2,Pause,Play,RotateCcw,X} from 'lucide-react';
import {Button} from './components/ui';
import './batch-workspace.css';

export default function BatchQueue({queue,projects,onControl,onRetry,importing=false}) {
  const byId=useMemo(()=>new Map(projects.map(project=>[project.id,project])),[projects]);
  const [dismissedSignature,setDismissedSignature]=useState(null);
  if(!queue)return null;
  const pending=queue.pending_ids||[],failed=queue.failed_ids||[],completed=queue.completed_ids||[];
  const completedOnly=!queue.active_id&&!pending.length&&!failed.length;
  const completedSignature=completed.join('|');
  if(completedOnly&&completedSignature===dismissedSignature)return null;
  const active=queue.active_id?byId.get(queue.active_id):null;
  const total=new Set([...pending,...failed,...completed,...(queue.active_id?[queue.active_id]:[])]).size;
  if(!total)return null;
  const finished=completed.length+failed.length;
  const title=queue.paused?(queue.active_id?'Pausing after current image':'Queue paused'):queue.active_id?'Analyzing images':pending.length?'Images queued':failed.length?'Queue needs attention':'Batch complete';
  const progress=finished+(queue.active_id?Math.min(1,Math.max(0,(active?.progress||0)/100)):0);
  return <section className="batch-queue" aria-label="Analysis queue" data-state={queue.paused?'paused':queue.active_id||pending.length?'running':failed.length?'error':'complete'}>
    <div className="batch-queue-main">
      <span className="batch-queue-icon" aria-hidden="true">{queue.paused&&!queue.active_id?<Pause size={18}/>:queue.active_id||pending.length?<Loader2 size={18} className="spin"/>:failed.length?<AlertCircle size={18}/>:<CheckCircle2 size={18}/>}</span>
      <div className="batch-queue-title"><strong>{title}</strong><span role="status" aria-live="polite">{active?.name||(pending.length?`${pending.length} waiting`:failed.length?`${failed.length} failed`: `${completed.length} ${completed.length===1?'image':'images'} analyzed`)}</span></div>
      <span className="batch-queue-count">{finished} / {total}</span>
      <div className="batch-queue-actions">
        {queue.paused&&(pending.length>0||queue.active_id)?<Button size="sm" onClick={()=>onControl('resume')} disabled={importing}><Play size={14}/>Resume</Button>:(queue.active_id||pending.length>0)&&<Button size="sm" onClick={()=>onControl('pause')} disabled={importing}><Pause size={14}/>{queue.active_id?'Pause after image':'Pause'}</Button>}
        {pending.length>0&&<Button size="sm" onClick={()=>onControl('clear')} disabled={importing} title="Remove waiting images from the queue; saved images stay available"><X size={14}/>Clear waiting</Button>}
        {failed.length>0&&<Button size="sm" onClick={()=>onRetry(failed)} disabled={importing}><RotateCcw size={14}/>Retry {failed.length} failed</Button>}
        {completedOnly&&<Button variant="ghost" size="sm" onClick={()=>setDismissedSignature(completedSignature)} aria-label="Dismiss completed batch"><X size={14}/>Dismiss</Button>}
      </div>
    </div>
    <progress className="batch-queue-progress" aria-label="Images processed" value={progress} max={Math.max(total,1)}/>
    {(queue.active_id||pending.length>0||failed.length>0)&&<details className="batch-queue-details"><summary>{pending.length} waiting{failed.length?` · ${failed.length} failed`:''}</summary><ul>
      {pending.map(id=><li key={id}><span>{byId.get(id)?.name||'Waiting image'}</span><small>Queued</small></li>)}
      {failed.map(id=><li key={id}><span>{byId.get(id)?.name||'Image needing attention'}</span><small>{byId.get(id)?.error||'Analysis failed'}</small></li>)}
    </ul></details>}
  </section>;
}
