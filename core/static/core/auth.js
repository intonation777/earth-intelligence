(() => {
  const dict = {
    fa: { title_login:'ورود به حساب', title_register:'ساخت حساب', sub:'برای استفاده از بخش علمی وارد شوید یا حساب بسازید.',
      login:'ورود', register:'ثبت‌نام', key:'کلید API', name:'نام و نام خانوادگی', id:'ایمیل یا شماره موبایل',
      pass:'رمز عبور', phone:'شماره تماس (اختیاری)', submit_login:'ورود', submit_register:'ساخت حساب',
      submit_key:'ورود با کلید', key_ph:'api_key', required:'شناسه و رمز را وارد کنید', key_required:'کلید API را وارد کنید',
      pass_hint:'رمز حداقل ۸ کاراکتر.', key_hint:'فقط برای کاربران legacy.', err:'خطا' },
    en: { title_login:'Sign in', title_register:'Create account', sub:'Sign in or create an account to use the scientific workspace.',
      login:'Login', register:'Register', key:'API key', name:'Full name', id:'Email or mobile', pass:'Password',
      phone:'Contact phone (optional)', submit_login:'Sign in', submit_register:'Create account', submit_key:'Login with key',
      key_ph:'api_key', required:'Enter identifier and password', key_required:'Enter API key', pass_hint:'Password must be at least 8 characters.',
      key_hint:'Legacy users only.', err:'Error' }
  };
  let lang = localStorage.getItem('landing_lang') || 'fa';
  const $ = id => document.getElementById(id);
  const t = k => (dict[lang] && dict[lang][k]) || dict.fa[k] || k;
  function apply(){ document.documentElement.lang=lang; document.documentElement.dir=lang==='fa'?'rtl':'ltr';
    document.title = lang==='fa' ? 'ورود | Earth Intelligence' : 'Sign in | Earth Intelligence';
    const hl=$('homeLink'); if(hl) hl.textContent = lang==='fa' ? '← خانه' : '← Home';
    $('title').textContent=t(lang==='fa'?'title_login':'title_login'); $('sub').textContent=t('sub');
    $('tabLogin').textContent=t('login'); $('tabRegister').textContent=t('register'); $('tabKey').textContent=t('key');
    $('langBtn').textContent=lang==='fa'?'EN':'فا'; $('authHint').textContent=mode==='key'?t('key_hint'):t('pass_hint'); render(mode); }
  let mode='login';
  function render(m){ mode=m; ['tabLogin','tabRegister','tabKey'].forEach(id=>$(id).classList.toggle('on', $(id).dataset.m===m));
    const isKey=m==='key', isReg=m==='register';
    $('authBox').innerHTML = isKey
      ? `<input id="fKey" placeholder="${t('key_ph')}" autocomplete="off"><button class="btn" id="go">${t('submit_key')}</button>`
      : `${isReg?`<input id="fName" placeholder="${t('name')}" autocomplete="name">`:''}
         <input id="fLogin" placeholder="${t('id')}" autocomplete="username">
         <input id="fPass" type="password" placeholder="${t('pass')}" autocomplete="${m==='login'?'current-password':'new-password'}">
         ${isReg?`<input id="fPhone" placeholder="${t('phone')}" autocomplete="tel">`:''}
         <button class="btn" id="go">${isReg?t('submit_register'):t('submit_login')}</button>`;
    $('go').onclick=submit; }
  async function submit(){ const err=$('authErr'); err.textContent='';
    if(mode==='key'){ const key=$('fKey').value.trim(); if(!key){err.textContent=t('key_required');return}
      const r=await fetch('/api/farmer/login/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:key})}).then(r=>r.json().then(d=>({ok:r.ok,d}))); 
      if(!r.ok){err.textContent=r.d.error||t('err');return} location.href='/observatory/'; return; }
    const login=$('fLogin').value.trim(), password=$('fPass').value; if(!login||!password){err.textContent=t('required');return}
    const payload={login,password}; if(mode==='register'){ const name=$('fName').value.trim(); if(!name){err.textContent=t('name');return} payload.name=name; payload.phone=($('fPhone')&&$('fPhone').value.trim())||''; }
    const url=mode==='register'?'/api/farmer/register/':'/api/farmer/login/';
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(r=>r.json().then(d=>({ok:r.ok,d})));
    if(!r.ok){err.textContent=r.d.error||t('err');return} location.href='/observatory/'; }
  $('tabLogin').onclick=()=>render('login'); $('tabRegister').onclick=()=>render('register'); $('tabKey').onclick=()=>render('key');
  $('langBtn').onclick=()=>{lang=lang==='fa'?'en':'fa';localStorage.setItem('landing_lang',lang);apply()};
  document.documentElement.lang=lang; document.documentElement.dir=lang==='fa'?'rtl':'ltr';
  ['tabLogin','tabRegister','tabKey'].forEach(id=>$(id).dataset.m=id==='tabLogin'?'login':id==='tabRegister'?'register':'key');
  render('login'); $('authHint').textContent=t('pass_hint');
})();
