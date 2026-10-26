/** Local, dependency-light primitives following the 21st.dev/shadcn patterns.
 * References and adaptation notes: frontend/DESIGN.md.
 */
export function Button({variant='outline',size='default',className='',type='button',...props}) {
  return <button type={type} data-variant={variant} data-size={size} className={`ui-button ${className}`} {...props}/>;
}

export function Badge({children,status='neutral',className=''}) {
  return <span className={`ui-badge ${className}`} data-status={status}><i aria-hidden="true"/>{children}</span>;
}

/** Single-value segmented group, with native radio-group keyboard behavior. */
export function SegmentedControl({value,onChange,options,label}) {
  const enabled=options.filter(option=>!option.disabled);
  const move=(event)=>{
    let index=enabled.findIndex(option=>option.value===value);
    if(event.key==='ArrowRight'||event.key==='ArrowDown')index=(index+1)%enabled.length;
    else if(event.key==='ArrowLeft'||event.key==='ArrowUp')index=(index-1+enabled.length)%enabled.length;
    else if(event.key==='Home')index=0;
    else if(event.key==='End')index=enabled.length-1;
    else return;
    if(!enabled.length)return;
    event.preventDefault();
    const next=enabled[index];onChange(next.value);
    event.currentTarget.querySelector(`[data-value="${next.value}"]`)?.focus();
  };
  return <div className="ui-segmented" role="radiogroup" aria-label={label} onKeyDown={move}>{options.map(option=><button type="button" key={option.value} role="radio" aria-checked={value===option.value} tabIndex={value===option.value?0:-1} data-value={option.value} disabled={option.disabled} onClick={()=>onChange(option.value)}>{option.icon}{option.label}</button>)}</div>;
}
