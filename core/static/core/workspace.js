/* Phase 5 — Scientific Workspace */
const WS_OWNER = localStorage.getItem('wsOwner') || (localStorage.setItem('wsOwner', crypto.randomUUID()), localStorage.getItem('wsOwner'));
async function wsApi(path, opts={}){
  opts.headers = Object.assign({'Content-Type':'application/json','X-Owner':WS_OWNER}, opts.headers||{});
  const r = await fetch(path, opts);
  return {ok:r.ok, status:r.status, data: await r.json().catch(()=>({}))};
}
async function loadAnalyses(){
  const el=document.getElementById('wsList'); if(!el) return;
  const r = await wsApi('/api/analyses/?owner='+WS_OWNER);
  const items = r.data.analyses||[];
  const T = (typeof tr!=='undefined' && tr && tr[lang]) || {};
  if(!items.length){ el.innerHTML = emptyState('🧪', T.ws_empty||'No saved analyses'); return; }
  el.innerHTML = items.map(a=>{
    return `<div class="analysis-card">
      <div class="analysis-head"><b>${esc(a.title||('#'+a.id))}</b><span class="pill">${esc(a.analysis_type)}</span></div>
      <div class="analysis-meta muted" style="font-size:12px">${esc(a.data_source||'')} · ${esc((a.created_at||'').slice(0,10))} · v:${esc(a.dataset_version||'—')}</div>
      <div class="row" style="gap:6px;margin-top:8px">
        <button class="btn btn-ghost btn-sm" onclick="reproduceAnalysis(${a.id})">${T.ws_reproduce||'Reproduce'}</button>
        <a class="btn btn-ghost btn-sm" href="/api/analyses/${a.id}/export/?format=csv&owner=${WS_OWNER}" download>${T.ws_export_csv||'CSV'}</a>
        <a class="btn btn-ghost btn-sm" href="/api/analyses/${a.id}/export/?format=pdf&owner=${WS_OWNER}" download>${T.ws_export_pdf||'PDF'}</a>
        <button class="btn btn-ghost btn-sm" onclick="deleteAnalysis(${a.id})">${T.ws_delete||'Delete'}</button>
      </div>
      <div id="repro-${a.id}" style="margin-top:8px"></div>
    </div>`;
  }).join('');
}
window.reproduceAnalysis = async id=>{
  const el=document.getElementById('repro-'+id); if(el) el.innerHTML='<div class="status">…</div>';
  const r = await wsApi('/api/analyses/'+id+'/reproduce/?owner='+WS_OWNER);
  if(el) el.innerHTML = r.ok ? '<pre class="code-block" style="max-height:200px;overflow:auto">'+esc(JSON.stringify(r.data.data||r.data,null,1).slice(0,2000))+'</pre>' : '<div class="status error">'+esc(r.data.error||(lang==='fa'?'خطا':'error'))+'</div>';
};
window.deleteAnalysis = async id=>{
  if(!confirm(lang==='fa'?'این تحلیل حذف شود؟':'Delete this analysis?')) return;
  await wsApi('/api/analyses/'+id+'/delete/', {method:'POST', body:'{}'});
  loadAnalyses();
};
document.getElementById('wsSave')?.addEventListener('click', async ()=>{
  const title=document.getElementById('wsTitle').value.trim()||'analysis';
  const type=document.getElementById('wsType').value;
  const params = type==='timeseries'
    ? {lat:+document.getElementById('tsLat').value, lon:+document.getElementById('tsLon').value,
       start:document.getElementById('tsStart').value, end:document.getElementById('tsEnd').value,
       parameters:(document.getElementById('tsParams').value||'').split(',').map(s=>s.trim()).filter(Boolean),
       baseline:{start:(document.getElementById('tsBaseline').value||'').split(',')[0],
                 end:(document.getElementById('tsBaseline').value||'').split(',')[1]}}
    : {lat:+document.getElementById('lat').value||null, lon:+document.getElementById('lon').value||null,
       start:document.getElementById('start')?.value||'', end:document.getElementById('end')?.value||'',
       parameters:(document.getElementById('powerParams')?.value||'').split(',').map(s=>s.trim()).filter(Boolean)};
  const r = await wsApi('/api/analyses/save/', {method:'POST', body:JSON.stringify({
    title, analysis_type:type, geo:{lat:params.lat,lon:params.lon},
    time_range:{start:params.start,end:params.end}, data_source:'NASA POWER / CMR',
    parameters:params, viz_settings:{}, dataset_version:'live'})});
  const st=document.getElementById('wsSaveStatus');
  const T=(typeof tr!=='undefined' && tr && tr[lang])||{};
  if(st) st.textContent = r.ok ? (T.ws_saved||(lang==='fa'?'ذخیره شد':'Saved')) : (r.data.error||(lang==='fa'?'خطا':'error'));
  if(r.ok) loadAnalyses();
});
document.getElementById('tsRun')?.addEventListener('click', async ()=>{
  const el=document.getElementById('tsResult'); el.innerHTML='<div class="status">…</div>';
  const qs=new URLSearchParams({lat:document.getElementById('tsLat').value,
    lon:document.getElementById('tsLon').value,
    start:document.getElementById('tsStart').value,end:document.getElementById('tsEnd').value,
    parameters:document.getElementById('tsParams').value});
  const bl=document.getElementById('tsBaseline').value.trim();
  if(bl){const parts=bl.split(','); if(parts[0])qs.set('baseline_start',parts[0].trim()); if(parts[1])qs.set('baseline_end',parts[1].trim());}
  const r=await fetch('/api/timeseries/?'+qs);
  const d=await r.json();
  if(!r.ok){el.innerHTML='<div class="status error">'+esc(d.error||(lang==='fa'?'خطا':'error'))+'</div>';return}
  const series=d.series||{};
  let h='<div class="analysis-grid">';
  for(const [pn,pts] of Object.entries(series)){
    const vals=pts.map(p=>p.value).filter(v=>v!=null);
    const avg=vals.length?(vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1):'—';
    const min=vals.length?Math.min(...vals).toFixed(1):'—';
    const max=vals.length?Math.max(...vals).toFixed(1):'—';
    h+=`<div class="analysis-card"><div class="analysis-head"><b>${esc(pn)}</b></div>
      <div class="analysis-meta">avg:${avg} min:${min} max:${max} n:${pts.length}</div>
      <canvas class="ts-chart" data-param="${esc(pn)}" height="80"></canvas></div>`;
  }
  h+='</div>'+(d.baseline_series?'<div class="status">'+(lang==='fa'?'مقایسه با دوره پایه: ':'baseline: ')+esc(d.comparison||'')+'</div>':'');
  el.innerHTML=h;
  document.querySelectorAll('.ts-chart').forEach(cv=>{
    const pn=cv.dataset.param, pts=(series[pn]||[]).map(p=>p.value).filter(v=>v!=null);
    if(pts.length<2) return;
    const ctx=cv.getContext('2d');
    const w=cv.width=cv.offsetWidth*2, h=cv.height=160;
    ctx.scale(2,2);
    const mn=Math.min(...pts), mx=Math.max(...pts), rg=mx-mn||1;
    ctx.strokeStyle='#4f8cff'; ctx.lineWidth=1.5; ctx.beginPath();
    pts.forEach((v,i)=>{const x=i/(pts.length-1)*cv.offsetWidth, y=cv.offsetHeight-((v-mn)/rg)*(cv.offsetHeight-10)-5; i?ctx.lineTo(x,y):ctx.moveTo(x,y)});
    ctx.stroke();
  });
});
