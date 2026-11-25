/* DOM falso e APIs de navegador para rodar o front-end do tracing_app dentro do QuickJS, sem navegador.
   Escrito em JS simples; cobre o que a base e as views usam (ver README em smoke/runner.py: "limitações").
   Tudo que o harness precisa fica em `globalThis.__smoke` (relógio virtual, erros capturados, logs, fetch). */
(function (G) {
  'use strict';

  const HTML_NS = 'http://www.w3.org/1999/xhtml';
  const SVG_NS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------------ estado do harness */
  const S = G.__smoke = {
    errors: [],        // erros duros: console.error, exceções em listeners/timers, rejeições de listeners async
    soft: [],          // exceções dentro de callbacks .then/.catch (podem ter sido tratadas depois)
    warnings: [],      // console.warn
    logs: [],          // console.log/info/debug
    fetches: [],       // URLs pedidas
    opened: [],        // window.open
    blobs: new Map(),  // blob: URL -> Blob
    clipboard: null,
    phase: 'carga',
    now: 0,            // relógio virtual (ms)
    hoverables: new Set(),
    clickables: new Set(),
  };

  function fmtArg(a) {
    if (a instanceof Error) return a.name + ': ' + a.message;
    if (typeof a === 'string') return a;
    if (a === undefined) return 'undefined';
    if (typeof a === 'function') return '[function ' + (a.name || 'anônima') + ']';
    try { return JSON.stringify(a); } catch (e) { return String(a); }
  }
  function stackOf(args) {
    for (const a of args) if (a instanceof Error && a.stack) return String(a.stack);
    return String(new Error('trace').stack || '');
  }
  function reportError(e, where) {
    const isErr = e instanceof Error;
    S.errors.push({
      kind: 'uncaught', where: where || '', phase: S.phase,
      name: isErr ? e.name : typeof e,
      message: isErr ? e.message : fmtArg(e),
      stack: isErr && e.stack ? String(e.stack) : '',
    });
  }
  S.reportError = reportError;

  /* ------------------------------------------------------------------ console */
  const con = {};
  ['log', 'info', 'debug', 'dir', 'table', 'group', 'groupCollapsed', 'groupEnd', 'time', 'timeEnd', 'timeLog', 'count', 'clear', 'trace'].forEach((k) => {
    con[k] = function (...a) { S.logs.push({ level: k, phase: S.phase, text: a.map(fmtArg).join(' ') }); };
  });
  con.warn = function (...a) { S.warnings.push({ phase: S.phase, text: a.map(fmtArg).join(' '), stack: stackOf(a) }); };
  con.error = function (...a) {
    S.errors.push({ kind: 'console.error', phase: S.phase, where: '', name: '', message: a.map(fmtArg).join(' '), stack: stackOf(a) });
  };
  con.assert = function (cond, ...a) { if (!cond) con.error('Assertion failed:', ...a); };
  G.console = con;

  /* ------------------------------------------------------------------ DOMException e erros */
  class DOMException extends Error {
    constructor(message, name) {
      super(message === undefined ? '' : String(message));
      this.name = name || 'Error';
      const codes = { IndexSizeError: 1, HierarchyRequestError: 3, NotFoundError: 8, InvalidCharacterError: 5, SyntaxError: 12, AbortError: 20 };
      this.code = codes[this.name] || 0;
    }
  }
  G.DOMException = DOMException;

  /* ------------------------------------------------------------------ eventos */
  class Event {
    constructor(type, init) {
      init = init || {};
      this.type = String(type);
      this.bubbles = !!init.bubbles;
      this.cancelable = !!init.cancelable;
      this.composed = !!init.composed;
      this.defaultPrevented = false;
      this.target = null;
      this.currentTarget = null;
      this.eventPhase = 0;
      this.isTrusted = false;
      this.timeStamp = S.now;
      this._stop = false;
      this._stopImm = false;
    }
    preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
    stopPropagation() { this._stop = true; }
    stopImmediatePropagation() { this._stop = true; this._stopImm = true; }
    composedPath() { return this._path ? this._path.slice() : []; }
  }
  const eventClass = (name, defaults) => {
    const C = class extends Event {
      constructor(type, init) {
        super(type, init);
        Object.assign(this, defaults, init || {});
      }
    };
    Object.defineProperty(C, 'name', { value: name });
    G[name] = C;
    return C;
  };
  const MouseEvent = eventClass('MouseEvent', { clientX: 0, clientY: 0, screenX: 0, screenY: 0, pageX: 0, pageY: 0, offsetX: 0, offsetY: 0, button: 0, buttons: 0, ctrlKey: false, shiftKey: false, altKey: false, metaKey: false, relatedTarget: null, detail: 0 });
  eventClass('PointerEvent', { clientX: 0, clientY: 0, pointerId: 1, pointerType: 'mouse', button: 0, buttons: 0, ctrlKey: false, shiftKey: false, altKey: false, metaKey: false });
  eventClass('WheelEvent', { clientX: 0, clientY: 0, deltaX: 0, deltaY: 0, deltaMode: 0, ctrlKey: false });
  eventClass('KeyboardEvent', { key: '', code: '', ctrlKey: false, shiftKey: false, altKey: false, metaKey: false, repeat: false });
  eventClass('InputEvent', { data: null, inputType: '' });
  eventClass('FocusEvent', { relatedTarget: null });
  eventClass('CustomEvent', { detail: null });
  eventClass('HashChangeEvent', { oldURL: '', newURL: '' });
  eventClass('PopStateEvent', { state: null });
  eventClass('ErrorEvent', { message: '', error: null });
  eventClass('StorageEvent', { key: null, oldValue: null, newValue: null });
  G.Event = Event;

  const parentOf = (n) => (n === G ? null : (n.nodeType === 9 ? G : (n.parentNode || null)));
  const listenersOf = (n, create) => {
    if (!n._l) { if (!create) return null; Object.defineProperty(n, '_l', { value: new Map(), enumerable: false }); }
    return n._l;
  };
  const HOVER_TYPES = ['mouseenter', 'mouseover', 'mousemove', 'pointerenter', 'pointerover', 'pointermove'];

  function callListener(node, fn, ev, where) {
    try {
      const r = typeof fn === 'function' ? fn.call(node, ev) : (fn && typeof fn.handleEvent === 'function' ? fn.handleEvent(ev) : undefined);
      if (r && typeof r.then === 'function') r.then(null, (e) => reportError(e, where + ' (async)'));
    } catch (e) { reportError(e, where); }
  }
  function invoke(node, ev, capturePhase) {
    ev.currentTarget = node;
    const map = listenersOf(node, false);
    const list = map && map.get(ev.type);
    if (list) {
      for (const l of list.slice()) {
        if (l.removed) continue;
        if (capturePhase === true && !l.capture) continue;
        if (capturePhase === false && l.capture) continue;
        if (l.once) node.removeEventListener(ev.type, l.fn, l.capture);
        callListener(node, l.fn, ev, 'listener de "' + ev.type + '"');
        if (ev._stopImm) return;
      }
    }
    if (capturePhase !== true && typeof node['on' + ev.type] === 'function') callListener(node, node['on' + ev.type], ev, 'on' + ev.type);
  }

  class EventTarget {
    addEventListener(type, fn, opts) {
      if (fn === null || fn === undefined) return;
      const capture = typeof opts === 'boolean' ? opts : !!(opts && opts.capture);
      const once = !!(opts && typeof opts === 'object' && opts.once);
      const map = listenersOf(this, true);
      if (!map.has(type)) map.set(type, []);
      const list = map.get(type);
      if (list.some((l) => l.fn === fn && l.capture === capture)) return;
      list.push({ fn, capture, once, removed: false });
      if (this instanceof Element) {
        if (HOVER_TYPES.includes(type)) S.hoverables.add(this);
        if (type === 'click') S.clickables.add(this);
      }
      if (opts && typeof opts === 'object' && opts.signal) opts.signal.addEventListener('abort', () => this.removeEventListener(type, fn, capture));
    }
    removeEventListener(type, fn, opts) {
      const capture = typeof opts === 'boolean' ? opts : !!(opts && opts.capture);
      const map = listenersOf(this, false);
      const list = map && map.get(type);
      if (!list) return;
      const i = list.findIndex((l) => l.fn === fn && l.capture === capture);
      if (i >= 0) { list[i].removed = true; list.splice(i, 1); }
    }
    dispatchEvent(ev) {
      if (!(ev instanceof Event)) throw new TypeError("Failed to execute 'dispatchEvent' on 'EventTarget': parameter 1 is not of type 'Event'.");
      ev.target = this; ev._stop = false; ev._stopImm = false; ev.defaultPrevented = false;
      const path = [];
      for (let p = parentOf(this); p; p = parentOf(p)) path.push(p);
      ev._path = [this].concat(path);
      ev.eventPhase = 1;
      for (let i = path.length - 1; i >= 0 && !ev._stop; i--) invoke(path[i], ev, true);
      ev.eventPhase = 2;
      if (!ev._stop) { invoke(this, ev, true); if (!ev._stopImm) invoke(this, ev, false); }
      if (ev.bubbles) {
        ev.eventPhase = 3;
        for (let i = 0; i < path.length && !ev._stop; i++) invoke(path[i], ev, false);
      }
      ev.eventPhase = 0; ev.currentTarget = null;
      return !ev.defaultPrevented;
    }
  }
  G.EventTarget = EventTarget;

  /* ------------------------------------------------------------------ listas (NodeList/HTMLCollection sem os métodos de Array, como no navegador) */
  class NodeList {
    item(i) { return this[i] || null; }
    forEach(fn, t) { for (let i = 0; i < this.length; i++) fn.call(t, this[i], i, this); }
    entries() { return Array.prototype.map.call(this, (x, i) => [i, x])[Symbol.iterator](); }
    keys() { return Array.prototype.map.call(this, (x, i) => i)[Symbol.iterator](); }
    values() { return Array.prototype.slice.call(this)[Symbol.iterator](); }
    [Symbol.iterator]() { return Array.prototype.slice.call(this)[Symbol.iterator](); }
  }
  class HTMLCollection {
    item(i) { return this[i] || null; }
    namedItem(n) { for (let i = 0; i < this.length; i++) if (this[i].id === n || this[i].getAttribute('name') === n) return this[i]; return null; }
    [Symbol.iterator]() { return Array.prototype.slice.call(this)[Symbol.iterator](); }
  }
  function fillList(proto, arr) {
    const o = Object.create(proto);
    for (let i = 0; i < arr.length; i++) o[i] = arr[i];
    Object.defineProperty(o, 'length', { value: arr.length });
    return o;
  }
  const makeNodeList = (arr) => fillList(NodeList.prototype, arr);
  const makeCollection = (arr) => fillList(HTMLCollection.prototype, arr);
  G.NodeList = NodeList; G.HTMLCollection = HTMLCollection;

  /* ------------------------------------------------------------------ nós */
  class Node extends EventTarget {
    constructor() {
      super();
      this.parentNode = null;
      Object.defineProperty(this, '_c', { value: [], enumerable: false, writable: true });
    }
    get ownerDocument() { return G.document; }
    get childNodes() { return makeNodeList(this._c); }
    get firstChild() { return this._c[0] || null; }
    get lastChild() { return this._c[this._c.length - 1] || null; }
    get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p._c.indexOf(this); return p._c[i + 1] || null; }
    get previousSibling() { const p = this.parentNode; if (!p) return null; const i = p._c.indexOf(this); return i > 0 ? p._c[i - 1] : null; }
    get parentElement() { const p = this.parentNode; return p && p.nodeType === 1 ? p : null; }
    get isConnected() { let p = this; while (p.parentNode) p = p.parentNode; return p === G.document; }
    hasChildNodes() { return this._c.length > 0; }
    getRootNode() { let p = this; while (p.parentNode) p = p.parentNode; return p; }
    contains(o) { for (let p = o; p; p = p.parentNode) if (p === this) return true; return false; }
    get textContent() {
      if (this.nodeType === 3 || this.nodeType === 8) return this.data;
      let s = '';
      for (const c of this._c) if (c.nodeType !== 8) s += c.textContent;
      return s;
    }
    set textContent(v) {
      if (this.nodeType === 3 || this.nodeType === 8) { this.data = v === null || v === undefined ? '' : String(v); return; }
      this._clear();
      const s = v === null || v === undefined ? '' : String(v);
      if (s !== '') this._insert(new Text(s), null);
    }
    get nodeValue() { return this.nodeType === 3 || this.nodeType === 8 ? this.data : null; }
    set nodeValue(v) { if (this.nodeType === 3 || this.nodeType === 8) this.data = String(v); }
    _clear() { for (const c of this._c) c.parentNode = null; this._c.length = 0; }
    _insert(node, ref) {
      if (!(node instanceof Node)) throw new TypeError("Failed to execute 'insertBefore' on 'Node': parameter 1 is not of type 'Node'.");
      if (node.nodeType === 11) {
        const kids = node._c.slice();
        node._clear();
        for (const k of kids) this._insert(k, ref);
        return node;
      }
      if (node === ref) ref = node.nextSibling;
      for (let p = this; p; p = p.parentNode) {
        if (p === node) throw new DOMException('The new child element contains the parent.', 'HierarchyRequestError');
      }
      if (this.nodeType === 3 || this.nodeType === 8) throw new DOMException('This node type does not support this method.', 'HierarchyRequestError');
      if (node.parentNode) node.parentNode._removeRaw(node);
      const idx = ref ? this._c.indexOf(ref) : this._c.length;
      if (idx < 0) throw new DOMException("Failed to execute 'insertBefore' on 'Node': The node before which the new node is to be inserted is not a child of this node.", 'NotFoundError');
      this._c.splice(idx, 0, node);
      node.parentNode = this;
      return node;
    }
    _removeRaw(node) {
      const i = this._c.indexOf(node);
      if (i >= 0) { this._c.splice(i, 1); node.parentNode = null; }
    }
    appendChild(node) { if (!(node instanceof Node)) throw new TypeError("Failed to execute 'appendChild' on 'Node': parameter 1 is not of type 'Node'."); return this._insert(node, null); }
    insertBefore(node, ref) { return this._insert(node, ref === undefined ? null : ref); }
    removeChild(node) {
      if (!(node instanceof Node)) throw new TypeError("Failed to execute 'removeChild' on 'Node': parameter 1 is not of type 'Node'.");
      if (node.parentNode !== this) throw new DOMException("Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.", 'NotFoundError');
      this._removeRaw(node);
      return node;
    }
    replaceChild(neu, old) {
      if (old.parentNode !== this) throw new DOMException("Failed to execute 'replaceChild' on 'Node': The node to be replaced is not a child of this node.", 'NotFoundError');
      const ref = old.nextSibling === neu ? neu.nextSibling : old.nextSibling;
      this._removeRaw(old);
      this._insert(neu, ref);
      return old;
    }
    _toNodes(list) { return list.map((x) => (x instanceof Node ? x : new Text(String(x)))); }
    append(...list) { for (const n of this._toNodes(list)) this._insert(n, null); }
    prepend(...list) { const ref = this.firstChild; for (const n of this._toNodes(list)) this._insert(n, ref); }
    replaceChildren(...list) { this._clear(); this.append(...list); }
    remove() { if (this.parentNode) this.parentNode._removeRaw(this); }
    before(...list) { const p = this.parentNode; if (!p) return; for (const n of this._toNodes(list)) p._insert(n, this); }
    after(...list) { const p = this.parentNode; if (!p) return; const ref = this.nextSibling; for (const n of this._toNodes(list)) p._insert(n, ref); }
    replaceWith(...list) { const p = this.parentNode; if (!p) return; const ref = this.nextSibling; p._removeRaw(this); for (const n of this._toNodes(list)) p._insert(n, ref); }
    normalize() {}
    isSameNode(o) { return this === o; }
    cloneNode(deep) {
      const c = this._shallowClone();
      if (deep) for (const k of this._c) c._insert(k.cloneNode(true), null);
      return c;
    }
  }
  Object.assign(Node, { ELEMENT_NODE: 1, TEXT_NODE: 3, COMMENT_NODE: 8, DOCUMENT_NODE: 9, DOCUMENT_FRAGMENT_NODE: 11 });
  G.Node = Node;

  class Text extends Node {
    constructor(data) { super(); this.nodeType = 3; this.nodeName = '#text'; this.data = data === undefined ? '' : String(data); }
    get length() { return this.data.length; }
    get wholeText() { return this.data; }
    _shallowClone() { return new Text(this.data); }
  }
  class Comment extends Node {
    constructor(data) { super(); this.nodeType = 8; this.nodeName = '#comment'; this.data = data === undefined ? '' : String(data); }
    _shallowClone() { return new Comment(this.data); }
  }
  G.Text = Text; G.Comment = Comment;

  class DocumentFragment extends Node {
    constructor() { super(); this.nodeType = 11; this.nodeName = '#document-fragment'; }
    _shallowClone() { return new DocumentFragment(); }
    get children() { return makeCollection(this._c.filter((c) => c.nodeType === 1)); }
    get firstElementChild() { return this._c.find((c) => c.nodeType === 1) || null; }
    get lastElementChild() { const e = this._c.filter((c) => c.nodeType === 1); return e[e.length - 1] || null; }
    get childElementCount() { return this._c.filter((c) => c.nodeType === 1).length; }
    getElementById(id) { return findFirst(this, (e) => e.getAttribute('id') === id); }
  }
  G.DocumentFragment = DocumentFragment;

  /* ------------------------------------------------------------------ CSS inline */
  const kebab = (s) => s.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());
  class CSSStyle {
    setProperty(name, value) {
      if (name.startsWith('--')) this._custom.set(name, String(value));
      else if (value === '' || value === null || value === undefined) this.removeProperty(name);
      else this[name.replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = String(value);
    }
    getPropertyValue(name) {
      if (name.startsWith('--')) return this._custom.get(name) || '';
      const v = this[name.replace(/-([a-z])/g, (m, c) => c.toUpperCase())];
      return v === undefined ? '' : String(v);
    }
    removeProperty(name) {
      if (name.startsWith('--')) { const old = this._custom.get(name) || ''; this._custom.delete(name); return old; }
      const k = name.replace(/-([a-z])/g, (m, c) => c.toUpperCase());
      const old = this[k]; delete this[k]; return old === undefined ? '' : old;
    }
    get cssText() {
      const parts = [];
      for (const k of Object.keys(this)) if (k[0] !== '_') parts.push(kebab(k) + ': ' + this[k]);
      for (const [k, v] of this._custom) parts.push(k + ': ' + v);
      return parts.join('; ') + (parts.length ? ';' : '');
    }
    set cssText(text) {
      for (const k of Object.keys(this)) if (k[0] !== '_') delete this[k];
      this._custom.clear();
      String(text || '').split(';').forEach((d) => {
        const i = d.indexOf(':');
        if (i > 0) this.setProperty(d.slice(0, i).trim(), d.slice(i + 1).trim());
      });
    }
  }
  function makeStyle() {
    const target = new CSSStyle();
    Object.defineProperty(target, '_custom', { value: new Map(), enumerable: false });
    return new Proxy(target, {
      get(t, p, r) {
        if (typeof p === 'symbol' || p in t) return Reflect.get(t, p, r);
        return '';   // propriedade CSS sem valor: string vazia, como no navegador
      },
    });
  }

  /* ------------------------------------------------------------------ HTML: parser e serializador mínimos */
  const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
  const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
  const decodeEnt = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === '#') return String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENT[e.toLowerCase()] !== undefined ? ENT[e.toLowerCase()] : m;
  });
  const escText = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const escAttr = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;');

  function parseHTML(html, inSvg) {
    const root = new DocumentFragment();
    const stack = [root];
    const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][^\s>]*)\s*>|<([a-zA-Z][^\s/>]*)((?:\s+[^\s=\/>]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|[^<]+|</g;
    const attrRe = /([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
    let m;
    const top = () => stack[stack.length - 1];
    const svgCtx = () => inSvg || stack.some((n) => n.namespaceURI === SVG_NS && n.localName !== 'foreignObject');
    while ((m = re.exec(html)) !== null) {
      const tok = m[0];
      if (tok.startsWith('<!--')) top()._insert(new Comment(tok.slice(4, -3)), null);
      else if (m[1]) {
        const name = m[1].toLowerCase();
        for (let i = stack.length - 1; i > 0; i--) {
          if (stack[i].localName.toLowerCase() === name) { stack.length = i; break; }
        }
      } else if (m[2]) {
        const tag = m[2];
        const ns = tag.toLowerCase() === 'svg' || svgCtx() ? SVG_NS : HTML_NS;
        const el = makeElement(tag, ns);
        let a;
        attrRe.lastIndex = 0;
        while ((a = attrRe.exec(m[3] || '')) !== null) {
          el.setAttribute(a[1], a[2] !== undefined ? decodeEnt(a[2]) : a[3] !== undefined ? decodeEnt(a[3]) : a[4] !== undefined ? decodeEnt(a[4]) : '');
        }
        top()._insert(el, null);
        const lower = tag.toLowerCase();
        if (m[4] || (ns === HTML_NS && VOID.has(lower))) continue;
        if (ns === HTML_NS && (lower === 'script' || lower === 'style')) {
          const end = html.toLowerCase().indexOf('</' + lower, re.lastIndex);
          const stop = end < 0 ? html.length : end;
          if (stop > re.lastIndex) el._insert(new Text(html.slice(re.lastIndex, stop)), null);
          re.lastIndex = stop;
          continue;
        }
        stack.push(el);
      } else if (tok === '<') top()._insert(new Text('<'), null);
      else top()._insert(new Text(decodeEnt(tok)), null);
    }
    return root;
  }
  function serialize(node) {
    if (node.nodeType === 3) return escText(node.data);
    if (node.nodeType === 8) return '<!--' + node.data + '-->';
    if (node.nodeType === 11 || node.nodeType === 9) return node._c.map(serialize).join('');
    let attrs = '';
    for (const [k, v] of node._attrList()) attrs += ' ' + k + '="' + escAttr(v) + '"';
    const inner = node.localName === 'template' ? serialize(node.content) : node._c.map(serialize).join('');
    if (node.namespaceURI === HTML_NS && VOID.has(node.localName)) return '<' + node.localName + attrs + '>';
    return '<' + node.localName + attrs + '>' + inner + '</' + node.localName + '>';
  }

  /* ------------------------------------------------------------------ seletores CSS */
  const selCache = new Map();
  function parseSelectorList(src) {
    if (selCache.has(src)) return selCache.get(src);
    const s = String(src).trim();
    let i = 0;
    const syntax = (why) => new DOMException("'" + src + "' is not a valid selector" + (why ? ' (' + why + ')' : '') + '.', 'SyntaxError');
    const ident = () => {
      const m = /^(?:\\.|[\w\- -￿])+/.exec(s.slice(i));
      if (!m) throw syntax('identificador esperado na posição ' + i);
      i += m[0].length;
      return m[0].replace(/\\(.)/g, '$1');
    };
    const ws = () => { while (i < s.length && /\s/.test(s[i])) i++; };
    function readParen() {
      let depth = 1; const start = i;
      while (i < s.length && depth) { if (s[i] === '(') depth++; else if (s[i] === ')') depth--; i++; }
      if (depth) throw syntax('parêntese sem fechar');
      return s.slice(start, i - 1);
    }
    function compound() {
      const c = { tag: null, id: null, classes: [], attrs: [], pseudos: [] };
      let any = false;
      for (;;) {
        const ch = s[i];
        if (ch === '*') { c.tag = '*'; i++; any = true; }
        else if (ch === '#') { i++; c.id = ident(); any = true; }
        else if (ch === '.') { i++; c.classes.push(ident()); any = true; }
        else if (ch === '[') {
          i++; ws();
          const name = ident(); ws();
          let op = null, value = null, flag = '';
          if (s[i] !== ']') {
            const mo = /^([~|^$*]?=)/.exec(s.slice(i));
            if (!mo) throw syntax('operador de atributo');
            op = mo[1]; i += op.length; ws();
            if (s[i] === '"' || s[i] === "'") {
              const q = s[i]; const end = s.indexOf(q, i + 1);
              if (end < 0) throw syntax('aspas sem fechar');
              value = s.slice(i + 1, end); i = end + 1;
            } else value = ident();
            ws();
            if (/[iIsS]/.test(s[i]) && s[i + 1] === ']') { flag = s[i].toLowerCase(); i++; }
          }
          if (s[i] !== ']') throw syntax('] esperado');
          i++;
          c.attrs.push({ name, op, value, ci: flag === 'i' });
          any = true;
        } else if (ch === ':') {
          i++;
          if (s[i] === ':') throw new Error('shim: pseudo-elemento não suportado em "' + src + '"');
          const name = ident().toLowerCase();
          let arg = null;
          if (s[i] === '(') { i++; arg = readParen(); }
          c.pseudos.push(pseudo(name, arg, src));
          any = true;
        } else if (!any && /[\w\-\\ -￿]/.test(ch || '')) { c.tag = ident(); any = true; }
        else break;
      }
      if (!any) throw syntax('seletor vazio na posição ' + i);
      return c;
    }
    function complex() {
      const steps = [];
      let comb = null;
      for (;;) {
        steps.push({ comb, c: compound() });
        const before = i;
        ws();
        if (i >= s.length || s[i] === ',') break;
        if (/[>+~]/.test(s[i])) { comb = s[i]; i++; ws(); }
        else if (i > before) comb = ' ';
        else throw syntax('caractere inesperado "' + s[i] + '"');
      }
      return steps;
    }
    const list = [];
    for (;;) {
      ws();
      list.push(complex());
      ws();
      if (s[i] === ',') { i++; continue; }
      if (i >= s.length) break;
      throw syntax('caractere inesperado "' + s[i] + '"');
    }
    selCache.set(src, list);
    return list;
  }
  function pseudo(name, arg, src) {
    const sub = () => parseSelectorList(arg);
    switch (name) {
      case 'first-child': return { name, test: (el) => !prevEl(el) };
      case 'last-child': return { name, test: (el) => !nextEl(el) };
      case 'only-child': return { name, test: (el) => !prevEl(el) && !nextEl(el) };
      case 'empty': return { name, test: (el) => el._c.length === 0 };
      case 'root': return { name, test: (el) => el === G.document.documentElement };
      case 'scope': return { name, test: (el, scope) => el === scope };
      case 'checked': return { name, test: (el) => !!el.checked || (el.localName === 'option' && !!el.selected) };
      case 'disabled': return { name, test: (el) => !!el.disabled };
      case 'enabled': return { name, test: (el) => !el.disabled };
      case 'hover': case 'active': case 'focus': case 'focus-visible': case 'focus-within': case 'visited': return { name, test: () => false };
      case 'not': { const l = sub(); return { name, test: (el, scope) => !l.some((st) => matchComplex(el, st, st.length - 1, scope)) }; }
      case 'is': case 'where': { const l = sub(); return { name, test: (el, scope) => l.some((st) => matchComplex(el, st, st.length - 1, scope)) }; }
      case 'nth-child': case 'nth-last-child': {
        const a = String(arg).trim().toLowerCase();
        let A = 0, B = 0;
        if (a === 'odd') { A = 2; B = 1; } else if (a === 'even') { A = 2; B = 0; }
        else {
          const m = /^([+-]?\d*)n\s*([+-]\s*\d+)?$/.exec(a);
          if (m) { A = m[1] === '' || m[1] === '+' ? 1 : m[1] === '-' ? -1 : parseInt(m[1], 10); B = m[2] ? parseInt(m[2].replace(/\s/g, ''), 10) : 0; }
          else if (/^[+-]?\d+$/.test(a)) { A = 0; B = parseInt(a, 10); }
          else throw new Error('shim: argumento de :' + name + ' não suportado em "' + src + '"');
        }
        return {
          name,
          test: (el) => {
            const sibs = el.parentNode ? el.parentNode._c.filter((c) => c.nodeType === 1) : [el];
            let idx = sibs.indexOf(el) + 1;
            if (name === 'nth-last-child') idx = sibs.length - idx + 1;
            if (A === 0) return idx === B;
            const n = (idx - B) / A;
            return Number.isInteger(n) && n >= 0;
          },
        };
      }
      default: throw new Error('shim: pseudo-classe ":' + name + '" não suportada em "' + src + '" (adicione em dom_shim.js se for válida no navegador)');
    }
  }
  const prevEl = (el) => { const p = el.parentNode; if (!p) return null; const i = p._c.indexOf(el); for (let k = i - 1; k >= 0; k--) if (p._c[k].nodeType === 1) return p._c[k]; return null; };
  const nextEl = (el) => { const p = el.parentNode; if (!p) return null; const i = p._c.indexOf(el); for (let k = i + 1; k < p._c.length; k++) if (p._c[k].nodeType === 1) return p._c[k]; return null; };

  function matchCompound(el, c, scope) {
    if (c.tag && c.tag !== '*' && el.localName.toLowerCase() !== c.tag.toLowerCase()) return false;
    if (c.id !== null && el.getAttribute('id') !== c.id) return false;
    if (c.classes.length) {
      const have = (el.getAttribute('class') || '').split(/\s+/);
      for (const k of c.classes) if (!have.includes(k)) return false;
    }
    for (const a of c.attrs) {
      let v = el.getAttribute(a.name);
      if (v === null) return false;
      if (a.op === null) continue;
      let want = a.value;
      if (a.ci) { v = v.toLowerCase(); want = want.toLowerCase(); }
      switch (a.op) {
        case '=': if (v !== want) return false; break;
        case '~=': if (!v.split(/\s+/).includes(want)) return false; break;
        case '^=': if (!want || !v.startsWith(want)) return false; break;
        case '$=': if (!want || !v.endsWith(want)) return false; break;
        case '*=': if (!want || !v.includes(want)) return false; break;
        case '|=': if (v !== want && !v.startsWith(want + '-')) return false; break;
        default: return false;
      }
    }
    for (const p of c.pseudos) if (!p.test(el, scope)) return false;
    return true;
  }
  function matchComplex(el, steps, idx, scope) {
    const st = steps[idx];
    if (!matchCompound(el, st.c, scope)) return false;
    if (idx === 0) return true;
    switch (st.comb) {
      case ' ': for (let p = el.parentNode; p && p.nodeType === 1; p = p.parentNode) if (matchComplex(p, steps, idx - 1, scope)) return true; return false;
      case '>': { const p = el.parentNode; return !!p && p.nodeType === 1 && matchComplex(p, steps, idx - 1, scope); }
      case '+': { const p = prevEl(el); return !!p && matchComplex(p, steps, idx - 1, scope); }
      case '~': for (let p = prevEl(el); p; p = prevEl(p)) if (matchComplex(p, steps, idx - 1, scope)) return true; return false;
      default: return false;
    }
  }
  function elementMatches(el, selector, scope) {
    return parseSelectorList(selector).some((st) => matchComplex(el, st, st.length - 1, scope || el));
  }
  function walk(root, fn) {   // percorre descendentes elementos em ordem de documento; fn devolve true para parar
    const stack = [];
    for (let i = root._c.length - 1; i >= 0; i--) stack.push(root._c[i]);
    while (stack.length) {
      const n = stack.pop();
      if (n.nodeType !== 1) continue;
      if (fn(n)) return true;
      for (let i = n._c.length - 1; i >= 0; i--) stack.push(n._c[i]);
    }
    return false;
  }
  function findFirst(root, pred) { let found = null; walk(root, (e) => { if (pred(e)) { found = e; return true; } return false; }); return found; }
  function findAll(root, pred) { const out = []; walk(root, (e) => { if (pred(e)) out.push(e); return false; }); return out; }
  function qsa(root, selector) {
    const list = parseSelectorList(selector);
    return findAll(root, (e) => list.some((st) => matchComplex(e, st, st.length - 1, root)));
  }
  S.qsa = (sel, root) => qsa(root || G.document, sel);

  /* ------------------------------------------------------------------ elementos */
  const rect = () => ({ x: 0, y: 0, left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, toJSON() { return this; } });

  class Element extends Node {
    constructor(tag, ns) {
      super();
      this.nodeType = 1;
      this.namespaceURI = ns || HTML_NS;
      this.localName = this.namespaceURI === HTML_NS ? String(tag).toLowerCase() : String(tag);
      this.tagName = this.namespaceURI === HTML_NS ? this.localName.toUpperCase() : this.localName;
      this.nodeName = this.tagName;
      Object.defineProperty(this, '_attrs', { value: new Map(), enumerable: false });
      this.scrollTop = 0;
      this.scrollLeft = 0;
    }
    _shallowClone() {
      const c = makeElement(this.localName, this.namespaceURI);
      for (const [k, v] of this._attrList()) c.setAttribute(k, v);
      if (this._value !== undefined) c._value = this._value;
      if (this._checked !== undefined) c._checked = this._checked;
      if (this._selected !== undefined) c._selected = this._selected;
      return c;
    }
    _attrList() {
      const out = [];
      for (const [k, v] of this._attrs) if (k !== 'style') out.push([k, v]);
      const st = this.getAttribute('style');
      if (st) out.push(['style', st]);
      return out;
    }
    /* atributos */
    _attrName(n) { return this.namespaceURI === HTML_NS ? String(n).toLowerCase() : String(n); }
    getAttribute(n) {
      n = this._attrName(n);
      if (n === 'style' && this._style) { const t = this._style.cssText; return t === '' && !this._attrs.has('style') ? null : t; }
      return this._attrs.has(n) ? this._attrs.get(n) : null;
    }
    setAttribute(n, v) {
      n = this._attrName(n);
      if (!/^[^\s"'<>\/=]+$/.test(n)) throw new DOMException("Failed to execute 'setAttribute' on 'Element': '" + n + "' is not a valid attribute name.", 'InvalidCharacterError');
      v = String(v);
      this._attrs.set(n, v);
      if (n === 'style') this.style.cssText = v;
    }
    removeAttribute(n) { n = this._attrName(n); this._attrs.delete(n); if (n === 'style' && this._style) this._style.cssText = ''; }
    hasAttribute(n) { return this.getAttribute(n) !== null; }
    toggleAttribute(n, force) { const has = this.hasAttribute(n); const want = force === undefined ? !has : !!force; if (want && !has) this.setAttribute(n, ''); else if (!want && has) this.removeAttribute(n); return want; }
    getAttributeNames() { return this._attrList().map((a) => a[0]); }
    getAttributeNS(ns, n) { return this.getAttribute(n); }
    setAttributeNS(ns, n, v) { this.setAttribute(n, v); }
    removeAttributeNS(ns, n) { this.removeAttribute(n); }
    get attributes() { return this._attrList().map(([name, value]) => ({ name, value, nodeName: name, nodeValue: value })); }
    get id() { return this.getAttribute('id') || ''; }
    set id(v) { this.setAttribute('id', v); }
    get className() { return this.getAttribute('class') || ''; }
    set className(v) { this.setAttribute('class', v); }
    get classList() {
      if (!this._classList) {
        const el = this;
        const toks = () => (el.getAttribute('class') || '').split(/\s+/).filter(Boolean);
        const save = (arr) => el.setAttribute('class', arr.join(' '));
        const chk = (t) => {
          if (t === '' ) throw new DOMException('The token provided must not be empty.', 'SyntaxError');
          if (/\s/.test(t)) throw new DOMException("The token provided ('" + t + "') contains HTML space characters, which are not valid in tokens.", 'InvalidCharacterError');
        };
        Object.defineProperty(this, '_classList', {
          enumerable: false,
          value: {
            add(...t) { const a = toks(); t.forEach((x) => { x = String(x); chk(x); if (!a.includes(x)) a.push(x); }); save(a); },
            remove(...t) { t.forEach((x) => chk(String(x))); save(toks().filter((x) => !t.map(String).includes(x))); },
            toggle(t, force) {
              t = String(t); chk(t);
              const a = toks(); const has = a.includes(t); const want = force === undefined ? !has : !!force;
              if (want && !has) { a.push(t); save(a); } else if (!want && has) save(a.filter((x) => x !== t));
              return want;
            },
            contains(t) { return toks().includes(String(t)); },
            replace(a, b) { const l = toks(); const i = l.indexOf(a); if (i < 0) return false; l[i] = b; save(l); return true; },
            item(i) { return toks()[i] || null; },
            forEach(fn) { toks().forEach(fn); },
            get length() { return toks().length; },
            get value() { return el.getAttribute('class') || ''; },
            toString() { return el.getAttribute('class') || ''; },
            [Symbol.iterator]() { return toks()[Symbol.iterator](); },
          },
        });
      }
      return this._classList;
    }
    get dataset() {
      if (!this._dataset) {
        const el = this;
        const attr = (p) => 'data-' + kebab(String(p));
        Object.defineProperty(this, '_dataset', {
          enumerable: false,
          value: new Proxy({}, {
            get: (t, p) => { if (typeof p === 'symbol') return undefined; const v = el.getAttribute(attr(p)); return v === null ? undefined : v; },
            set: (t, p, v) => { el.setAttribute(attr(p), v); return true; },
            deleteProperty: (t, p) => { el.removeAttribute(attr(p)); return true; },
            has: (t, p) => el.hasAttribute(attr(p)),
            ownKeys: () => el.getAttributeNames().filter((n) => n.startsWith('data-')).map((n) => n.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())),
            getOwnPropertyDescriptor: (t, p) => (typeof p === 'string' && el.hasAttribute(attr(p)) ? { value: el.getAttribute(attr(p)), enumerable: true, configurable: true, writable: true } : undefined),
          }),
        });
      }
      return this._dataset;
    }
    get style() {
      if (!this._style) Object.defineProperty(this, '_style', { value: makeStyle(), enumerable: false, writable: true });
      return this._style;
    }
    set style(v) { this.style.cssText = String(v); }
    /* árvore */
    get children() { return makeCollection(this._c.filter((c) => c.nodeType === 1)); }
    get firstElementChild() { return this._c.find((c) => c.nodeType === 1) || null; }
    get lastElementChild() { for (let i = this._c.length - 1; i >= 0; i--) if (this._c[i].nodeType === 1) return this._c[i]; return null; }
    get childElementCount() { return this._c.filter((c) => c.nodeType === 1).length; }
    get nextElementSibling() { return nextEl(this); }
    get previousElementSibling() { return prevEl(this); }
    get innerText() { return this.textContent; }
    set innerText(v) { this.textContent = v; }
    get innerHTML() { return this._c.map(serialize).join(''); }
    set innerHTML(html) {
      const frag = parseHTML(String(html), this.namespaceURI === SVG_NS);
      if (this.localName === 'template') { this.content._clear(); this.content._insert(frag, null); return; }
      this._clear();
      this._insert(frag, null);
    }
    get outerHTML() { return serialize(this); }
    get content() {
      if (this.localName !== 'template') return undefined;
      if (!this._content) Object.defineProperty(this, '_content', { value: new DocumentFragment(), enumerable: false, writable: true });
      return this._content;
    }
    insertAdjacentHTML(pos, html) {
      const frag = parseHTML(String(html), this.namespaceURI === SVG_NS);
      this.insertAdjacentElement(pos, frag);
    }
    insertAdjacentElement(pos, node) {
      switch (String(pos).toLowerCase()) {
        case 'beforebegin': this.parentNode._insert(node, this); break;
        case 'afterbegin': this._insert(node, this.firstChild); break;
        case 'beforeend': this._insert(node, null); break;
        case 'afterend': this.parentNode._insert(node, this.nextSibling); break;
        default: throw new DOMException("The value provided ('" + pos + "') is not one of 'beforeBegin', 'afterBegin', 'beforeEnd', or 'afterEnd'.", 'SyntaxError');
      }
      return node;
    }
    insertAdjacentText(pos, text) { this.insertAdjacentElement(pos, new Text(text)); }
    /* consultas */
    querySelector(sel) { const list = parseSelectorList(sel); return findFirst(this, (e) => list.some((st) => matchComplex(e, st, st.length - 1, this))); }
    querySelectorAll(sel) { return makeNodeList(qsa(this, sel)); }
    matches(sel) { return elementMatches(this, sel, this); }
    webkitMatchesSelector(sel) { return this.matches(sel); }
    closest(sel) { for (let p = this; p && p.nodeType === 1; p = p.parentNode) if (elementMatches(p, sel, this)) return p; return null; }
    getElementsByTagName(tag) { const t = String(tag).toLowerCase(); return makeCollection(findAll(this, (e) => t === '*' || e.localName.toLowerCase() === t)); }
    getElementsByClassName(cls) { const want = String(cls).split(/\s+/).filter(Boolean); return makeCollection(findAll(this, (e) => { const have = (e.getAttribute('class') || '').split(/\s+/); return want.every((w) => have.includes(w)); })); }
    /* layout e rolagem (valores fixos) */
    getBoundingClientRect() { return rect(); }
    getClientRects() { return [rect()]; }
    get offsetWidth() { return 800; }
    get offsetHeight() { return 600; }
    get offsetLeft() { return 0; }
    get offsetTop() { return 0; }
    get offsetParent() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
    get clientWidth() { return 800; }
    get clientHeight() { return 600; }
    get clientLeft() { return 0; }
    get clientTop() { return 0; }
    get scrollWidth() { return 800; }
    get scrollHeight() { return 600; }
    scrollIntoView() {}
    scrollTo(a, b) { if (typeof a === 'object' && a) { if (a.top !== undefined) this.scrollTop = a.top; if (a.left !== undefined) this.scrollLeft = a.left; } else { if (b !== undefined) this.scrollTop = b; if (a !== undefined) this.scrollLeft = a; } }
    scrollBy() {}
    getBBox() { return { x: 0, y: 0, width: 100, height: 20 }; }
    getTotalLength() { return 100; }
    getPointAtLength() { return { x: 0, y: 0 }; }
    getComputedTextLength() { return Math.max(1, this.textContent.length) * 6; }
    setPointerCapture() {}
    releasePointerCapture() {}
    hasPointerCapture() { return false; }
    animate() { return { cancel() {}, finish() {}, play() {}, pause() {}, finished: Promise.resolve(), onfinish: null }; }
    attachShadow() { throw new Error('shim: shadow DOM não suportado'); }
    /* foco e clique */
    focus() {
      const d = G.document;
      if (d._active === this) return;
      const prev = d._active;
      if (prev && prev !== this) prev.blur();
      d._active = this;
      this.dispatchEvent(new G.FocusEvent('focus', { bubbles: false }));
      this.dispatchEvent(new G.FocusEvent('focusin', { bubbles: true }));
    }
    blur() {
      const d = G.document;
      if (d._active !== this) return;
      d._active = null;
      this.dispatchEvent(new G.FocusEvent('blur', { bubbles: false }));
      this.dispatchEvent(new G.FocusEvent('focusout', { bubbles: true }));
    }
    select() {}
    setSelectionRange() {}
    click() {
      if (this.disabled) return;
      const type = (this.getAttribute('type') || '').toLowerCase();
      const isBox = this.localName === 'input' && (type === 'checkbox' || type === 'radio');
      const before = this.checked;
      if (isBox) this.checked = type === 'radio' ? true : !before;
      const ev = new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 10, clientY: 10, button: 0 });
      this.dispatchEvent(ev);
      if (ev.defaultPrevented) { if (isBox) this.checked = before; return; }
      if (isBox) {
        this.dispatchEvent(new G.InputEvent('input', { bubbles: true }));
        this.dispatchEvent(new G.Event('change', { bubbles: true }));
      }
      const a = this.closest('a[href]');
      if (a) {
        const href = a.getAttribute('href');
        if (href.startsWith('#')) G.location.hash = href;
        else if (!href.startsWith('javascript:')) S.opened.push({ via: 'link', url: href, download: a.getAttribute('download') });
      }
    }
    showModal() { this.setAttribute('open', ''); }
    show() { this.setAttribute('open', ''); }
    close() { this.removeAttribute('open'); }
    requestFullscreen() { return Promise.resolve(); }
    /* controles de formulário */
    get value() {
      switch (this.localName) {
        case 'select': { const o = this._selOpt(); return o ? o.value : ''; }
        case 'option': return this.hasAttribute('value') ? this.getAttribute('value') : this.textContent.replace(/\s+/g, ' ').trim();
        case 'textarea': return this._value !== undefined ? this._value : this.textContent;
        default: return this._value !== undefined ? this._value : (this.getAttribute('value') || '');
      }
    }
    set value(v) {
      const s = v === null || v === undefined ? '' : String(v);
      if (this.localName === 'select') { for (const o of this.options) o._selected = o.value === s; }
      else if (this.localName === 'option') this.setAttribute('value', s);
      else this._value = s;
    }
    get checked() { return this._checked !== undefined ? this._checked : this.hasAttribute('checked'); }
    set checked(v) { this._checked = !!v; }
    get defaultChecked() { return this.hasAttribute('checked'); }
    get selected() { return this._selected !== undefined ? this._selected : this.hasAttribute('selected'); }
    set selected(v) {
      this._selected = !!v;
      const sel = this.parentNode && (this.parentNode.localName === 'select' ? this.parentNode : (this.parentNode.parentNode && this.parentNode.parentNode.localName === 'select' ? this.parentNode.parentNode : null));
      if (v && sel && !sel.multiple) for (const o of sel.options) if (o !== this) o._selected = false;
    }
    get indeterminate() { return !!this._indeterminate; }
    set indeterminate(v) { this._indeterminate = !!v; }
    get options() { return this.localName === 'select' ? makeCollection(findAll(this, (e) => e.localName === 'option')) : undefined; }
    get selectedOptions() { return makeCollection(this.localName === 'select' ? findAll(this, (e) => e.localName === 'option' && e.selected) : []); }
    _selOpt() {
      const opts = findAll(this, (e) => e.localName === 'option');
      const hit = opts.find((o) => o.selected);
      if (hit) return hit;
      return this.multiple ? null : (opts.find((o) => !o.disabled) || null);
    }
    get selectedIndex() { if (this.localName !== 'select') return undefined; const o = this._selOpt(); return o ? findAll(this, (e) => e.localName === 'option').indexOf(o) : -1; }
    set selectedIndex(i) { const opts = findAll(this, (e) => e.localName === 'option'); opts.forEach((o, j) => { o._selected = j === i; }); }
    get type() {
      const t = this.getAttribute('type');
      if (this.localName === 'input') return (t || 'text').toLowerCase();
      if (this.localName === 'button') return (t || 'submit').toLowerCase();
      if (this.localName === 'select') return this.multiple ? 'select-multiple' : 'select-one';
      return t || '';
    }
    set type(v) { this.setAttribute('type', v); }
    get tabIndex() { const t = this.getAttribute('tabindex'); if (t !== null) return parseInt(t, 10) || 0; return ['a', 'button', 'input', 'select', 'textarea'].includes(this.localName) ? 0 : -1; }
    set tabIndex(v) { this.setAttribute('tabindex', v); }
    get form() { return this.closest('form'); }
    get files() { return null; }
    get href() { return this.getAttribute('href') || ''; }
    set href(v) { this.setAttribute('href', v); }
    get htmlFor() { return this.getAttribute('for') || ''; }
    set htmlFor(v) { this.setAttribute('for', v); }
    get readOnly() { return this.hasAttribute('readonly'); }
    set readOnly(v) { this.toggleAttribute('readonly', !!v); }
    get width() { return this._dim('width'); }
    set width(v) { this.setAttribute('width', v); }
    get height() { return this._dim('height'); }
    set height(v) { this.setAttribute('height', v); }
    _dim(n) { const v = this.getAttribute(n); return v === null ? (this.localName === 'canvas' ? (n === 'width' ? 300 : 150) : 0) : (parseFloat(v) || 0); }
    getContext() { return canvasContext(this); }
    toDataURL() { return 'data:image/png;base64,'; }
    toBlob(cb) { cb(new G.Blob([''], { type: 'image/png' })); }
    get viewBox() { return { baseVal: { x: 0, y: 0, width: 800, height: 600 } }; }
  }
  const STR_PROPS = { title: 'title', src: 'src', alt: 'alt', name: 'name', placeholder: 'placeholder', target: 'target', rel: 'rel', download: 'download', role: 'role', lang: 'lang', dir: 'dir', min: 'min', max: 'max', step: 'step', pattern: 'pattern', autocomplete: 'autocomplete', label: 'label', accept: 'accept' };
  Object.keys(STR_PROPS).forEach((p) => Object.defineProperty(Element.prototype, p, { get() { return this.getAttribute(STR_PROPS[p]) || ''; }, set(v) { this.setAttribute(STR_PROPS[p], v); }, configurable: true }));
  ['disabled', 'hidden', 'required', 'multiple', 'open', 'autofocus', 'draggable', 'spellcheck'].forEach((p) => Object.defineProperty(Element.prototype, p, { get() { return this.hasAttribute(p); }, set(v) { this.toggleAttribute(p, !!v); }, configurable: true }));

  function canvasContext() {
    const fns = { measureText: (t) => ({ width: String(t).length * 6 }), createLinearGradient: () => ({ addColorStop() {} }), getImageData: () => ({ data: [] }) };
    return new Proxy({}, {
      get: (t, p) => (p in t ? t[p] : (p in fns ? fns[p] : (typeof p === 'symbol' ? undefined : function () {}))),
      set: (t, p, v) => { t[p] = v; return true; },
    });
  }

  class HTMLElement extends Element {}
  class SVGElement extends Element {}
  class SVGSVGElement extends SVGElement {}
  const subclass = (name, Base) => { const C = class extends Base {}; Object.defineProperty(C, 'name', { value: name }); G[name] = C; return C; };
  const HTMLInputElement = subclass('HTMLInputElement', HTMLElement);
  const HTMLSelectElement = subclass('HTMLSelectElement', HTMLElement);
  const HTMLTextAreaElement = subclass('HTMLTextAreaElement', HTMLElement);
  const HTMLButtonElement = subclass('HTMLButtonElement', HTMLElement);
  const HTMLAnchorElement = subclass('HTMLAnchorElement', HTMLElement);
  const HTMLOptionElement = subclass('HTMLOptionElement', HTMLElement);
  const HTMLTemplateElement = subclass('HTMLTemplateElement', HTMLElement);
  const HTMLCanvasElement = subclass('HTMLCanvasElement', HTMLElement);
  const HTMLFormElement = subclass('HTMLFormElement', HTMLElement);
  const HTMLDivElement = subclass('HTMLDivElement', HTMLElement);
  const HTMLSpanElement = subclass('HTMLSpanElement', HTMLElement);
  Object.assign(G, { Element, HTMLElement, SVGElement, SVGSVGElement });
  const HTML_CLASSES = { input: HTMLInputElement, select: HTMLSelectElement, textarea: HTMLTextAreaElement, button: HTMLButtonElement, a: HTMLAnchorElement, option: HTMLOptionElement, template: HTMLTemplateElement, canvas: HTMLCanvasElement, form: HTMLFormElement, div: HTMLDivElement, span: HTMLSpanElement };

  function makeElement(tag, ns) {
    ns = ns || HTML_NS;
    tag = String(tag);
    if (ns === SVG_NS) return tag === 'svg' ? new SVGSVGElement(tag, ns) : new SVGElement(tag, ns);
    if (ns !== HTML_NS) return new Element(tag, ns);
    const C = HTML_CLASSES[tag.toLowerCase()] || HTMLElement;
    return new C(tag, ns);
  }

  /* ------------------------------------------------------------------ document */
  class Document extends Node {
    constructor() {
      super();
      this.nodeType = 9;
      this.nodeName = '#document';
      this.readyState = 'loading';
      this.cookie = '';
      this.referrer = '';
      this.hidden = false;
      this.visibilityState = 'visible';
      this.characterSet = 'UTF-8';
      this.contentType = 'text/html';
      this.compatMode = 'CSS1Compat';
      this._active = null;
      this._title = '';
      this.fonts = { ready: Promise.resolve(), load() { return Promise.resolve([]); }, check() { return true; } };
    }
    get documentElement() { return this._c.find((c) => c.nodeType === 1) || null; }
    get head() { return this.documentElement.children[0]; }
    get body() { return this.documentElement.children[1]; }
    get defaultView() { return G; }
    get location() { return G.location; }
    get URL() { return G.location.href; }
    get activeElement() { return this._active && this._active.isConnected ? this._active : this.body; }
    get title() { return this._title; }
    set title(v) { this._title = String(v); }
    createElement(tag) { return makeElement(tag, HTML_NS); }
    createElementNS(ns, tag) { return makeElement(tag, ns || HTML_NS); }
    createTextNode(t) { return new Text(t); }
    createComment(t) { return new Comment(t); }
    createDocumentFragment() { return new DocumentFragment(); }
    createEvent(type) { const C = { MouseEvents: MouseEvent, CustomEvent: G.CustomEvent, KeyboardEvent: G.KeyboardEvent }[type] || Event; return new C(''); }
    createRange() {
      return { selectNodeContents() {}, selectNode() {}, setStart() {}, setEnd() {}, collapse() {}, detach() {}, getBoundingClientRect: rect, getClientRects: () => [rect()], cloneContents: () => new DocumentFragment(), createContextualFragment: (h) => parseHTML(String(h), false) };
    }
    importNode(n, deep) { return n.cloneNode(!!deep); }
    adoptNode(n) { return n; }
    getElementById(id) { return findFirst(this, (e) => e.getAttribute('id') === id); }
    querySelector(sel) { const list = parseSelectorList(sel); return findFirst(this, (e) => list.some((st) => matchComplex(e, st, st.length - 1, this))); }
    querySelectorAll(sel) { return makeNodeList(qsa(this, sel)); }
    getElementsByTagName(tag) { const t = String(tag).toLowerCase(); return makeCollection(findAll(this, (e) => t === '*' || e.localName.toLowerCase() === t)); }
    getElementsByClassName(cls) { return this.documentElement.getElementsByClassName(cls); }
    elementFromPoint() { return null; }
    elementsFromPoint() { return []; }
    hasFocus() { return true; }
    execCommand() { return true; }
    get children() { return makeCollection(this._c.filter((c) => c.nodeType === 1)); }
    _shallowClone() { return new Document(); }
  }
  G.Document = Document;
  const document = new Document();
  const html = makeElement('html', HTML_NS);
  html.setAttribute('lang', 'pt-BR');
  html.setAttribute('data-theme', 'light');
  html._insert(makeElement('head', HTML_NS), null);
  const body = makeElement('body', HTML_NS);
  const app = makeElement('div', HTML_NS);
  app.setAttribute('id', 'app');
  body._insert(app, null);
  html._insert(body, null);
  document._insert(html, null);
  G.document = document;
  G.HTMLDocument = Document;

  /* ------------------------------------------------------------------ timers virtuais */
  const timers = new Map();
  let timerSeq = 0, timerOrd = 0;
  function addTimer(fn, delay, args, repeat) {
    if (typeof fn !== 'function') throw new TypeError('shim: setTimeout/setInterval só aceitam função (recebeu ' + typeof fn + ')');
    const id = ++timerSeq;
    const d = Math.max(0, Number(delay) || 0);
    timers.set(id, { id, fn, args, at: S.now + d, ord: ++timerOrd, every: repeat ? Math.max(1, d) : 0 });
    return id;
  }
  G.setTimeout = (fn, d, ...a) => addTimer(fn, d, a, false);
  G.setInterval = (fn, d, ...a) => addTimer(fn, d, a, true);
  G.clearTimeout = G.clearInterval = (id) => { timers.delete(id); };
  G.requestAnimationFrame = (fn) => addTimer(() => fn(S.now), 16, [], false);
  G.cancelAnimationFrame = (id) => { timers.delete(id); };
  G.requestIdleCallback = (fn) => addTimer(() => fn({ didTimeout: false, timeRemaining: () => 50 }), 1, [], false);
  G.cancelIdleCallback = (id) => { timers.delete(id); };
  G.setImmediate = (fn, ...a) => addTimer(fn, 0, a, false);
  /** roda o próximo timer com `at <= limit`; devolve true se rodou algum */
  S.runNext = function (limit) {
    let best = null;
    for (const t of timers.values()) if (t.at <= limit && (best === null || t.at < best.at || (t.at === best.at && t.ord < best.ord))) best = t;
    if (!best) return false;
    if (best.at > S.now) S.now = best.at;
    if (best.every) { best.at = S.now + best.every; best.ord = ++timerOrd; } else timers.delete(best.id);
    try {
      const r = best.fn.apply(G, best.args);
      if (r && typeof r.then === 'function') r.then(null, (e) => reportError(e, 'timer (async)'));
    } catch (e) { reportError(e, 'timer'); }
    return true;
  };
  S.pendingTimers = () => timers.size;
  S.nextTimerAt = () => { let m = null; for (const t of timers.values()) if (m === null || t.at < m) m = t.at; return m; };

  /* ------------------------------------------------------------------ Promise.then: registra exceções dentro de callbacks */
  (function () {
    const orig = Promise.prototype.then;
    const wrap = (fn) => (typeof fn !== 'function' ? fn : function (v) {
      try { return fn.call(this, v); } catch (e) {
        S.soft.push({ phase: S.phase, name: e instanceof Error ? e.name : typeof e, message: e instanceof Error ? e.message : fmtArg(e), stack: e instanceof Error && e.stack ? String(e.stack) : '' });
        throw e;
      }
    });
    Promise.prototype.then = function (a, b) { return orig.call(this, wrap(a), wrap(b)); };
  }());

  /* ------------------------------------------------------------------ URLSearchParams e URL */
  const formEnc = (s) => encodeURIComponent(s).replace(/%20/g, '+').replace(/[!'()~]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase());
  const formDec = (s) => { s = s.replace(/\+/g, ' '); try { return decodeURIComponent(s); } catch (e) { return s; } };
  class URLSearchParams {
    constructor(init) {
      this._l = [];
      if (init instanceof URLSearchParams) this._l = init._l.map((p) => p.slice());
      else if (typeof init === 'string' || init === undefined || init === null) {
        const s = init ? String(init).replace(/^\?/, '') : '';
        if (s) s.split('&').forEach((p) => { if (p === '') return; const i = p.indexOf('='); this._l.push(i < 0 ? [formDec(p), ''] : [formDec(p.slice(0, i)), formDec(p.slice(i + 1))]); });
      } else if (typeof init[Symbol.iterator] === 'function') for (const [k, v] of init) this._l.push([String(k), String(v)]);
      else Object.keys(init).forEach((k) => this._l.push([k, String(init[k])]));
    }
    get size() { return this._l.length; }
    append(k, v) { this._l.push([String(k), String(v)]); }
    delete(k) { this._l = this._l.filter((p) => p[0] !== k); }
    get(k) { const p = this._l.find((x) => x[0] === k); return p ? p[1] : null; }
    getAll(k) { return this._l.filter((x) => x[0] === k).map((x) => x[1]); }
    has(k) { return this._l.some((x) => x[0] === k); }
    set(k, v) { const i = this._l.findIndex((x) => x[0] === k); if (i < 0) this._l.push([String(k), String(v)]); else { this._l[i][1] = String(v); this._l = this._l.filter((x, j) => j <= i || x[0] !== k); } }
    sort() { this._l.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)); }
    forEach(fn, t) { this._l.forEach((p) => fn.call(t, p[1], p[0], this)); }
    keys() { return this._l.map((p) => p[0])[Symbol.iterator](); }
    values() { return this._l.map((p) => p[1])[Symbol.iterator](); }
    entries() { return this._l.map((p) => [p[0], p[1]])[Symbol.iterator](); }
    [Symbol.iterator]() { return this.entries(); }
    toString() { return this._l.map((p) => formEnc(p[0]) + '=' + formEnc(p[1])).join('&'); }
  }
  G.URLSearchParams = URLSearchParams;
  class URL {
    constructor(url, base) {
      const re = /^([a-zA-Z][a-zA-Z0-9+.-]*:)?(?:\/\/([^\/?#]*))?([^?#]*)(\?[^#]*)?(#.*)?$/;
      let m = re.exec(String(url));
      if (m && !m[1] && base !== undefined) {
        const b = new URL(base);
        const path = m[2] !== undefined ? m[3] : (m[3] === '' ? b.pathname : (m[3].startsWith('/') ? m[3] : b.pathname.replace(/[^\/]*$/, '') + m[3]));
        m = [null, b.protocol, m[2] !== undefined ? m[2] : b.host, path, m[2] === undefined && m[3] === '' && m[4] === undefined ? b.search : m[4], m[5]];
      }
      if (!m || !m[1]) throw new TypeError("Failed to construct 'URL': Invalid URL");
      this.protocol = m[1];
      this.host = m[2] || '';
      this.pathname = m[3] || (this.host ? '/' : '');
      this.search = m[4] && m[4] !== '?' ? m[4] : '';
      this.hash = m[5] && m[5] !== '#' ? m[5] : '';
      this.searchParams = new URLSearchParams(this.search);
      this.username = ''; this.password = '';
    }
    get hostname() { return this.host.replace(/:\d+$/, ''); }
    get port() { const m = /:(\d+)$/.exec(this.host); return m ? m[1] : ''; }
    get origin() { return this.protocol + '//' + this.host; }
    get href() { const q = this.searchParams.toString(); return this.protocol + (this.host || this.protocol === 'file:' ? '//' : '') + this.host + this.pathname + (q ? '?' + q : '') + this.hash; }
    toString() { return this.href; }
    toJSON() { return this.href; }
    static createObjectURL(blob) { const u = 'blob:http://localhost/' + (S.blobs.size + 1); S.blobs.set(u, blob); return u; }
    static revokeObjectURL() {}
  }
  G.URL = URL;

  /* ------------------------------------------------------------------ Blob, File, codificação */
  const utf8 = (s) => unescape(encodeURIComponent(s));
  class Blob {
    constructor(parts, opts) {
      this._parts = (parts || []).map((p) => (p instanceof Blob ? p._text() : String(p)));
      this.type = (opts && opts.type) || '';
      this.size = utf8(this._parts.join('')).length;
    }
    _text() { return this._parts.join(''); }
    text() { return Promise.resolve(this._text()); }
    slice(a, b, t) { return new Blob([this._text().slice(a, b)], { type: t || this.type }); }
  }
  class File extends Blob { constructor(parts, name, opts) { super(parts, opts); this.name = name; this.lastModified = Date.now(); } }
  G.Blob = Blob; G.File = File;
  G.TextEncoder = class TextEncoder {
    get encoding() { return 'utf-8'; }
    encode(s) { const b = utf8(String(s === undefined ? '' : s)); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  };
  G.TextDecoder = class TextDecoder {
    get encoding() { return 'utf-8'; }
    decode(u) { if (!u) return ''; let s = ''; const a = new Uint8Array(u.buffer || u); for (let i = 0; i < a.length; i++) s += String.fromCharCode(a[i]); try { return decodeURIComponent(escape(s)); } catch (e) { return s; } }
  };
  const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  G.btoa = (s) => {
    s = String(s); let out = '';
    for (let i = 0; i < s.length; i += 3) {
      const a = s.charCodeAt(i), b = s.charCodeAt(i + 1), c = s.charCodeAt(i + 2);
      if (a > 255 || b > 255 || c > 255) throw new DOMException('The string to be encoded contains characters outside of the Latin1 range.', 'InvalidCharacterError');
      const n = (a << 16) | ((b || 0) << 8) | (c || 0);
      out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63] + (i + 1 < s.length ? B64[(n >> 6) & 63] : '=') + (i + 2 < s.length ? B64[n & 63] : '=');
    }
    return out;
  };
  G.atob = (s) => {
    s = String(s).replace(/[\s=]+$/g, ''); let out = '', bits = 0, val = 0;
    for (const ch of s) { const v = B64.indexOf(ch); if (v < 0) throw new DOMException('The string to be decoded is not correctly encoded.', 'InvalidCharacterError'); val = (val << 6) | v; bits += 6; if (bits >= 8) { bits -= 8; out += String.fromCharCode((val >> bits) & 255); } }
    return out;
  };
  G.structuredClone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
  G.CSS = { escape: (s) => String(s).replace(/[^\w -￿-]/g, (c) => '\\' + c), supports: () => false };

  /* ------------------------------------------------------------------ AbortController */
  class AbortSignal extends EventTarget {
    constructor() { super(); this.aborted = false; this.reason = undefined; }
    throwIfAborted() { if (this.aborted) throw this.reason; }
  }
  class AbortController {
    constructor() { this.signal = new AbortSignal(); }
    abort(reason) {
      if (this.signal.aborted) return;
      this.signal.aborted = true;
      this.signal.reason = reason === undefined ? new DOMException('signal is aborted without reason', 'AbortError') : reason;
      this.signal.dispatchEvent(new Event('abort'));
    }
  }
  G.AbortController = AbortController; G.AbortSignal = AbortSignal;

  /* ------------------------------------------------------------------ fetch (ponte com o Python) */
  const STATUS_TEXT = { 200: 'OK', 400: 'Bad Request', 404: 'Not Found', 500: 'Internal Server Error' };
  class Headers {
    constructor(init) { this._m = new Map(); if (init) Object.keys(init).forEach((k) => this._m.set(k.toLowerCase(), String(init[k]))); }
    get(k) { const v = this._m.get(String(k).toLowerCase()); return v === undefined ? null : v; }
    has(k) { return this._m.has(String(k).toLowerCase()); }
    set(k, v) { this._m.set(String(k).toLowerCase(), String(v)); }
    forEach(fn) { this._m.forEach((v, k) => fn(v, k)); }
  }
  class Response {
    constructor(body, init) {
      init = init || {};
      this._body = body === undefined || body === null ? '' : String(body);
      this.status = init.status === undefined ? 200 : init.status;
      this.ok = this.status >= 200 && this.status < 300;
      this.statusText = init.statusText || STATUS_TEXT[this.status] || '';
      this.headers = new Headers(init.headers || { 'content-type': 'application/json' });
      this.url = init.url || '';
      this.bodyUsed = false;
    }
    json() { this.bodyUsed = true; try { return Promise.resolve(JSON.parse(this._body)); } catch (e) { return Promise.reject(new SyntaxError('Unexpected end of JSON input')); } }
    text() { this.bodyUsed = true; return Promise.resolve(this._body); }
    blob() { return Promise.resolve(new Blob([this._body], { type: this.headers.get('content-type') || '' })); }
    clone() { return new Response(this._body, { status: this.status, url: this.url }); }
  }
  G.Headers = Headers; G.Response = Response;
  G.fetch = function (url, opts) {
    opts = opts || {};
    const signal = opts.signal;
    const abortErr = () => (signal && signal.reason) || new DOMException('The operation was aborted.', 'AbortError');
    return new Promise((resolve, reject) => {
      if (signal && signal.aborted) { reject(abortErr()); return; }
      const u = String(url && url.url ? url.url : url);
      S.fetches.push(u);
      let res;
      try { res = G.__host_fetch(u, String(opts.method || 'GET').toUpperCase()); } catch (e) { res = null; }
      // latência virtual de 1 ms: a resposta chega depois do código que pediu terminar, como no navegador
      addTimer(() => {
        if (signal && signal.aborted) { reject(abortErr()); return; }
        if (!res) { reject(new TypeError('Failed to fetch')); return; }
        resolve(new Response(res[1], { status: res[0], url: u }));
      }, 1, [], false);
    });
  };

  /* ------------------------------------------------------------------ armazenamento */
  class Storage {
    constructor() { Object.defineProperty(this, '_m', { value: new Map(), enumerable: false }); }
    get length() { return this._m.size; }
    key(i) { return Array.from(this._m.keys())[i] || null; }
    getItem(k) { return this._m.has(String(k)) ? this._m.get(String(k)) : null; }
    setItem(k, v) { this._m.set(String(k), String(v)); }
    removeItem(k) { this._m.delete(String(k)); }
    clear() { this._m.clear(); }
  }
  G.Storage = Storage;
  G.localStorage = new Storage();
  G.sessionStorage = new Storage();

  /* ------------------------------------------------------------------ location, history, navigator, window */
  const loc = {
    _hash: (typeof G.__SMOKE_HASH === 'string' && G.__SMOKE_HASH !== '#') ? G.__SMOKE_HASH : '',
    get hash() { return this._hash; },
    set hash(v) {
      let h = String(v);
      if (h !== '' && h[0] !== '#') h = '#' + h;
      if (h === '#') h = '';
      if (h === this._hash) return;
      const old = this.href;
      this._hash = h;
      const neu = this.href;
      addTimer(() => G.dispatchEvent(new G.HashChangeEvent('hashchange', { oldURL: old, newURL: neu })), 0, [], false);
    },
    get href() { return 'http://localhost:8100/' + this._hash; },
    set href(v) { const s = String(v); const i = s.indexOf('#'); if (i >= 0) this.hash = s.slice(i); else S.opened.push({ via: 'location.href', url: s }); },
    get origin() { return 'http://localhost:8100'; },
    protocol: 'http:', host: 'localhost:8100', hostname: 'localhost', port: '8100', pathname: '/', search: '',
    assign(u) { this.href = u; }, replace(u) { this.href = u; }, reload() { S.opened.push({ via: 'reload' }); },
    toString() { return this.href; },
  };
  G.location = loc;
  G.history = {
    state: null, length: 1, scrollRestoration: 'auto',
    replaceState(state, title, url) { this.state = state; if (url !== undefined && url !== null) { const i = String(url).indexOf('#'); if (i >= 0) loc._hash = String(url).slice(i) === '#' ? '' : String(url).slice(i); } },
    pushState(state, title, url) { this.replaceState(state, title, url); },
    back() {}, forward() {}, go() {},
  };
  G.navigator = {
    userAgent: 'Mozilla/5.0 (smoke-test; QuickJS) TracingAppSmoke', language: 'pt-BR', languages: ['pt-BR', 'pt'], platform: 'smoke', onLine: true,
    hardwareConcurrency: 4, maxTouchPoints: 0, cookieEnabled: true,
    clipboard: { writeText(t) { S.clipboard = String(t); return Promise.resolve(); }, readText() { return Promise.resolve(S.clipboard || ''); } },
    sendBeacon() { return true; },
  };
  G.window = G; G.self = G; G.top = G; G.parent = G; G.frames = G;
  G.innerWidth = 1280; G.innerHeight = 800; G.outerWidth = 1280; G.outerHeight = 800;
  G.devicePixelRatio = 1; G.scrollX = 0; G.scrollY = 0; G.pageXOffset = 0; G.pageYOffset = 0;
  G.screen = { width: 1280, height: 800, availWidth: 1280, availHeight: 800, colorDepth: 24 };
  G.isSecureContext = true;
  G.origin = 'http://localhost:8100';
  ['addEventListener', 'removeEventListener', 'dispatchEvent'].forEach((k) => { G[k] = function (...a) { return EventTarget.prototype[k].apply(G, a); }; });
  G.scrollTo = G.scrollBy = G.focus = G.blur = G.print = G.close = G.stop = function () {};
  G.open = function (url) { S.opened.push({ via: 'window.open', url: String(url) }); return null; };
  G.alert = function (m) { S.logs.push({ level: 'alert', phase: S.phase, text: String(m) }); };
  G.confirm = function () { return true; };
  G.prompt = function () { return null; };
  G.getComputedStyle = function (el) { return el.style; };
  G.getSelection = function () { return { rangeCount: 0, isCollapsed: true, toString() { return ''; }, removeAllRanges() {}, addRange() {}, getRangeAt() { return G.document.createRange(); } }; };
  G.matchMedia = function (q) { return { media: String(q), matches: false, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return true; } }; };
  const t0 = Date.now();
  G.performance = { now: () => S.now + (Date.now() - t0) / 1000, mark() {}, measure() {}, getEntriesByType: () => [], getEntriesByName: () => [], timeOrigin: t0, timing: {} };
  G.XMLSerializer = class XMLSerializer { serializeToString(n) { return serialize(n); } };
  G.DOMParser = class DOMParser { parseFromString(str) { const d = new Document(); const h = makeElement('html', HTML_NS); h._insert(makeElement('head', HTML_NS), null); const b = makeElement('body', HTML_NS); b._insert(parseHTML(String(str), false), null); h._insert(b, null); d._insert(h, null); return d; } };
  G.DOMRect = class DOMRect { constructor(x = 0, y = 0, w = 0, h = 0) { Object.assign(this, { x, y, width: w, height: h, left: x, top: y, right: x + w, bottom: y + h }); } };
  G.reportError = (e) => reportError(e, 'reportError');

  /* ------------------------------------------------------------------ observadores */
  G.ResizeObserver = class ResizeObserver {
    constructor(cb) { this._cb = cb; this._t = new Set(); }
    observe(el) {
      this._t.add(el);
      addTimer(() => {
        if (!this._t.has(el)) return;
        this._cb([{ target: el, contentRect: new G.DOMRect(0, 0, 800, 600), borderBoxSize: [{ inlineSize: 800, blockSize: 600 }], contentBoxSize: [{ inlineSize: 800, blockSize: 600 }] }], this);
      }, 0, [], false);
    }
    unobserve(el) { this._t.delete(el); }
    disconnect() { this._t.clear(); }
  };
  G.IntersectionObserver = class IntersectionObserver {
    constructor(cb) { this._cb = cb; this._t = new Set(); }
    observe(el) { this._t.add(el); addTimer(() => { if (this._t.has(el)) this._cb([{ target: el, isIntersecting: true, intersectionRatio: 1, boundingClientRect: rect() }], this); }, 0, [], false); }
    unobserve(el) { this._t.delete(el); }
    disconnect() { this._t.clear(); }
    takeRecords() { return []; }
  };
  G.MutationObserver = class MutationObserver { constructor() {} observe() {} disconnect() {} takeRecords() { return []; } };

  /* ------------------------------------------------------------------ Intl mínimo (o QuickJS não traz) */
  if (typeof G.Intl === 'undefined') {
    G.Intl = {
      NumberFormat: class NumberFormat { constructor(l, o) { this.l = l; this.o = o; } format(n) { return Number(n).toLocaleString(this.l, this.o); } resolvedOptions() { return { locale: 'pt-BR' }; } },
      DateTimeFormat: class DateTimeFormat { constructor(l, o) { this.l = l; this.o = o; } format(d) { return new Date(d === undefined ? Date.now() : d).toLocaleString(); } formatToParts() { return []; } resolvedOptions() { return { locale: 'pt-BR', timeZone: 'UTC' }; } },
      RelativeTimeFormat: class RelativeTimeFormat { format(v, u) { return v + ' ' + u; } },
      PluralRules: class PluralRules { select(n) { return n === 1 ? 'one' : 'other'; } },
      Collator: class Collator { compare(a, b) { return String(a).localeCompare(String(b)); } },
      ListFormat: class ListFormat { format(l) { return Array.from(l).join(', '); } },
    };
  }
}(globalThis));
