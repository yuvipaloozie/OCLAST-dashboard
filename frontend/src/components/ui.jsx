import {createContext,useContext} from 'react';
import * as ToggleGroupPrimitive from '@radix-ui/react-toggle-group';
import {Slot} from '@radix-ui/react-slot';
import {cva} from 'class-variance-authority';
import {clsx} from 'clsx';

// Adapted from shadcn/ui and 21st.dev's shadcn Toggle Group (MIT).
// OCLAST keeps its offline CSS tokens and existing public component API.
const buttonVariants=cva('ui-button',{
  variants:{variant:{outline:'',primary:'ui-button-primary',ghost:'ui-button-ghost'},size:{default:'',sm:'ui-button-sm',icon:'ui-button-icon'}},
  defaultVariants:{variant:'outline',size:'default'},
});

export function Button({variant='outline',size='default',className,type='button',asChild=false,...props}) {
  const Component=asChild?Slot:'button';
  return <Component type={asChild?undefined:type} data-slot="button" data-variant={variant} data-size={size} className={clsx(buttonVariants({variant,size}),className)} {...props}/>;
}

export function Badge({children,status='neutral',className}) {
  return <span className={clsx('ui-badge',className)} data-status={status}><i aria-hidden="true"/>{children}</span>;
}

const ToggleContext=createContext({size:'default'});
export function ToggleGroup({className,size='default',children,...props}) {
  return <ToggleGroupPrimitive.Root data-slot="toggle-group" className={clsx('ui-segmented',className)} {...props}>
    <ToggleContext.Provider value={{size}}>{children}</ToggleContext.Provider>
  </ToggleGroupPrimitive.Root>;
}
export function ToggleGroupItem({className,children,...props}) {
  const {size}=useContext(ToggleContext);
  return <ToggleGroupPrimitive.Item data-slot="toggle-group-item" data-size={size} className={clsx('ui-segment',className)} {...props}>{children}</ToggleGroupPrimitive.Item>;
}

/** Controlled single selection; re-clicking the active item keeps it selected. */
export function SegmentedControl({value,onChange,options,label}) {
  return <ToggleGroup type="single" value={value} onValueChange={next=>{if(next)onChange(next);}} aria-label={label} loop onFocusCapture={event=>{
    // Single-value display modes behave as radios: keyboard focus activates a mode.
    const next=event.target.closest('[data-value]')?.dataset.value;
    if(next&&next!==value)onChange(next);
  }}>
    {options.map(option=><ToggleGroupItem key={option.value} value={option.value} data-value={option.value} disabled={option.disabled}>{option.icon}<span>{option.label}</span></ToggleGroupItem>)}
  </ToggleGroup>;
}
