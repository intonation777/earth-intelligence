(() => {
  const STORAGE_KEY = 'landing_lang';
  const EN_URL = '/static/shared/i18n/landing_en.json?v=2';
  const FA_URL = '/static/shared/i18n/landing_fa.json?v=2';
  const state = { lang: 'en', dict: { en: {}, fa: {} }, menuOpen: false };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) {}
  }

  async function loadDicts() {
    try {
      const [en, fa] = await Promise.all([
        fetch(EN_URL).then(r => r.ok ? r.json() : {}),
        fetch(FA_URL).then(r => r.ok ? r.json() : {})
      ]);
      state.dict.en = en || {};
      state.dict.fa = fa || {};
    } catch (e) {
      state.dict.en = {};
      state.dict.fa = {};
    }
  }

  function applyTranslations() {
    const dict = state.dict[state.lang] || {};

    $$('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n;
      if (dict[key] != null) el.textContent = dict[key];
    });
    $$('[data-i18n-alt]').forEach(el => {
      const key = el.dataset.i18nAlt;
      if (dict[key] != null) el.setAttribute('alt', dict[key]);
    });
    $$('[data-i18n-aria]').forEach(el => {
      const key = el.dataset.i18nAria;
      if (dict[key] != null) el.setAttribute('aria-label', dict[key]);
    });
    $$('[data-i18n-title]').forEach(el => {
      const key = el.dataset.i18nTitle;
      if (dict[key] != null) el.setAttribute('title', dict[key]);
    });
    $$('[data-i18n-content]').forEach(el => {
      const key = el.dataset.i18nContent;
      if (dict[key] != null) el.setAttribute('content', dict[key]);
    });
    $$('[data-i18n-placeholder]').forEach(el => {
      const key = el.dataset.i18nPlaceholder;
      if (dict[key] != null) el.setAttribute('placeholder', dict[key]);
    });

    if (dict.page_title) document.title = dict.page_title;
  }

  function updateLangButtons() {
    $$('.lang-btn').forEach(btn => {
      const active = btn.dataset.lang === state.lang;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.classList.toggle('active', active);
    });
  }

  function setLanguage(lang, persist = true) {
    state.lang = lang === 'fa' ? 'fa' : 'en';
    document.documentElement.lang = state.lang === 'fa' ? 'fa' : 'en';
    document.documentElement.dir = state.lang === 'fa' ? 'rtl' : 'ltr';
    if (persist) storageSet(STORAGE_KEY, state.lang);
    applyTranslations();
    updateLangButtons();
  }

  function initMenu() {
    const toggle = $('.nav-toggle');
    const nav = $('.site-nav');
    if (!toggle || !nav) return;

    const close = () => {
      state.menuOpen = false;
      nav.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    };

    toggle.addEventListener('click', () => {
      state.menuOpen = !state.menuOpen;
      nav.classList.toggle('open', state.menuOpen);
      toggle.setAttribute('aria-expanded', String(state.menuOpen));
    });

    nav.addEventListener('click', event => {
      if (event.target.closest('a')) close();
    });

    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && state.menuOpen) {
        close();
        toggle.focus();
      }
    });

    window.addEventListener('resize', () => {
      if (window.innerWidth > 1020) close();
    });
  }

  function updateActiveNav() {
    const path = window.location.pathname.replace(/\/+$/, '') || '/';
    const hash = window.location.hash;
    $$('.site-nav a[data-nav]').forEach(link => link.removeAttribute('aria-current'));

    if (path !== '/') return;
    const key = hash === '#platform' ? 'platform'
      : hash === '#data' ? 'data'
      : hash === '#about' ? 'about'
      : 'home';
    const active = document.querySelector(`.site-nav a[data-nav="${key}"]`);
    if (active) active.setAttribute('aria-current', 'page');
  }

  async function init() {
    await loadDicts();
    const saved = storageGet(STORAGE_KEY);
    setLanguage(saved === 'fa' ? 'fa' : 'en', false);
    updateActiveNav();
    window.addEventListener('hashchange', updateActiveNav);
    window.addEventListener('popstate', updateActiveNav);
    initMenu();
    $$('.lang-btn').forEach(btn => {
      btn.addEventListener('click', () => setLanguage(btn.dataset.lang));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
