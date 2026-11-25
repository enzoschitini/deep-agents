/* Núcleo: namespace TA, barramento de eventos, estado global e o construtor de DOM `TA.h`. */
window.TA = {
  views: {}, ui: {}, util: {}, fmt: {}, charts: {}, api: {},
  state: { range: 'all', theme: 'light' },
};

/* ---- barramento de eventos ---- */
TA.bus = (function () {
  const map = new Map();
  return {
    on(name, fn) {
      if (!map.has(name)) map.set(name, new Set());
      map.get(name).add(fn);
      return () => map.get(name).delete(fn);
    },
    emit(name, payload) {
      (map.get(name) || []).forEach((fn) => { try { fn(payload); } catch (e) { console.error('[bus]', name, e); } });
    },
  };
})();

/* ---- h(tag, attrs, ...children) ----
   attrs: class | className, style (string ou objeto), on<Evento>: fn, dataset: {}, value/checked/disabled/...: propriedades,
   qualquer outro: atributo. children: string | number | Node | array | null/false (ignorados).
   Texto SEMPRE como nó de texto (seguro para dados vindos dos JSONs). Tags SVG: use TA.h.svg(tag, attrs, ...). */
TA.h = function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  TA.h._apply(el, attrs);
  TA.h._append(el, children);
  return el;
};
TA.h.svg = function svg(tag, attrs, ...children) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  TA.h._apply(el, attrs);
  TA.h._append(el, children);
  return el;
};
TA.h._apply = function (el, attrs) {
  if (!attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class' || k === 'className') el.setAttribute('class', Array.isArray(v) ? v.filter(Boolean).join(' ') : v);
    else if (k === 'style') {
      if (typeof v === 'string') el.setAttribute('style', v);
      else Object.entries(v).forEach(([sk, sv]) => { if (sv !== null && sv !== undefined) (sk.startsWith('--') ? el.style.setProperty(sk, sv) : (el.style[sk] = sv)); });
    }
    else if (k === 'dataset') Object.entries(v).forEach(([dk, dv]) => { el.dataset[dk] = dv; });
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected' || k === 'indeterminate') el[k] = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
};
TA.h._append = function (el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) TA.h._append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
};
