/* Utilitários: formatação (TA.fmt), helpers (TA.util), armazenamento local. */

TA.fmt = {
  /** 12345 -> "12.345" */
  num(n) { return n === null || n === undefined || Number.isNaN(n) ? '—' : Number(n).toLocaleString('pt-BR'); },
  /** 12345 -> "12,3 mil" | 1234567 -> "1,2 mi" */
  compact(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    const a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' bi';
    if (a >= 1e6) return (n / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi';
    if (a >= 1e4) return (n / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mil';
    return Number(n).toLocaleString('pt-BR');
  },
  /** segundos -> "850 ms" | "3,2 s" | "1 min 12 s" */
  dur(s) {
    if (s === null || s === undefined || Number.isNaN(s)) return '—';
    if (s < 0.001) return '<1 ms';
    if (s < 1) return Math.round(s * 1000) + ' ms';
    if (s < 60) return s.toLocaleString('pt-BR', { maximumFractionDigits: s < 10 ? 2 : 1 }) + ' s';
    const m = Math.floor(s / 60), r = Math.round(s - m * 60);
    return m < 60 ? `${m} min ${r} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
  },
  cost(c) {
    if (c === null || c === undefined) return '—';
    if (c === 0) return '$0';
    return '$' + (c < 0.01 ? c.toFixed(5) : c < 1 ? c.toFixed(4) : c.toFixed(2));
  },
  pct(x, digits = 1) { return x === null || x === undefined || Number.isNaN(x) ? '—' : (x * 100).toLocaleString('pt-BR', { maximumFractionDigits: digits }) + '%'; },
  bytes(n) {
    if (n === null || n === undefined) return '—';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  },
  date(iso) { return iso ? new Date(iso).toLocaleDateString('pt-BR') : '—'; },
  time(iso) { return iso ? new Date(iso).toLocaleTimeString('pt-BR') : '—'; },
  datetime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR');
  },
  /** "há 5 min" */
  rel(iso) {
    if (!iso) return '—';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 0) return 'agora';
    if (s < 60) return 'há ' + Math.round(s) + ' s';
    if (s < 3600) return 'há ' + Math.round(s / 60) + ' min';
    if (s < 86400) return 'há ' + Math.round(s / 3600) + ' h';
    if (s < 86400 * 30) return 'há ' + Math.round(s / 86400) + ' d';
    return TA.fmt.date(iso);
  },
  /** corta em uma linha */
  trunc(s, n = 120) {
    s = String(s === null || s === undefined ? '' : s).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  },
  /** id curto (8 primeiros caracteres) */
  short(id, n = 8) { return id ? String(id).slice(0, n) : '—'; },
};

TA.util = {
  debounce(fn, ms = 250) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; },
  clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; },
  clamp(x, a, b) { return Math.max(a, Math.min(b, x)); },
  sum(arr, f) { return arr.reduce((s, x) => s + (f ? f(x) : x) || 0, 0); },
  /** cor estável (var CSS de série) para uma string: agente, modelo, ferramenta... */
  colorFor(key) {
    let h = 0;
    const s = String(key);
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return `var(--c${(h % 8) + 1})`;
  },
  /** query string a partir de um objeto (ignora null/''/undefined) */
  qs(obj) {
    const p = new URLSearchParams();
    Object.entries(obj || {}).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '') p.set(k, v); });
    const s = p.toString();
    return s ? '?' + s : '';
  },
  copy(text) {
    const done = () => TA.ui.toast('Copiado');
    if (navigator.clipboard && window.isSecureContext !== false) {
      navigator.clipboard.writeText(text).then(done, () => TA.util._copyFallback(text, done));
    } else TA.util._copyFallback(text, done);
  },
  _copyFallback(text, done) {
    const ta = TA.h('textarea', { style: 'position:fixed;opacity:0' }, text);
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { TA.ui.toast('Não consegui copiar', 'err'); }
    ta.remove();
  },
  /** JSON legível (para copiar/exibir) */
  pretty(v) { try { return typeof v === 'string' ? v : JSON.stringify(v, null, 2); } catch (e) { return String(v); } },
  store: {
    get(k, d) { try { const v = localStorage.getItem('ta.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('ta.' + k, JSON.stringify(v)); } catch (e) { /* sem armazenamento */ } },
  },
  /** cores/rótulos do status de um run/span */
  statusKind(status) {
    return { completed: 'ok', error: 'err', cancelled: 'warn', running: 'info', unfinished: 'warn' }[status] || '';
  },
  statusLabel(status) {
    return { completed: 'Concluído', error: 'Erro', cancelled: 'Cancelado', running: 'Em andamento', unfinished: 'Incompleto' }[status] || status || '—';
  },
  /** intervalo de tempo (chave) -> ISO inicial (ou null para "tudo") */
  sinceOf(key) {
    const h = { '1h': 1, '24h': 24, '7d': 168, '30d': 720 }[key];
    return h ? new Date(Date.now() - h * 3600e3).toISOString() : null;
  },
};
