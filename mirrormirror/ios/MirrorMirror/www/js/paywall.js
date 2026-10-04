/* Free readings, then a subscription.
   The first few readings are free. After that the mirror asks for Mirror Mirror Premium, an
   auto-renewing subscription bought through the App Store (StoreKit 2) when this page runs inside
   the iOS app. On the open web there is no store, so the paywall says where to subscribe.

   Bridge protocol (iOS app):
     JS -> native : window.webkit.messageHandlers.store.postMessage({ type, productId })
                    type: 'status' | 'purchase' | 'restore' | 'manage'
     native -> JS : window.__mirrorStore.receive({ type, entitled, price, period, expires, ok, error, cancelled, pending }) */

const CFG = (typeof window !== 'undefined' && window.MM_CONFIG) || {};
export const PAYWALL = {
  freeScans: Number.isFinite(CFG.freeScans) ? CFG.freeScans : 3,
  productId: CFG.productId || 'com.grandviewventures.mirrormirror.monthly',
  price: CFG.price || '$0.99',
  period: CFG.period || 'month',
  appStoreUrl: CFG.appStoreUrl || '',
  platform: CFG.platform || 'web',
};
const KEYS = { scans: 'mm.scans.v1', entitled: 'mm.entitled.v1', dev: 'mm.dev.unlocked' };

function read(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } }
function write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage unavailable: the count simply resets */ } }

export function hasNativeStore() {
  return !!(typeof window !== 'undefined' && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.store);
}

export function createPaywall() {
  const listeners = new Set();
  const state = {
    scans: read(KEYS.scans, 0), entitled: read(KEYS.entitled, false) === true,
    price: PAYWALL.price, period: PAYWALL.period, expires: null, busy: false, lastError: null, storeReady: false,
  };
  const emit = () => listeners.forEach((l) => { try { l(state); } catch (e) { console.warn(e); } });
  const pending = new Map();

  window.__mirrorStore = {
    receive(msg) {
      if (!msg || typeof msg !== 'object') return;
      if (typeof msg.entitled === 'boolean') { state.entitled = msg.entitled; write(KEYS.entitled, msg.entitled); }
      if (msg.price) state.price = msg.price;
      if (msg.period) state.period = msg.period;
      if (msg.expires !== undefined) state.expires = msg.expires || null;
      if (msg.type === 'status') state.storeReady = true;
      if (msg.error) state.lastError = msg.error;
      const resolve = pending.get(msg.type);
      if (resolve) { pending.delete(msg.type); resolve(msg); }
      emit();
    },
  };

  const post = (type) => new Promise((resolve) => {
    if (!hasNativeStore()) { resolve({ type, ok: false, error: 'no-store' }); return; }
    pending.set(type, resolve);
    try { window.webkit.messageHandlers.store.postMessage({ type, productId: PAYWALL.productId }); }
    catch (e) { pending.delete(type); resolve({ type, ok: false, error: String(e) }); return; }
    setTimeout(() => { if (pending.get(type) === resolve) { pending.delete(type); resolve({ type, ok: false, error: 'timeout' }); } }, type === 'status' ? 8000 : 180000);
  });

  const api = {
    state,
    onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    get hasStore() { return hasNativeStore(); },
    isEntitled() { return state.entitled || read(KEYS.dev, false) === true; },
    scansUsed() { return state.scans; },
    freeLeft() { return Math.max(0, PAYWALL.freeScans - state.scans); },
    canScan() { return api.isEntitled() || api.freeLeft() > 0; },
    recordScan() { state.scans += 1; write(KEYS.scans, state.scans); emit(); },
    async refresh() { if (hasNativeStore()) await post('status'); emit(); },
    async purchase() {
      state.busy = true; state.lastError = null; emit();
      const r = await post('purchase');
      state.busy = false;
      if (r.error === 'no-store') state.lastError = 'Subscriptions are bought inside the Mirror Mirror app from the App Store.';
      else if (r.error && r.error !== 'timeout') state.lastError = r.error;
      else if (r.pending) state.lastError = 'Your purchase is waiting for approval (Ask to Buy). The mirror will unlock when it arrives.';
      emit(); return r;
    },
    async restore() {
      state.busy = true; state.lastError = null; emit();
      const r = await post('restore');
      state.busy = false;
      if (r.error === 'no-store') state.lastError = 'There is nothing to restore on the web; open the Mirror Mirror app.';
      else if (!r.entitled) state.lastError = 'No active subscription was found for this Apple ID.';
      emit(); return r;
    },
    manage() { if (hasNativeStore()) post('manage'); },
  };
  return api;
}

/* ----------------------------------------------------------------- the paywall screen */
const h = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v; else if (k === 'html') n.innerHTML = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k.nodeType ? k : document.createTextNode(String(k)));
  return n;
};

/** Render the paywall into `root`. Calls onUnlocked() once the subscription is active, onBack() for "not now". */
export function renderPaywall(root, paywall, { onBack, onUnlocked }) {
  root.innerHTML = '';
  const st = paywall.state;
  const used = paywall.scansUsed();
  const title = h('h2', { class: 'section-title' }, used >= PAYWALL.freeScans ? 'Your free readings are spent' : 'Keep consulting the mirror');
  const lede = h('p', { class: 'lede' },
    `You have had ${used} free ${used === 1 ? 'reading' : 'readings'}. `,
    h('strong', {}, 'Mirror Mirror Premium'), ' gives you unlimited readings, every line of the arithmetic each time, the shareable card, and the mirror’s undivided attention.');
  const priceLine = h('p', { class: 'price-line' }, h('b', { id: 'pw-price' }, st.price), h('span', {}, ` per ${st.period}`));
  const err = h('p', { class: 'status err', role: 'alert' });
  const btnBuy = h('button', { class: 'btn btn-primary', type: 'button' }, `Subscribe · ${st.price} / ${st.period}`);
  const btnRestore = h('button', { class: 'btn btn-secondary', type: 'button' }, 'Restore purchases');
  const btnBack = h('button', { class: 'btn btn-ghost', type: 'button' }, 'Not now');
  const terms = h('p', { class: 'fineprint' },
    `Payment is charged to your Apple ID at confirmation. The subscription renews automatically each ${st.period} at ${st.price} unless it is cancelled at least 24 hours before the end of the current period. You can manage or cancel it any time in Settings › Apple ID › Subscriptions. `,
    h('a', { href: 'privacy.html' }, 'Privacy Policy'), ' · ', h('a', { href: 'terms.html' }, 'Terms of Use'), ' · ',
    h('a', { href: 'https://www.apple.com/legal/internet-services/itunes/dev/stdeula/', target: '_blank', rel: 'noopener' }, 'Apple’s standard EULA'));
  const webNote = !paywall.hasStore ? h('div', { class: 'note info' },
    'Subscriptions are bought inside the Mirror Mirror app on the iPhone, where the purchase goes through the App Store. ',
    PAYWALL.appStoreUrl ? h('a', { href: PAYWALL.appStoreUrl }, 'Get the app') : 'The app is on its way to the App Store.') : null;

  const update = () => {
    btnBuy.disabled = st.busy; btnRestore.disabled = st.busy;
    btnBuy.textContent = st.busy ? 'One moment…' : `Subscribe · ${st.price} / ${st.period}`;
    document.getElementById('pw-price') && (document.getElementById('pw-price').textContent = st.price);
    err.textContent = st.lastError || '';
    if (paywall.isEntitled()) { off(); onUnlocked && onUnlocked(); }
  };
  const off = paywall.onChange(update);
  btnBuy.addEventListener('click', () => paywall.purchase());
  btnRestore.addEventListener('click', () => paywall.restore());
  btnBack.addEventListener('click', () => { off(); onBack && onBack(); });

  root.append(
    h('div', { class: 'mirror-frame mirror-frame--idle paywall-frame', 'aria-hidden': 'true' }, h('div', { class: 'mirror-glass' }, h('div', { class: 'mirror-phi' }, 'φ'))),
    title, lede, priceLine,
    h('ul', { class: 'perks' },
      h('li', {}, 'Unlimited readings, camera or photo'),
      h('li', {}, 'The seven golden ratios, the canons, symmetry and the modern ratios, with every formula'),
      h('li', {}, 'Millimetre estimates and the shareable card'),
      h('li', {}, 'Nothing ever leaves your phone'),
    ),
    h('div', { class: 'actions' }, btnBuy, btnRestore, btnBack),
    err, webNote, terms,
  );
  update();
  paywall.refresh();
}
