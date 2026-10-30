import {useMemo, useState} from 'react';
import {estimateDensity} from './density';
import './density.css';

export default function DensityPlot({cells, field, title}) {
  const [focused, setFocused] = useState(true);
  const bounded = field === 'circularity';
  const {points, min, max, count, outside} = useMemo(() => estimateDensity(cells.map(c => c[field]), bounded, focused), [cells, field, bounded, focused]);
  const peak = Math.max(...points.map(p => p.y), Number.MIN_VALUE);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${((p.x - min) / (max - min) * 300).toFixed(2)},${(72 - p.y / peak * 64).toFixed(2)}`).join(' ');
  const format = x => bounded ? x.toFixed(2) : Math.round(x).toLocaleString();
  return <figure className="density-plot">
    <figcaption><span>{title}</span><button className="density-range" aria-label={`${title}: ${focused ? 'show full range' : 'focus on distribution'}`} onClick={() => setFocused(!focused)}>{focused ? 'Full' : 'Focus'}</button></figcaption>
    {count ? <svg viewBox="0 0 300 76" preserveAspectRatio="none" role="img" aria-label={`${title}: smoothed density of ${count} objects, ${focused ? 'focused' : 'full'} range ${format(min)} to ${format(max)}, ${outside} objects outside view`}>
      <title>{`${count.toLocaleString()} objects · relative density · all values included`}</title>
      {[24,48,72].map(y => <line key={y} x1="0" x2="300" y1={y} y2={y} className="density-grid"/>)}
      <path d={`${path} L300,72 L0,72 Z`} fill="#825493" fillOpacity=".14"/>
      <path d={path} className="density-line"/>
    </svg> : <div className="density-empty">No objects to plot</div>}
    <div className="density-axis"><span>{format(min)}</span><span>{format((min + max) / 2)}</span><span>{format(max)}</span></div>
    <div className="density-caption">{focused ? 'Focused' : 'Full range'} · {outside ? `${outside.toLocaleString()} outside view` : 'all objects in view'}</div>
  </figure>;
}
