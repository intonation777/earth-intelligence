/* Farmer Dashboard JS — vanilla, RTL, Persian */

/* ---------- i18n ---------- */
function applyFarmerI18n(){
  document.documentElement.lang = getFarmerLang();
  document.documentElement.dir = getFarmerLang() === 'fa' ? 'rtl' : 'ltr';
  document.title = t('app_title');
  document.querySelectorAll('[data-i18n]').forEach(el=>{ el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-aria]').forEach(el=>{ el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
  const lb = $('langBtn'); if(lb) lb.textContent = getFarmerLang() === 'fa' ? 'EN' : 'فا';
}
window.toggleFarmerLang = ()=>{ setFarmerLang(getFarmerLang() === 'fa' ? 'en' : 'fa'); applyFarmerI18n(); if(typeof currentTab!=='undefined')switchTab(currentTab); };
const $=id=>document.getElementById(id);
const state={key:localStorage.getItem('farmerKey')||'',farmer:null,fields:[],fieldId:null,farmId:null,onboardFarmId:null,onboardFieldId:null};

function api(path,opts={}){
  opts.headers=Object.assign({'X-Farmer-Key':state.key,'Content-Type':'application/json'},opts.headers||{});
  return fetch(path,opts).then(r=>r.json().then(d=>({ok:r.ok,status:r.status,data:d})));
}
function post(path,body){return api(path,{method:'POST',body:JSON.stringify(body)})}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(msg){const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);requestAnimationFrame(()=>t.classList.add('show'));setTimeout(()=>{t.classList.remove('show');setTimeout(()=>t.remove(),300)},2500)}
function skeleton(n=3){return Array(n).fill('<div class="skeleton"></div>').join('')}
function confirmDialog(title,msg){return new Promise(res=>{
  const o=document.createElement('div');o.className='ei-modal-overlay';
  o.innerHTML=`<div class="ei-modal"><h3>${esc(title)}</h3><p>${esc(msg)}</p>
    <div class="row"><button class="btn btn-ghost" id="cfNo">${t('cancel_btn')}</button>
    <button class="btn btn-primary" id="cfYes" style="width:auto">${t('confirm_btn')}</button></div></div>`;
  document.body.appendChild(o);
  o.querySelector('#cfNo').onclick=()=>{o.remove();res(false)};
  o.querySelector('#cfYes').onclick=()=>{o.remove();res(true)};
  o.onclick=e=>{if(e.target===o){o.remove();res(false)}};
})}

/* ---------- Theme ---------- */
function applyTheme(){
  const t=localStorage.getItem('theme')||(window.matchMedia&&matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  document.documentElement.dataset.theme=t;
  const b=$('themeBtn');if(b)b.textContent=t==='dark'?'☀️':'🌙';
}
$('themeBtn').onclick=()=>{
  const t=document.documentElement.dataset.theme==='dark'?'light':'dark';
  document.documentElement.dataset.theme=t;localStorage.setItem('theme',t);
  $('themeBtn').textContent=t==='dark'?'☀️':'🌙';
};
applyTheme();
$('logoutBtn')&&($('logoutBtn').onclick=async()=>{
  await api('/api/farmer/logout/',{method:'POST',body:'{}'});
  localStorage.removeItem('farmerKey');state.key='';state.farmer=null;location.reload();
});

/* ---------- Auth & Onboarding ---------- */
function afterAuth(data){
  state.farmer=data.farmer||null;
  state.key=(state.farmer&&state.farmer.api_key)||state.key||'';
  if(state.key)localStorage.setItem('farmerKey',state.key);
  showOnboardStep2();
}
function renderAuth(mode='login'){
  const box=$('authBox');if(!box)return;
  const isLogin=mode==='login',isKey=mode==='key',isReg=mode==='register';
  const cls=m=>mode===m?'ei-btn-primary':'ei-btn-ghost';
  box.innerHTML=`
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button type="button" class="ei-btn ${cls('login')}" id="authTabLogin" style="flex:1">${t('auth_login')}</button>
      <button type="button" class="ei-btn ${cls('register')}" id="authTabRegister" style="flex:1">${t('auth_register')}</button>
      <button type="button" class="ei-btn ${cls('key')}" id="authTabKey" style="flex:1">${t('auth_api_key')}</button>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px;text-align:start">
      ${isKey?`<input id="authApiKey" class="ei-input" placeholder="${t('auth_api_key')}" autocomplete="off">`:`
        ${isReg?`<input id="authName" class="ei-input" placeholder="${t('auth_name')}" autocomplete="name">`:''}
        <input id="authLogin" class="ei-input" placeholder="${t('auth_identifier')}" autocomplete="username">
        <input id="authPassword" class="ei-input" type="password" placeholder="${t('auth_password')}" autocomplete="${isLogin?'current-password':'new-password'}">
        ${isReg?`<input id="authPhone" class="ei-input" placeholder="${t('auth_phone')}" autocomplete="tel">`:''}`}
      <button id="authSubmit" class="ei-btn ei-btn-primary ei-btn-lg">${isKey?t('auth_submit_key'):(isLogin?t('auth_submit_login'):t('auth_submit_register'))}</button>
      <p class="muted" style="font-size:.78rem;margin:0">${isKey?t('auth_key_hint'):t('auth_password_hint')}</p>
    </div>`;
  $('authTabLogin').onclick=()=>renderAuth('login');
  $('authTabRegister').onclick=()=>renderAuth('register');
  $('authTabKey').onclick=()=>renderAuth('key');
  $('authSubmit').onclick=async()=>{
    if(isKey){
      const key=$('authApiKey').value.trim();
      if(!key){$('onboardErr').textContent=t('auth_key_required');return}
      const r=await post('/api/farmer/login/',{api_key:key});
      if(!r.ok){$('onboardErr').textContent=r.data.error||t('error_fallback');return}
      afterAuth(r.data);return;
    }
    const loginId=$('authLogin').value.trim(),password=$('authPassword').value;
    if(!loginId||!password){$('onboardErr').textContent=t('auth_required');return}
    const payload={login:loginId,password};
    if(isReg){
      const name=$('authName').value.trim();
      if(!name){$('onboardErr').textContent=t('enter_name');return}
      payload.name=name;payload.phone=($('authPhone')&&$('authPhone').value.trim())||'';
    }
    const r=await post(isLogin?'/api/farmer/login/':'/api/farmer/register/',payload);
    if(!r.ok){$('onboardErr').textContent=r.data.error||t('error_fallback');return}
    afterAuth(r.data);
  };
}
function showOnboardStep2(){
  $('onboard').querySelector('.onboard-card').innerHTML=`
    <div class="logo">🏡</div>
    <h1>${t('add_farm_title')}</h1>
    <p class="muted">${t('add_farm_sub')}</p>
    <div style="text-align:start;display:flex;flex-direction:column;gap:10px">
      <input id="obFarmName" class="ei-input" placeholder="${t('farm_name_ph')}">
      <input id="obFieldName" class="ei-input" placeholder="${t('field_name_ph')}">
      <div style="display:flex;gap:8px">
        <input id="obFieldLat" class="ei-input" type="number" step="0.0001" placeholder="${t('lat_ph')}">
        <input id="obFieldLon" class="ei-input" type="number" step="0.0001" placeholder="${t('lon_ph')}">
      </div>
      <input id="obFieldArea" class="ei-input" type="number" step="0.1" placeholder="${t('area_ph')}">
    </div>
    <button id="btnObFarm" class="ei-btn ei-btn-primary ei-btn-lg" style="margin-top:14px">${t('register_start')}</button>
    <button id="btnObSkip" class="ei-btn ei-btn-ghost" style="margin-top:8px">${t('add_later')}</button>
    <p id="onboardErr" class="error"></p>`;
  $('btnObSkip').onclick=boot;
  $('btnObFarm').onclick=async()=>{
    const fn=$('obFarmName').value.trim(),fld=$('obFieldName').value.trim();
    if(!fn||!fld){$('onboardErr').textContent=t('enter_farm_field');return}
    const fr=await post('/api/farmer/farms/create/',{name:fn});
    if(!fr.ok){$('onboardErr').textContent=fr.data.error||t('error_fallback');return}
    const farmId=fr.data.farm?.id||fr.data.id;
    const r=await post('/api/farmer/fields/create/',{farm_id:farmId,name:fld,
      lat:$('obFieldLat').value||null,lon:$('obFieldLon').value||null,area_ha:$('obFieldArea').value||null});
    if(!r.ok){$('onboardErr').textContent=r.data.error||t('field_save_err');return}
    state.onboardFarmId=farmId;state.onboardFieldId=r.data.field?.id||r.data.id||null;
    await loadFields();showOnboardStep3();
  };
}
async function showOnboardStep3(){
  if(!state.onboardFieldId){boot();return}
  const cr=await api('/api/farmer/crops/');
  const crops=cr.data.crops||[];
  if(!crops.length){boot();return}
  $('onboard').querySelector('.onboard-card').innerHTML=`
    <div class="logo">🌱</div>
    <h1>${t('onboard_crop_title')}</h1>
    <p class="muted">${t('onboard_crop_sub')}</p>
    <div style="text-align:start;display:flex;flex-direction:column;gap:10px">
      <select id="obCrop" class="ei-select">${crops.map(c=>`<option value="${esc(c.key)}">${esc(getFarmerLang()==='en'?(c.name_en||c.name_fa):c.name_fa)}</option>`).join('')}</select>
      <input id="obPlantDate" class="ei-input" type="date">
    </div>
    <button id="btnObCrop" class="ei-btn ei-btn-primary ei-btn-lg" style="margin-top:14px">${t('onboard_start_crop')}</button>
    <button id="btnObCropSkip" class="ei-btn ei-btn-ghost" style="margin-top:8px">${t('add_later')}</button>
    <p id="onboardErr" class="error"></p>`;
  $('obPlantDate').value=new Date().toISOString().slice(0,10);
  $('btnObCropSkip').onclick=boot;
  $('btnObCrop').onclick=async()=>{
    const crop=$('obCrop').value,date=$('obPlantDate').value||new Date().toISOString().slice(0,10);
    const r=await post('/api/farmer/cycles/create/',{field_id:state.onboardFieldId,crop,planting_date:date});
    if(!r.ok){$('onboardErr').textContent=r.data.error||t('error_fallback');return}
    boot();
  };
}

/* ---------- Boot ---------- */
async function boot(){
  const p=await api('/api/farmer/me/');
  if(!p.ok){
    localStorage.removeItem('farmerKey');state.key='';state.farmer=null;
    renderAuth('login');$('onboard').classList.remove('hidden');return;
  }
  state.farmer=p.data.farmer;
  if(state.farmer&&state.farmer.api_key){state.key=state.farmer.api_key;localStorage.setItem('farmerKey',state.key)}
  $('farmerNameLabel').textContent=state.farmer.name;
  await loadFields();
  $('onboard').classList.add('hidden');$('main').classList.remove('hidden');
  switchTab('today');
}

async function loadFields(){
  const r=await api('/api/farmer/fields/');
  state.fields=r.data.fields||[];
  const sel=$('fieldSelect');
  sel.innerHTML=state.fields.length?state.fields.map(f=>`<option value="${f.id}">${esc(f.name)}</option>`).join(''):'<option value="">'+t('no_fields')+'</option>';
  state.fieldId=state.fields[0]?.id||null;
  sel.onchange=()=>{state.fieldId=Number(sel.value)||null;switchTab(currentTab)};
}

/* ---------- Tabs ---------- */
let currentTab='today';
function switchTab(tab){
  if(tab==='more'){tab='manage'}
  currentTab=tab;
  document.querySelectorAll('.ei-nav-item,.ei-bottomnav button').forEach(b=>{
    const on=b.dataset.tab===tab;b.classList.toggle('active',on);
    if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
  });
  const c=$('content');c.setAttribute('aria-busy','true');c.innerHTML=skeleton(3);
  const sectionInfo=getFarmerLang()==='en'?{
    today:['Farm command center','Review today’s priorities, overdue tasks and recorded alerts in one place.'],
    crop:['Crop and growth management','Review the crop and growth stage for each field. Recommendations depend on the information recorded.'],
    irrigation:['Irrigation planning','Review available water-need estimates and suggestions. Missing soil or rainfall data can limit the result.'],
    calendar:['Farm activity calendar','Track planned work and upcoming crop-cycle stages.'],
    risks:['Alerts and risks','Review items that need attention, organized by severity and related field.'],
    agent:['Farm AI assistant','Ask a question in natural language. Before saving an operation, complete the required details and review them.'],
    economics:['Farm economics','Review costs, revenue and estimates based on the values you entered.'],
    manage:['Farm information management','Create or update farms, fields and basic information to improve the usefulness of recommendations.']
  }:{
    today:['مرکز فرماندهی مزرعه','اولویت‌های امروز، کارهای عقب‌افتاده و هشدارهای ثبت‌شده را یک‌جا ببینید.'],
    crop:['مدیریت محصول و چرخه کشت','محصول و مرحله رشد هر قطعه را بررسی کنید؛ پیشنهادها به اطلاعات ثبت‌شده وابسته‌اند.'],
    irrigation:['برنامه‌ریزی آبیاری','نیاز آبی و پیشنهادهای موجود را بررسی کنید. اگر داده خاک یا بارش ناقص باشد، نتیجه محدود خواهد بود.'],
    calendar:['تقویم عملیات مزرعه','کارهای برنامه‌ریزی‌شده و مراحل پیش‌روی کشت را دنبال کنید.'],
    risks:['هشدارها و ریسک‌ها','موارد نیازمند توجه را بر اساس شدت و قطعه مربوطه مرور کنید.'],
    agent:['دستیار هوشمند مزرعه','سؤال خود را به زبان طبیعی مطرح کنید؛ برای ثبت عملیات، جزئیات لازم را تکمیل و پیش از ذخیره بازبینی کنید.'],
    economics:['اقتصاد و هزینه‌های مزرعه','هزینه‌ها، درآمد و برآوردهای اقتصادی را بر اساس مقادیر واردشده بررسی کنید.'],
    manage:['مدیریت اطلاعات مزرعه','زمین‌ها، قطعات و اطلاعات پایه را ثبت یا ویرایش کنید تا پیشنهادها دقیق‌تر شوند.']
  };
  const info=sectionInfo[tab]||sectionInfo.today;
  const render=({today:renderToday,crop:renderCrop,irrigation:renderIrrigation,calendar:renderCalendar,
    risks:renderRisks,agent:renderAgent,economics:renderEconomics,manage:renderManage}[tab]||(()=>{}));
  Promise.resolve(render()).catch(err=>{c.innerHTML=`<div class="empty"><div class="big">⚠️</div><p>${esc(err.message||t('error_generic'))}</p></div>`;})
    .finally(()=>{if(currentTab!==tab)return;c.setAttribute('aria-busy','false');
      const guide=document.createElement('section');guide.className='section-orientation';guide.setAttribute('aria-label',getFarmerLang()==='en'?'Section guide':'راهنمای بخش');
      guide.innerHTML=`<div class="section-orientation-icon">${({today:'☀️',crop:'🌱',irrigation:'💧',calendar:'🗓️',risks:'⚠️',agent:'🤖',economics:'📊',manage:'⚙️'})[tab]||'🌾'}</div><div><h1>${info[0]}</h1><p>${info[1]}</p></div>`;
      c.prepend(guide);
    });
}
document.querySelectorAll('.ei-nav-item,.ei-bottomnav button').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));

/* ---------- Today ---------- */
const PRI={critical:0,high:1,medium:2,low:3};
const PRI_FA={critical:t('pri_critical'),high:t('pri_high'),medium:t('pri_medium'),low:t('pri_low')};
function actionCard(task){
  const pri=task.importance||task.severity||'medium';
  return `<div class="action-card pri-${pri}">
    <div class="action-pri">${PRI_FA[pri]||pri}</div>
    <div class="action-body"><div class="action-title">${esc(task.title_fa||task.title)}</div>
    ${task.why_fa?`<div class="action-why">${t('why_important')} ${esc(task.why_fa)}</div>`:''}
    ${task.timing_fa?`<div class="action-meta">🕐 ${esc(task.timing_fa)}</div>`:''}
    ${task.source?`<div class="action-meta">📊 ${esc(task.source)}</div>`:''}</div>
    ${task.id?`<button class="btn btn-sm btn-ghost" onclick="doneTask(${task.id})">${t('done')}</button>`:''}
  </div>`;
}
async function renderToday(){
  const r=await api('/api/farmer/daily/');
  if(!r.ok){$('content').innerHTML=`<div class="empty"><div class="big">⚠️</div>${esc(r.data.error||t('error_generic'))}</div>`;return}
  const d=r.data;
  // collect all actions across fields, sort by priority
  const actions=[];
  for(const f of d.fields||[])for(const t of f.tasks||[])actions.push({...t,field:f.field_name});
  for(const f of d.fields||[])for(const a of f.alerts||[])actions.push({...a,title_fa:a.title_fa,field:f.field_name});
  for(const t of d.overdue_tasks||[])actions.push({...t,title_fa:t.title,importance:'high',field:t.field_name});
  actions.sort((a,b)=>(PRI[a.importance||a.severity||'medium']??2)-(PRI[b.importance||b.severity||'medium']??2));
  const top=actions[0];
  let h=`<div class="quick-actions">
    <button class="qa" onclick="openOperation('irrigation')">${t('qa_irrigation')}</button>
    <button class="qa" onclick="openOperation('fertilizer')">${t('qa_fertilizer')}</button>
    <button class="qa" onclick="openOperation('observation')">${t('qa_observation')}</button>
    <button class="qa" onclick="switchTab('economics')">${t('qa_cost')}</button>
    <button class="qa" onclick="switchTab('agent')">${t('qa_agent')}</button>
  </div>
  <div class="summary">
    <div class="stat"><div class="num">${d.fields?.length||0}</div><div class="lbl">${t('fields_attention')}</div></div>
    <div class="stat"><div class="num">${d.overdue_tasks?.length||0}</div><div class="lbl">${t('overdue_tasks')}</div></div>
    <div class="stat"><div class="num">${actions.length}</div><div class="lbl">${t('today_actions')}</div></div></div>`;
  const fresh=d.generated_at?`<p class="muted" style="font-size:.72rem;margin:-6px 0 10px">${t('updated_at')} ${esc(d.generated_at.replace('T',' '))}</p>`:'';
  h+=fresh;
  if(top)h+=`<div class="card top-action"><h3><span class="icon">⭐</span>${t('top_today')}</h3>${actionCard(top)}</div>`;
  if(actions.length>1){h+='<div class="card"><h3><span class="icon">📋</span>'+t('other_actions')+'</h3>'+actions.slice(1).map(actionCard).join('')+'</div>'}
  for(const f of d.fields||[]){
    if(!(f.tasks||[]).length&&!(f.alerts||[]).length)continue;
    h+=`<div class="card"><h3><span class="icon">🌾</span>${esc(f.field_name)} <span class="muted" style="font-weight:400;font-size:.8rem">— ${esc(f.farm_name)}</span></h3>`;
    for(const t of f.tasks||[])h+=actionCard(t);
    for(const a of f.alerts||[])h+=actionCard({...a,title_fa:a.title_fa});
    h+='</div>';
  }
  if(!actions.length)h+='<div class="empty"><div class="big">✅</div><p>'+t('no_tasks')+'</p></div>';
  h+='<div id="recSection"><p class="muted" style="font-size:.8rem">'+t('rec_generating')+'</p></div>';
  $('content').innerHTML=h;
  loadRecommendations();
}
async function loadRecommendations(){
  const el=$('recSection');if(!el)return;
  const r=await api('/api/farmer/recommendations/');
  if(!r.ok){el.innerHTML='';return}
  const recs=r.data.recommendations||[];
  if(!recs.length){el.innerHTML='';return}
  const conf=v=>v==null?'—':Math.round(v*100)+'٪';
  let h='<div class="card"><h3><span class="icon">🧠</span>'+t('rec_title')+' <span class="muted" style="font-weight:400;font-size:.75rem">'+t('rec_sub')+'</span></h3>';
  h+=recs.slice(0,5).map(x=>{
    const pri=x.importance==='high'?'high':x.importance==='medium'?'medium':'low';
    return '<div class="item"><div class="dot '+pri+'"></div>'
      +'<div class="body"><div class="title">'+esc(x.title_fa)+'</div>'
      +'<div class="meta">'+t('confidence')+': <b>'+conf(x.confidence)+'</b> · '+t('review_at')+': '+esc(x.review_at||'—')+' · '+esc(x.field_name||'')+(x.expired?' · <span class="badge high">'+t('expired_badge')+'</span>':'')+'</div>'
      +(x.reason_fa?'<div class="meta" style="margin-top:2px">'+esc(x.reason_fa)+'</div>':'')
      +(x.estimated_cost?'<div class="meta muted" style="font-size:.75rem">💰 '+esc(x.estimated_cost)+(x.required_resources&&x.required_resources.length?' · 🧰 '+x.required_resources.map(esc).join('، '):'')+'</div>':'')
      +(x.evidence&&x.evidence.length?'<div class="meta muted" style="font-size:.75rem">'+t('evidence')+': '+x.evidence.slice(0,2).map(esc).join(' · ')+'</div>':'')
      +(x.outcome_note?'<div class="meta muted" style="font-size:.75rem">📈 '+esc(x.outcome_note)+'</div>':'')
      +'</div>'
      +'<div style="display:flex;gap:4px">'
      +'<button class="btn btn-sm btn-ghost" onclick="recFeedback('+x.id+',\'accepted\')" title="'+t('accepted')+'">✓</button>'
      +'<button class="btn btn-sm btn-ghost" onclick="recFeedback('+x.id+',\'rejected\')" title="'+t('rejected')+'">✗</button>'
      +'<button class="btn btn-sm btn-ghost" onclick="recOutcome('+x.id+')" title="'+t('outcome_btn')+'">📈</button>'
      +'</div></div>';
  }).join('')+'</div>';
  el.innerHTML=h;
}
window.recFeedback=async(id,status)=>{
  const r=await post(`/api/farmer/recommendations/${id}/feedback/`,{status});
  if(r.ok){toast(status==='accepted'?t('thanks_feedback'):t('saved'));loadRecommendations()}else toast(t('error_fallback'));
};
window.recOutcome=async(id)=>{
  const o=document.createElement('div');o.className='ei-modal-overlay';
  o.innerHTML=`<div class="ei-modal" style="max-width:430px;text-align:start">
    <h3>${t('outcome_title')}</h3>
    <div style="display:flex;flex-direction:column;gap:10px;margin:12px 0">
      <label class="ei-label">${t('outcome_note_ph')}<textarea id="outNote" class="ei-input" rows="2"></textarea></label>
      <div style="display:flex;gap:8px">
        <label class="ei-label" style="flex:1">${t('outcome_yield_ph')}<input id="outYield" class="ei-input" type="number" step="0.1" min="0"></label>
        <label class="ei-label" style="flex:1">${t('outcome_water_ph')}<input id="outWater" class="ei-input" type="number" step="0.1" min="0"></label>
      </div>
      <div style="display:flex;gap:8px">
        <label class="ei-label" style="flex:1">${t('outcome_cost_ph')}<input id="outCost" class="ei-input" type="number" step="0.1" min="0"></label>
        <label class="ei-label" style="flex:1">${t('outcome_rating_ph')}<input id="outRating" class="ei-input" type="number" min="1" max="5"></label>
      </div>
    </div>
    <div class="row"><button class="btn btn-ghost" id="outNo">${t('cancel_btn')}</button>
      <button class="btn btn-primary" id="outYes" style="width:auto">${t('outcome_save')}</button></div>
  </div>`;
  document.body.appendChild(o);
  o.querySelector('#outNo').onclick=()=>o.remove();
  o.onclick=e=>{if(e.target===o)o.remove()};
  o.querySelector('#outYes').onclick=async()=>{
    const outcome_metrics={};
    const y=Number(o.querySelector('#outYield').value),c=Number(o.querySelector('#outCost').value),
          w=Number(o.querySelector('#outWater').value),rt=Number(o.querySelector('#outRating').value);
    if(y)outcome_metrics.yield_kg_ha=y;
    if(c)outcome_metrics.cost=c;
    if(w)outcome_metrics.water_m3=w;
    if(rt>=1&&rt<=5)outcome_metrics.rating=rt;
    const r=await post(`/api/farmer/recommendations/${id}/feedback/`,{
      status:'completed',outcome_note:o.querySelector('#outNote').value||'',outcome_metrics});
    if(r.ok){toast(t('saved'));o.remove();loadRecommendations()}else toast(t('error_fallback'));
  };
};
window.doneTask=async id=>{await post(`/api/farmer/tasks/${id}/done/`,{});toast(t('saved'));renderToday()};

/* ---------- Quick operations ---------- */
const OP_FIELDS={
  irrigation:[['amount_m3','f_amount_water','number'],['duration_min','f_duration','number'],['method','f_method','text']],
  fertilizer:[['kind','f_kind','text'],['amount_kg','f_amount_kg','number']],
  observation:[['note','f_note','text']],
};
const OP_TITLE={irrigation:'op_irrigation',fertilizer:'op_fertilizer',observation:'op_observation'};
window.openOperation=type=>{
  const fields=state.fields;if(!fields.length){toast(t('register_field_first'));return}
  const o=document.createElement('div');o.className='ei-modal-overlay';
  const inputs=(OP_FIELDS[type]||[]).map(([k,key,ty])=>`<label class="ei-label" style="text-align:start">${t(key)}<input class="ei-input" data-k="${k}" type="${ty==='number'?'number':'text'}"></label>`).join('');
  o.innerHTML=`<div class="ei-modal" style="max-width:400px;text-align:start">
    <h3>${t(OP_TITLE[type]||'op_title')}</h3>
    <div style="display:flex;flex-direction:column;gap:10px;margin:12px 0">
      <label class="ei-label">${t('op_field')}<select class="ei-select" id="opField">${fields.map(f=>`<option value="${f.id}">${esc(f.name)}</option>`).join('')}</select></label>
      ${inputs}
      <label class="ei-label">${t('op_notes')}<input class="ei-input" id="opNotes" type="text"></label>
    </div>
    <div class="row" style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn btn-ghost" id="opNo">${t('cancel_btn')}</button>
      <button class="btn btn-primary" id="opYes" style="width:auto">${t('register')}</button>
    </div></div>`;
  document.body.appendChild(o);
  o.querySelector('#opNo').onclick=()=>o.remove();
  o.onclick=e=>{if(e.target===o)o.remove()};
  o.querySelector('#opYes').onclick=async()=>{
    const body={type,field_id:Number(o.querySelector('#opField').value),notes:o.querySelector('#opNotes').value};
    o.querySelectorAll('input[data-k]').forEach(i=>{const v=i.value;if(v!=='')body[i.dataset.k]=i.type==='number'?Number(v):v});
    const r=await post('/api/farmer/operations/',body);
    o.remove();
    if(r.ok){toast(t('saved'));if(currentTab==='today')renderToday()}else toast(r.data.error||t('error_fallback'));
  };
};

/* ---------- Simple/Expert mode ---------- */
function applyMode(){
  const m=localStorage.getItem('farmerMode')||'simple';
  document.body.classList.toggle('mode-simple',m==='simple');
  const b=$('modeBtn');if(b)b.textContent=m==='simple'?t('mode_expert'):t('mode_simple');
}
window.toggleMode=()=>{
  const m=document.body.classList.contains('mode-simple')?'expert':'simple';
  localStorage.setItem('farmerMode',m);applyMode();
};
applyMode();

/* ---------- Offline awareness ---------- */
function updateOnline(){
  const b=$('offlineBanner');if(!b)return;
  b.classList.toggle('hidden',navigator.onLine);
}
window.addEventListener('online',updateOnline);window.addEventListener('offline',updateOnline);

/* ---------- Crop (recommend + lifecycle) ---------- */
async function renderCrop(){
  if(!state.fieldId){$('content').innerHTML='<div class="empty"><div class="big">🌱</div><p>'+t('need_field_first')+'</p></div>';return}
  const [rec,cal]=await Promise.all([
    api('/api/farmer/recommend/?field_id='+state.fieldId),
    api('/api/farmer/calendar/?field_id='+state.fieldId)]);
  let h='';
  if(rec.ok&&rec.data.ranking&&rec.data.ranking.length){
    const suit=s=>s>=75?[t('suit_vhigh'),'success']:s>=55?[t('suit_high'),'info']:s>=35?[t('suit_mid'),'warning']:[t('suit_low'),'danger'];
    h+='<div class="card"><h3><span class="icon">🏆</span>'+t('crop_title')+'</h3><div class="crop-grid">';
    for(const r of rec.data.ranking.slice(0,6)){
      const [lbl,cls]=suit(r.score);
      h+='<div class="crop-card"><div class="crop-head"><b>'+esc(r.name_fa)+'</b><span class="badge badge-'+cls+'">'+lbl+'</span></div>'
        +'<div class="crop-score"><div class="ei-progress"><div style="width:'+r.score+'%"></div></div><span>'+r.score+'</span></div>'
        +'<div class="crop-meta">💧 '+(r.water_need_mm||'—')+'mm · 🌡️ '+(r.growth_days||'—')+' '+t('day_unit')+'</div>'
        +(r.reasons_fa&&r.reasons_fa.length?'<details class="crop-why"><summary>'+t('crop_why')+'</summary><ul>'+r.reasons_fa.slice(0,4).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></details>':'')
      +'</div>';
    }
    h+='</div><p class="muted" style="font-size:.78rem;margin-top:8px">'+esc((rec.data.limitations||[])[0]||'')+'</p></div>';
  }
  if(cal.ok&&cal.data.current_stage){
    const d=cal.data,pct=Math.round((d.progress||0)*100);
    h+='<div class="card"><h3><span class="icon">📅</span>'+t('crop_status')+' '+esc(d.crop_name_fa||'')+'</h3>'
      +'<div style="display:flex;justify-content:space-between;font-size:.9rem"><span>'+esc(d.current_stage.name_fa)+'</span><b>'+pct+'٪</b></div>'
      +'<div class="progress"><div style="width:'+pct+'%"></div></div>'
      +'<div class="meta muted tech" style="font-size:.82rem">'+t('gdd')+': '+(d.gdd_accumulated||'—')+'/'+(d.gdd_required||'—')+' · '+t('harvest_est')+': '+esc(d.estimated_harvest||'—')+'</div>'
      +'<p style="margin-top:8px;font-size:.88rem">'+esc(d.current_stage.tasks_fa||'')+'</p></div>';
  }
  if(!h)h='<div class="empty"><div class="big">🌱</div><p>'+t('no_crop_data')+'</p></div>';
  $('content').innerHTML=h;
}

/* ---------- Irrigation ---------- */
async function renderIrrigation(){
  if(!state.fieldId){$('content').innerHTML='<div class="empty"><div class="big">💧</div><p>'+t('select_field')+'</p></div>';return}
  const r=await api('/api/farmer/irrigation/?field_id='+state.fieldId);
  if(!r.ok){$('content').innerHTML='<div class="empty">'+esc(r.data.error||t('error_generic'))+'</div>';return}
  const d=r.data;
  $('content').innerHTML='<div class="card"><h3><span class="icon">💧</span>'+t('irr_title')+' — '+esc(d.crop_name_fa||'')+'</h3>'
    +'<div class="summary" style="grid-template-columns:repeat(3,1fr)">'
    +'<div class="stat"><div class="num">'+(d.pet_mm??'—')+'</div><div class="lbl">'+t('pet')+'</div></div>'
    +'<div class="stat"><div class="num">'+(d.etc_mm??'—')+'</div><div class="lbl">'+t('etc')+'</div></div>'
    +'<div class="stat"><div class="num">'+(d.net_need_mm??'—')+'</div><div class="lbl">'+t('net_need')+'</div></div></div>'
    +'<div class="item"><div class="dot '+(d.importance==='high'?'high':'medium')+'"></div><div class="body"><div class="title">'+esc(d.advice_fa||'')+'</div><div class="meta">'+t('stage')+': '+esc(d.growth_stage||'—')+' · Kc='+(d.kc_used??'—')+'</div></div></div>'
    +'<h3 style="margin-top:14px">'+t('limitations')+'</h3>'+(d.limitations_fa||[]).map(l=>'<div class="item"><div class="dot low"></div><div class="body"><div class="title" style="font-weight:400;font-size:.85rem">'+esc(l)+'</div></div></div>').join('')+'</div>';
}

/* ---------- Calendar ---------- */
async function renderCalendar(){
  if(!state.fieldId){$('content').innerHTML='<div class="empty"><div class="big">📅</div><p>'+t('select_field')+'</p></div>';return}
  const r=await api('/api/farmer/calendar/?field_id='+state.fieldId);
  if(!r.ok){$('content').innerHTML='<div class="empty">'+esc(r.data.error||t('no_cycle'))+'</div>';return}
  const d=r.data;
  const stages=(d.stages||[]).map(s=>{
    const p=d.progress||0;const active=p>=s.from&&p<s.to;
    return '<div class="item"><div class="dot '+(active?'high':'low')+'"></div><div class="body"><div class="title" style="'+(active?'font-weight:800':'')+'">'+esc(s.name_fa)+' '+(active?'◀':'')+'</div><div class="meta">'+Math.round(s.from*100)+'٪–'+Math.round(s.to*100)+'٪ '+t('of_cycle')+'</div></div></div>';
  }).join('');
  $('content').innerHTML='<div class="card"><h3><span class="icon">📅</span>'+t('cal_title')+' '+esc(d.crop_name_fa||'')+'</h3>'
    +'<div class="summary"><div class="stat"><div class="num">'+(d.days_since_planting??'—')+'</div><div class="lbl">'+t('days_since')+'</div></div>'
    +'<div class="stat"><div class="num">'+(d.days_to_harvest??'—')+'</div><div class="lbl">'+t('days_to')+'</div></div>'
    +'<div class="stat"><div class="num">'+(d.method==='gdd'?'GDD':t('method'))+'</div><div class="lbl">'+t('method')+'</div></div></div>'
    +'<h3>'+t('growth_stages')+'</h3>'+stages+'</div>';
}

/* ---------- Risks ---------- */
async function renderRisks(){
  const r=await api('/api/farmer/risks/');
  if(!r.ok){$('content').innerHTML=`<div class="empty">${esc(r.data.error||t('error_generic'))}</div>`;return}
  let h='';
  for(const f of r.data.fields||[]){
    h+=`<div class="card"><h3><span class="icon">⚠️</span>${esc(f.field_name)}</h3>`;
    for(const rk of f.risks)h+=`<div class="item"><div class="dot ${rk.severity==='critical'||rk.severity==='high'?'high':rk.severity==='medium'?'medium':'low'}"></div><div class="body"><div class="title">${esc(rk.title_fa)}</div><div class="meta"><span class="badge ${rk.severity}">${rk.severity==='critical'?t('sev_critical'):rk.severity==='high'?t('sev_high'):rk.severity==='medium'?t('sev_medium'):t('sev_low')}</span> ${esc(rk.action_fa||'')} · ${esc(rk.source||'')}</div></div></div>`;
    h+='</div>';
  }
  if(!h)h='<div class="empty"><div class="big">✅</div><p>'+t('no_risk_significant')+'</p></div>';
  $('content').innerHTML=h+'<div id="alertsSection"></div>';
  loadAlerts();
}
async function loadAlerts(){
  const el=$('alertsSection');if(!el)return;
  const qp=[];
  if(window._alertSev)qp.push('severity='+window._alertSev);
  if(window._alertFarmId)qp.push('farm_id='+window._alertFarmId);
  const r=await api('/api/farmer/alerts/'+(qp.length?'?'+qp.join('&'):''));
  if(!r.ok){el.innerHTML='';return}
  const alerts=r.data.alerts||[];
  const counts=r.data.status_counts||{};
  const STATUS_FA={new:t('st_new'),active:t('st_active'),acknowledged:t('st_acknowledged'),snoozed:t('st_snoozed'),resolved:t('st_resolved'),expired:t('st_expired')};
  const SEV_FA={critical:t('sev_critical'),high:t('sev_high'),medium:t('sev_medium'),low:t('sev_low')};
  const sevBadge=s=>'<span class="badge '+s+'">'+(SEV_FA[s]||s)+'</span>';
  const statusBadge=s=>'<span class="badge info" style="font-size:.7rem">'+(STATUS_FA[s]||s)+'</span>';
  const farms=[...new Set(alerts.map(a=>a.farm_name).filter(Boolean))];
  let h='<div class="card"><h3><span class="icon">🔔</span>'+t('alerts_title')+' <span class="badge info">'+r.data.unread+' '+t('unread')+'</span></h3>';
  h+='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;align-items:center">'
    +'<select class="ei-select" style="width:auto;padding:4px 8px;font-size:.8rem" onchange="filterAlertsByFarm(this.value)">'
    +'<option value="">'+t('farm')+': '+t('all')+'</option>'
    +farms.map(f=>'<option value="'+esc(f)+'"'+(window._alertFarm===f?' selected':'')+'>'+esc(f)+'</option>').join('')+'</select>'
    +'<select class="ei-select" style="width:auto;padding:4px 8px;font-size:.8rem" onchange="filterAlertsBySev(this.value)">'
    +'<option value="">'+t('severity')+': '+t('all')+'</option>'
    +['critical','high','medium','low'].map(s=>'<option value="'+s+'"'+(window._alertSev===s?' selected':'')+'>'+SEV_FA[s]+'</option>').join('')+'</select>'
    +'<span style="font-size:.75rem;color:var(--ei-muted)">|</span>'
    +'<div style="display:flex;gap:4px;flex-wrap:wrap">'
    +Object.entries(counts).filter(([k,v])=>v>0).map(([k,v])=>
      '<button class="btn btn-sm btn-ghost" onclick="filterAlerts(\''+k+'\')">'+(STATUS_FA[k]||k)+' ('+v+')</button>').join('')+'</div></div>';
  if(!alerts.length){h+='<p class="muted" style="font-size:.85rem">'+t('no_alerts')+'</p></div>';el.innerHTML=h;return}
  h+=alerts.map(a=>'<div class="item" style="'+(a.is_read?'opacity:.65':'')+'">'
    +'<div class="dot '+(a.severity==='critical'||a.severity==='high'?'high':'medium')+'"></div>'
    +'<div class="body"><div class="title">'+esc(a.title_fa)+' '+statusBadge(a.status)+'</div>'
    +'<div class="meta">'+sevBadge(a.severity)+' '+esc(a.field_name||'')+' · '+esc(a.farm_name||'')+' · '+esc(a.source||'')+' · '+esc((a.created_at||'').slice(0,10))+'</div>'
    +(a.evidence&&a.evidence.length?'<div class="meta muted" style="font-size:.75rem">'+t('evidence')+': '+a.evidence.map(e=>esc(e.kind||'')).join('، ')+'</div>':'')
    +'</div>'
    +'<div style="display:flex;gap:4px;flex-wrap:wrap">'
    +(['new','active'].includes(a.status)?'<button class="btn btn-sm btn-ghost" onclick="alertAction('+a.id+',\'acknowledge\')">✓ '+t('seen')+'</button>':'')
    +(['new','active','acknowledged'].includes(a.status)?'<button class="btn btn-sm btn-ghost" onclick="alertAction('+a.id+',\'snooze\')">⏰</button>':'')
    +(a.status!=='resolved'?'<button class="btn btn-sm btn-ghost" onclick="alertAction('+a.id+',\'resolve\')">✔ '+t('resolved_btn')+'</button>':'')
    +'<button class="btn btn-sm btn-ghost" onclick="alertAction('+a.id+',\'dismiss\')">×</button>'
    +'</div></div>').join('')+'</div>';
  el.innerHTML=h;
}
window.filterAlerts=status=>{
  window._alertStatus=status;
  api('/api/farmer/alerts/?status='+status).then(r=>{
    if(!r.ok)return;
    const el=$('alertsSection');if(!el)return;
    const STATUS_FA={new:t('st_new'),active:t('st_active'),acknowledged:t('st_acknowledged'),snoozed:t('st_snoozed'),resolved:t('st_resolved'),expired:t('st_expired')};
    el.innerHTML='<div class="card"><h3><span class="icon">🔔</span>'+(STATUS_FA[status]||status)+'</h3>'
      +(r.data.alerts||[]).map(a=>'<div class="item"><div class="dot '+(a.severity==='critical'||a.severity==='high'?'high':'medium')+'"></div>'
      +'<div class="body"><div class="title">'+esc(a.title_fa)+'</div>'
      +'<div class="meta">'+esc(a.field_name||'')+' · '+esc(a.source||'')+'</div></div></div>').join('')+'</div>';
  });
};
window.filterAlertsByFarm=f=>{window._alertFarm=f||null;loadAlerts()};
window.filterAlertsBySev=s=>{window._alertSev=s||null;loadAlerts()};
window.alertAction=async(id,action)=>{
  const r=await post('/api/farmer/alerts/'+id+'/action/',{action});
  if(r.ok){toast(t('saved'));loadAlerts()}else toast(t('error_fallback'));
};

/* ---------- Agent ---------- */
function renderAgent(){
  $('content').innerHTML='<div class="card"><h3><span class="icon">🤖</span>'+t('agent_title')+'</h3>'
    +'<div class="chat" id="chat"></div>'
    +'<div class="chat-input"><input id="chatIn" placeholder="'+t('agent_placeholder_full')+'" onkeydown="if(event.key===\'Enter\')sendChat()"><button id="micBtn" onclick="toggleMic()" title="'+t('agent_title')+'">🎤</button><button onclick="sendChat()">➤</button></div>'
    +'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">'
    +'<button class="qa" onclick="askQuick(\''+t('agent_q1')+'\')">'+t('agent_q1')+'</button>'
    +'<button class="qa" onclick="askQuick(\''+t('agent_q2')+'\')">'+t('agent_q2')+'</button>'
    +'<button class="qa" onclick="askQuick(\''+t('agent_q3')+'\')">'+t('agent_q3')+'</button>'
    +'<button class="qa" onclick="askQuick(\''+t('agent_q4')+'\')">'+t('agent_q4')+'</button>'
    +'<button class="qa" onclick="askQuick(\''+t('agent_q5')+'\')">'+t('agent_q5')+'</button>'
    +'</div></div>';
  addMsg('bot',t('agent_greeting'));
}
window.askQuick=q=>{$('chatIn').value=q;sendChat()};
let recog=null;
window.toggleMic=()=>{
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){toast(t('mic_unsupported'));return}
  if(recog){recog.stop();recog=null;$('micBtn').textContent='🎤';return}
  recog=new SR();recog.lang=getFarmerLang()==='en'?'en-US':'fa-IR';recog.interimResults=false;
  $('micBtn').textContent='⏺️';
  recog.onresult=e=>{$('chatIn').value=e.results[0][0].transcript;sendChat()};
  recog.onend=()=>{$('micBtn').textContent='🎤';recog=null};
  recog.onerror=()=>{$('micBtn').textContent='🎤';recog=null;toast(t('mic_error'))};
  recog.start();
};
function addMsg(who,text){const c=$('chat');if(!c)return;const d=document.createElement('div');d.className='msg '+who;d.innerHTML=esc(text).replace(/\n/g,'<br>');c.appendChild(d);c.parentElement.scrollTop=1e6}
function renderAgentConfirm(d){
  const c=$('chat');if(!c)return;
  const m=document.createElement('div');m.className='msg bot';
  m.innerHTML=esc(d.message_fa||d.answer_fa||'')+'<div style="margin-top:8px;display:flex;gap:8px">'
    +'<button class="btn btn-primary" style="width:auto">'+t('confirm_btn')+'</button>'
    +'<button class="btn btn-ghost" style="width:auto">'+t('cancel_btn')+'</button></div>';
  c.appendChild(m);c.parentElement.scrollTop=1e6;
  const btns=m.querySelectorAll('button'),yes=btns[0],no=btns[1];
  no.onclick=()=>m.remove();
  yes.onclick=async()=>{yes.disabled=no.disabled=true;
    const rr=await post('/api/farmer/agent/tool/',{tool:d.tool,params:d.params,confirm:true,field_id:(d.params&&d.params.field_id)||state.fieldId||null});
    m.innerHTML=esc(rr.ok?t('agent_confirmed'):(rr.data.error||t('agent_error')));
  };
}
window.sendChat=async()=>{
  const inp=$('chatIn'),q=inp.value.trim();if(!q)return;inp.value='';addMsg('user',q);addMsg('bot','…');
  const mode=localStorage.getItem('farmerMode')||'simple';
  const r=await post('/api/farmer/agent/',{question:q,field_id:state.fieldId||null,mode});
  const msgs=document.querySelectorAll('#chat .msg');msgs[msgs.length-1].remove();
  if(!r.ok){addMsg('bot',t('agent_error'));return}
  const d=r.data;
  if(d.confirmation_required){renderAgentConfirm(d);return}
  let text=d.answer_fa||'—';
  if(mode==='expert'&&d.expert){
    const s=(d.expert.sources||[]).join('، '),l=(d.expert.limitations||[]).join('؛ ');
    if(s)text+='\n'+t('agent_sources')+': '+s;
    if(l)text+='\n'+t('agent_limits')+': '+l;
  }
  addMsg('bot',text);
};

/* ---------- Economics ---------- */
async function renderEconomics(){
  const farms=await api('/api/farmer/farms/');
  $('content').innerHTML='<div class="card"><h3><span class="icon">💰</span>'+t('econ_title')+'</h3>'
    +'<div class="form-grid">'
    +'<label class="full">'+t('farm')+'<select id="econFarm">'+(farms.data.farms||[]).map(f=>'<option value="'+f.id+'">'+esc(f.name)+'</option>').join('')+'</select></label>'
    +'<label>'+t('yield_kg')+'<input id="econYield" type="number" placeholder="4000"></label>'
    +'<label>'+t('price')+'<input id="econPrice" type="number" placeholder="'+t('price')+'"></label>'
    +'<label class="full"><button class="btn btn-primary" onclick="loadEcon()">'+t('calculate')+'</button></label>'
    +'</div><div id="econResult"></div></div>'
    +'<div class="card"><h3><span class="icon">🧾</span>'+t('add_expense')+'</h3>'
    +'<div class="form-grid">'
    +'<label>'+t('expense_cat')+'<select id="expCat">'
    +['seed','land','water','fertilizer','pesticide','labor','harvest','transport','other'].map(k=>'<option value="'+k+'">'+t('exp_'+k)+'</option>').join('')
    +'</select></label>'
    +'<label>'+t('amount')+'<input id="expAmt" type="number"></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="addExpense()">'+t('register_expense')+'</button></label>'
    +'</div></div>';
}
window.loadEcon=async()=>{
  const f=$('econFarm').value,y=$('econYield').value,p=$('econPrice').value;
  const r=await api(`/api/farmer/economics/?farm_id=${f}${y?`&yield_kg_ha=${y}`:''}${p?`&price=${p}`:''}`);
  if(!r.ok){$('econResult').innerHTML=`<p class="error">${esc(r.data.error||t('error_generic'))}</p>`;return}
  const d=r.data;
  $('econResult').innerHTML=`<div class="summary" style="margin-top:14px">
    <div class="stat"><div class="num">${(d.total_cost||0).toLocaleString()}</div><div class="lbl">${t('total_cost')}</div></div>
    <div class="stat"><div class="num">${d.cost_per_ha?(d.cost_per_ha).toLocaleString():'—'}</div><div class="lbl">${t('cost_per_ha')}</div></div>
    ${d.profit!==undefined?`<div class="stat"><div class="num" style="color:${d.profit>=0?'var(--ok)':'var(--danger)'}">${d.profit.toLocaleString()}</div><div class="lbl">${t('profit')}</div></div>`:''}
    ${d.margin_pct!==undefined?`<div class="stat"><div class="num">${d.margin_pct}٪</div><div class="lbl">${t('margin')}</div></div>`:''}</div>
    ${d.break_even_yield_kg_ha?`<p class="muted" style="font-size:.85rem">${t('break_even')}: ${d.break_even_yield_kg_ha} kg/ha</p>`:''}`;
};
window.addExpense=async()=>{
  const f=$('econFarm').value,a=$('expAmt').value;if(!a){toast(t('enter_amount'));return}
  const r=await post('/api/farmer/expenses/create/',{farm_id:Number(f),category:$('expCat').value,amount:Number(a)});
  if(r.ok){toast(t('expense_saved'));loadEcon()}else toast(r.data.error||t('error_fallback'));
};

/* ---------- Manage ---------- */
async function renderManage(){
  if(!state.farms)state.farms=(await api('/api/farmer/farms/')).data.farms||[];
  if(!state.crops)state.crops=(await api('/api/farmer/crops/')).data.crops||[];
  const farms={data:{farms:state.farms}},crops={data:{crops:state.crops}};
  const fields={data:{fields:state.fields}};
  $('content').innerHTML=
  '<div class="card"><h3><span class="icon">🏡</span>'+t('manage_title')+'</h3>'
    +'<p class="muted" style="font-size:.85rem;margin-bottom:10px">'+(farms.data.farms||[]).length+' '+t('farms_count')+' · '+(fields.data.fields||[]).length+' '+t('fields_count')+'</p>'
    +'<div class="form-grid">'
    +'<label>'+t('new_farm_name')+'<input id="newFarmName"></label>'
    +'<label>'+t('province')+'<input id="newFarmProv"></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="addFarm()">+ '+t('add_farm')+'</button></label>'
    +'</div></div>'
  +'<div class="card"><h3><span class="icon">🗺️</span>'+t('new_field')+'</h3>'
    +'<div class="form-grid">'
    +'<label>'+t('farm')+'<select id="newFieldFarm">'+(farms.data.farms||[]).map(f=>'<option value="'+f.id+'">'+esc(f.name)+'</option>').join('')+'</select></label>'
    +'<label>'+t('field_name')+'<input id="newFieldName"></label>'
    +'<label>'+t('lat')+'<input id="newFieldLat" type="number" step="0.0001"></label>'
    +'<label>'+t('lon')+'<input id="newFieldLon" type="number" step="0.0001"></label>'
    +'<label>'+t('area_ha')+'<input id="newFieldArea" type="number" step="0.1"></label>'
    +'<label class="full">'+t('soil')+'<select id="newFieldSoil"><option value="">—</option>'
    +['clay','loam','sandy','silty','saline'].map(k=>'<option value="'+k+'">'+t('soil_'+k)+'</option>').join('')+'</select></label>'
    +'<label>'+t('current_crop')+'<select id="newFieldCrop"><option value="">—</option>'+(crops.data.crops||[]).map(c=>'<option value="'+c.key+'">'+esc(getFarmerLang()==='en'?(c.name_en||c.name_fa):c.name_fa)+'</option>').join('')+'</select></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="addField()">+ '+t('add_field')+'</button></label>'
    +'</div>'
    +'<div id="fieldMap" style="height:220px;border-radius:12px;margin-top:12px;border:1px solid var(--ei-border)"></div>'
    +'<p class="muted" style="font-size:.78rem;margin-top:6px">🗺️ '+t('map_hint')+'</p></div>'
  +'<div class="card"><h3><span class="icon">🌾</span>'+t('register_cycle')+'</h3>'
    +'<div class="form-grid">'
    +'<label>'+t('cycle_field')+'<select id="cycleField">'+state.fields.map(f=>'<option value="'+f.id+'">'+esc(f.name)+'</option>').join('')+'</select></label>'
    +'<label>'+t('cycle_crop')+'<select id="cycleCrop">'+(crops.data.crops||[]).map(c=>'<option value="'+c.key+'">'+esc(getFarmerLang()==='en'?(c.name_en||c.name_fa):c.name_fa)+'</option>').join('')+'</select></label>'
    +'<label>'+t('planting_date')+'<input id="cycleDate" type="date"></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="addCycle()">+ '+t('add_cycle')+'</button></label>'
    +'</div></div>'
  +'<div class="card"><h3><span class="icon">✅</span>'+t('my_tasks')+'</h3><div id="taskList"></div>'
    +'<div class="form-grid" style="margin-top:10px">'
    +'<label>'+t('new_task')+'<input id="newTaskTitle"></label>'
    +'<label>'+t('due')+'<input id="newTaskDue" type="date"></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="addTask()">+ '+t('add_task')+'</button></label>'
    +'</div></div>'
  +'<div class="card"><h3><span class="icon">🧪</span>'+t('soil_water_title')+'</h3>'
    +'<div class="form-grid">'
    +'<label>'+t('cycle_field')+'<select id="soilField">'+state.fields.map(f=>'<option value="'+f.id+'">'+esc(f.name)+'</option>').join('')+'</select></label>'
    +'<label>'+t('ph')+'<input id="soilPh" type="number" step="0.1"></label>'
    +'<label>'+t('organic_matter')+'<input id="soilOm" type="number" step="0.1"></label>'
    +'<label>'+t('field_capacity')+'<input id="soilFc" type="number" step="0.1"></label>'
    +'<label>'+t('wilting_point')+'<input id="soilPwp" type="number" step="0.1"></label>'
    +'<label>'+t('root_depth')+'<input id="soilRoot" type="number" step="1"></label>'
    +'<label class="full">'+t('soil_notes')+'<input id="soilNotes" type="text"></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="saveSoil()">'+t('save_soil')+'</button></label>'
    +'</div>'
    +'<h3 style="margin-top:14px">'+t('water_section')+'</h3>'
    +'<div class="form-grid">'
    +'<label>'+t('farm')+'<select id="wsFarm">'+(farms.data.farms||[]).map(f=>'<option value="'+f.id+'">'+esc(f.name)+'</option>').join('')+'</select></label>'
    +'<label>'+t('water_name')+'<input id="wsName" type="text"></label>'
    +'<label>'+t('water_kind')+'<select id="wsKind"><option value="">—</option>'
    +['well','qanat','river','dam','other'].map(k=>'<option value="'+k+'">'+t('ws_'+k)+'</option>').join('')+'</select></label>'
    +'<label>'+t('water_capacity')+'<input id="wsCap" type="number" step="0.1"></label>'
    +'<label class="full"><button class="btn btn-ghost" onclick="saveWaterSource()">'+t('add_water')+'</button></label>'
    +'</div></div>';
  loadTasks();
  initFieldMap();
}
window.saveSoil=async()=>{
  const fid=$('soilField').value;if(!fid)return;
  const body={ph:$('soilPh').value||null,organic_matter:$('soilOm').value||null,
    field_capacity:$('soilFc').value||null,wilting_point:$('soilPwp').value||null,
    root_depth_cm:$('soilRoot').value||null,notes:$('soilNotes').value};
  const r=await post('/api/farmer/fields/'+fid+'/soil/',body);
  toast(r.ok?t('soil_saved'):t('error_fallback'));
};
window.saveWaterSource=async()=>{
  const fid=$('wsFarm').value,n=$('wsName').value.trim();if(!n){toast(t('water_name'));return}
  const r=await post('/api/farmer/farms/'+fid+'/water-sources/',{name:n,kind:$('wsKind').value,capacity_m3:$('wsCap').value||null});
  toast(r.ok?t('water_saved'):t('error_fallback'));
};
let fieldMap=null,fieldMarker=null,leafletLoading=null;
function loadLeaflet(){
  if(window.L)return Promise.resolve();
  if(leafletLoading)return leafletLoading;
  leafletLoading=new Promise((res,rej)=>{
    const s=document.createElement('script');
    s.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    s.onload=res;s.onerror=rej;document.head.appendChild(s);
  });
  return leafletLoading;
}
async function initFieldMap(){
  const el=$('fieldMap');if(!el)return;
  try{await loadLeaflet()}catch(e){el.innerHTML='<p class="muted" style="padding:12px">'+t('map_fail')+'</p>';return}
  if(fieldMap){fieldMap.remove();fieldMap=null}
  const f=state.fields.find(x=>x.id===state.fieldId);
  const lat=f?.lat||32.4,lon=f?.lon||53.7;
  fieldMap=L.map(el).setView([lat,lon],f?12:4);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(fieldMap);
  if(f&&f.lat&&f.lon){fieldMarker=L.marker([f.lat,f.lon]).addTo(fieldMap).bindPopup(esc(f.name))}
  fieldMap.on('click',e=>{
    const la=e.latlng.lat.toFixed(4),lo=e.latlng.lng.toFixed(4);
    $('newFieldLat').value=la;$('newFieldLon').value=lo;
    if(fieldMarker)fieldMarker.setLatLng(e.latlng);else fieldMarker=L.marker(e.latlng).addTo(fieldMap);
    toast(t('coords')+': '+la+', '+lo);
  });
  setTimeout(()=>fieldMap.invalidateSize(),100);
}
window.addFarm=async()=>{const n=$('newFarmName').value.trim();if(!n)return;const r=await post('/api/farmer/farms/create/',{name:n,province:$('newFarmProv').value});if(r.ok){toast(t('farm_saved'));state.farms=null;await loadFields();renderManage()}else toast(r.data.error)};
window.addField=async()=>{const n=$('newFieldName').value.trim();if(!n)return;const r=await post('/api/farmer/fields/create/',{farm_id:Number($('newFieldFarm').value),name:n,lat:$('newFieldLat').value||null,lon:$('newFieldLon').value||null,area_ha:$('newFieldArea').value||null,soil_type:$('newFieldSoil').value,current_crop:$('newFieldCrop').value||null});if(r.ok){toast(t('field_saved'));state.farms=null;await loadFields();renderManage()}else toast(r.data.error)};
window.addCycle=async()=>{const r=await post('/api/farmer/cycles/create/',{field_id:Number($('cycleField').value),crop:$('cycleCrop').value,planting_date:$('cycleDate').value});if(r.ok){toast(t('cycle_saved'))}else toast(r.data.error||t('error_fallback'))};
window.addTask=async()=>{const t=$('newTaskTitle').value.trim();if(!t)return;const r=await post('/api/farmer/tasks/create/',{title:t,due_date:$('newTaskDue').value||null});if(r.ok){toast(t('task_saved'));loadTasks()}else toast(r.data.error)};
async function loadTasks(){
  const r=await api('/api/farmer/tasks/');const el=$('taskList');if(!el)return;
  el.innerHTML=(r.data.tasks||[]).map(t=>`<div class="item"><div class="dot ${t.done?'low':'medium'}"></div><div class="body"><div class="title" style="${t.done?'text-decoration:line-through;opacity:.6':''}">${esc(t.title)}</div><div class="meta">${t.field_name?esc(t.field_name)+' · ':''}${t.due_date||''}</div></div>${t.done?'':`<button class="btn btn-sm btn-ghost" onclick="doneTask(${t.id})">${t('done')}</button>`}</div>`).join('')||'<p class="muted">'+t('no_tasks_yet')+'</p>';
}

updateOnline();
boot();
