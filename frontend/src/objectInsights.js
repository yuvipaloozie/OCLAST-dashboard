export const fields = {
  area:{label:'Area',unit:'px²'},
  circularity:{label:'Circularity',unit:''},
  solidity:{label:'Solidity',unit:''},
  eccentricity:{label:'Eccentricity',unit:''},
};

export function quantile(sorted,p) {
  if(!sorted.length)return null;
  const i=(sorted.length-1)*p, low=Math.floor(i), high=Math.ceil(i);
  return sorted[low]+(sorted[high]-sorted[low])*(i-low);
}

export function describe(cells) {
  const areas=cells.map(c=>c.area).sort((a,b)=>a-b);
  const circularity=cells.map(c=>c.circularity).sort((a,b)=>a-b);
  return {count:cells.length,medianArea:quantile(areas,.5),q1:quantile(areas,.25),q3:quantile(areas,.75),
    p10:quantile(areas,.1),p90:quantile(areas,.9),medianCircularity:quantile(circularity,.5)};
}

export function presetIds(cells,preset,width,height) {
  if(preset==='all')return null;
  if(preset==='edge')return cells.filter(c=>c.bbox[0]===0||c.bbox[1]===0||c.bbox[2]===height||c.bbox[3]===width).map(c=>c.id);
  const field=preset==='largest'?'area':'circularity',direction=preset==='largest'?-1:1;
  return [...cells].sort((a,b)=>direction*(a[field]-b[field])||a.id-b.id).slice(0,Math.ceil(cells.length*.1)).map(c=>c.id);
}

export function inRange(cells,xField,yField,range) {
  return cells.filter(c=>c[xField]>=range.x0&&c[xField]<=range.x1&&c[yField]>=range.y0&&c[yField]<=range.y1).map(c=>c.id);
}

export function axisFor(cells,field,logArea=false) {
  const log=logArea&&field==='area';
  const transform=v=>log?Math.log10(Math.max(v,1)):v;
  const values=cells.map(c=>transform(c[field])).filter(Number.isFinite);
  let min=values.length?values.reduce((a,b)=>Math.min(a,b),Infinity):0,max=values.length?values.reduce((a,b)=>Math.max(a,b),-Infinity):1;
  const padding=(max-min||Math.max(Math.abs(min)*.1,field==='area'?1:.02))*.07;
  min-=padding;max+=padding;
  if(!log)min=Math.max(0,min);
  if(field!=='area')max=Math.min(1,max);
  if(max<=min){min=Math.max(0,min-.01);max=min+.02;}
  const inverse=v=>log?10**v:v;
  return {min:inverse(min),max:inverse(max),mid:inverse((min+max)/2),
    position:v=>(transform(v)-min)/(max-min),value:p=>inverse(min+p*(max-min))};
}
