export function collectionSelection(completedIds,excluded) {
  return completedIds.filter(id=>!excluded.has(id));
}

export function formatMeasurement(value,decimals=0) {
  return value==null||!Number.isFinite(value)?'—':value.toLocaleString(undefined,{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

export function sortImageRows(projects,summaryById,query,sort) {
  const needle=query.trim().toLocaleLowerCase();
  const rows=projects.filter(project=>!needle||`${project.name} ${project.source_path||''}`.toLocaleLowerCase().includes(needle));
  return rows.sort((a,b)=>{
    if(sort==='name')return a.name.localeCompare(b.name,undefined,{numeric:true})||a.id.localeCompare(b.id);
    const field=sort==='count'?'count':sort==='area'?'median_area':'median_circularity';
    const value=project=>project.status==='complete'?(field==='count'?project.count:summaryById.get(project.id)?.[field]):null;
    const av=value(a),bv=value(b);
    if(av==null&&bv==null)return a.name.localeCompare(b.name,undefined,{numeric:true});
    if(av==null)return 1;if(bv==null)return -1;
    return bv-av||a.name.localeCompare(b.name,undefined,{numeric:true});
  });
}
