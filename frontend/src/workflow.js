export function duration(seconds) {
  if(!Number.isFinite(seconds))return '—';
  if(seconds>0&&seconds<1)return '<1s';
  const rounded=Math.max(0,Math.round(seconds));
  return rounded<60?`${rounded}s`:`${Math.floor(rounded/60)}m ${rounded%60}s`;
}

export function importFiles(files) {
  const accepted=[],issues=[];
  for(const file of files) {
    const path=file.webkitRelativePath||file.name;
    if(!/\.(tiff?|png|jpe?g)$/i.test(file.name)){issues.push({name:path,error:'Not a supported image type.'});continue;}
    if(!file.size||file.size>512*1024**2){issues.push({name:path,error:file.size?'Exceeds the 512 MB file limit.':'The file is empty.'});continue;}
    accepted.push(file);
  }
  return {accepted,issues};
}

export async function downloadCsv(url,fallback) {
  const response=await fetch(url);
  if(!response.ok) {
    let detail;
    try {detail=(await response.json()).detail;}catch{ /* Keep the readable fallback. */ }
    throw new Error(typeof detail==='string'?detail:'Could not prepare this export. Please try again.');
  }
  const disposition=response.headers.get('content-disposition')||'';
  const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i),plain=disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
  let filename=fallback;
  if(encoded){try{filename=decodeURIComponent(encoded[1]);}catch{ /* Use the fallback. */ }}
  else if(plain)filename=(plain[1]||plain[2]).trim();
  const urlObject=URL.createObjectURL(await response.blob());
  const anchor=document.createElement('a');anchor.href=urlObject;anchor.download=filename;document.body.append(anchor);anchor.click();anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(urlObject),1000);
  return filename;
}
