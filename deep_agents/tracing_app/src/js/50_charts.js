/* TA.charts: biblioteca de gráficos própria (SVG + um pouco de HTML), sem dependências.
   Cores vêm dos tokens CSS (`var(--c1..c8)`, --text, --muted, --border...), aplicadas por classe/estilo, então
   funcionam nos temas claro e escuro sem recalcular nada; ainda assim todo gráfico se redesenha no evento `theme`.
   Cada função desenha dentro de `el`, é responsiva (ResizeObserver) e devolve `{ update(opts), destroy() }`.
   `update(opts)` mescla `opts` nas opções atuais e redesenha (a série ligada/desligada na legenda é mantida). */
(function () {
  const h = TA.h;
  const S = TA.h.svg;

  /* ------------------------------------------------------------------ utilidades */
  const pad2 = (n) => String(n).padStart(2, '0');
  const r1 = (n) => Math.round(n * 10) / 10;
  function toNum(v) {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  /** x de um ponto: Date | número | ISO | texto numérico -> número (ms em `time`) */
  function toX(v, type) {
    if (v instanceof Date) return v.getTime();
    if (typeof v === 'number') return v;
    if (typeof v === 'string') {
      if (type !== 'time') { const n = Number(v); if (Number.isFinite(n)) return n; }
      const t = Date.parse(v);
      return Number.isNaN(t) ? NaN : t;
    }
    return NaN;
  }
  const defColor = (i) => `var(--c${(i % 8) + 1})`;
  const fmtCompact = (v) => TA.fmt.compact(v);

  /** escala "bonita": limites e ticks redondos (1, 2, 5 x 10^n) */
  function niceNum(range, round) {
    const exp = Math.floor(Math.log10(range));
    const f = range / Math.pow(10, exp);
    let nf;
    if (round) nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
    else nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nf * Math.pow(10, exp);
  }
  function niceScale(min, max, count) {
    count = count || 5;
    if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
    if (max < min) { const t = min; min = max; max = t; }
    if (max === min) { if (max === 0) max = 1; else if (max > 0) { min = Math.min(min, 0); if (min === max) max = min + 1; } else { max = Math.max(max, 0); if (min === max) min = max - 1; } }
    const range = niceNum(max - min, false);
    const step = niceNum(range / Math.max(1, count - 1), true);
    const nmin = Math.floor(min / step + 1e-9) * step;
    const nmax = Math.ceil(max / step - 1e-9) * step;
    const ticks = [];
    for (let v = nmin, i = 0; v <= nmax + step * 1e-6 && i < 40; v += step, i++) ticks.push(parseFloat(v.toPrecision(12)));
    return { min: parseFloat(nmin.toPrecision(12)), max: parseFloat(nmax.toPrecision(12)), ticks, step };
  }

  const T_STEPS = [1e3, 2e3, 5e3, 10e3, 15e3, 30e3, 60e3, 120e3, 300e3, 600e3, 900e3, 1800e3, 3600e3, 7200e3, 10800e3, 21600e3, 43200e3,
    864e5, 2 * 864e5, 7 * 864e5, 14 * 864e5, 30 * 864e5, 90 * 864e5];
  /** ticks de tempo alinhados ao horário local */
  function timeTicks(a, b, target) {
    const span = Math.max(1, b - a);
    const step = T_STEPS.find((s) => span / s <= target) || T_STEPS[T_STEPS.length - 1];
    const ticks = [];
    if (step >= 864e5) {
      const d = new Date(a); d.setHours(0, 0, 0, 0);
      for (let i = 0; i < 400 && d.getTime() <= b + 1; i++) {
        if (d.getTime() >= a - 1) ticks.push(d.getTime());
        d.setDate(d.getDate() + step / 864e5);
      }
    } else {
      const off = -new Date(a).getTimezoneOffset() * 6e4;
      for (let t = Math.floor((a + off) / step) * step - off, i = 0; t <= b + 1 && i < 400; t += step, i++) if (t >= a - 1) ticks.push(t);
    }
    return { ticks, step };
  }
  function fmtTimeTick(ms, step, span) {
    const d = new Date(ms);
    const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
    const dm = `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}`;
    if (step < 6e4) return `${hm}:${pad2(d.getSeconds())}`;
    if (step < 864e5) return span > 864e5 ? `${dm} ${hm}` : hm;
    return dm;
  }
  function fmtTimeFull(ms, step) {
    if (!Number.isFinite(ms)) return '—';
    const iso = new Date(ms).toISOString();
    return step && step >= 864e5 ? TA.fmt.date(iso) : TA.fmt.datetime(iso);
  }

  function emptyBox(text, height) {
    return h('div', { class: 'ch-empty', style: { height: (height || 120) + 'px' } }, text || 'Sem dados no período');
  }
  function hideTip() { if (TA.ui && TA.ui.tipHide) TA.ui.tipHide(); }
  function addTip(el, content) { if (TA.ui && TA.ui.tip) TA.ui.tip(el, content); }
  function swatch(color) { return h('span', { class: 'ch-sw', style: 'background:' + color }); }

  function legendEl(list, st, redraw) {
    return h('div', { class: 'ch-legend' }, list.map((s) => h('button', {
      type: 'button', class: ['ch-leg', st.hidden.has(s.name) && 'off'], title: st.hidden.has(s.name) ? 'Mostrar série' : 'Ocultar série',
      onClick: () => { if (st.hidden.has(s.name)) st.hidden.delete(s.name); else st.hidden.add(s.name); redraw(); },
    }, swatch(s.color), h('span', null, s.name))));
  }

  /** eixo Y: ticks bonitos, rótulos formatados e margem esquerda proporcional ao maior rótulo */
  function yAxis(min, max, fmt, count) {
    const sc = niceScale(min, max, count || 5);
    const labels = sc.ticks.map((t) => (t === 0 ? '0' : String(fmt(t))));
    const longest = labels.reduce((m, l) => Math.max(m, l.length), 1);
    return { min: sc.min, max: sc.max, ticks: sc.ticks, labels, left: Math.max(30, Math.round(longest * 6.4 + 14)) };
  }

  /** casca comum: mede a largura, observa redimensionamento e tema, protege contra exceções */
  function mount(el, opts, render, cfg) {
    const observe = !cfg || cfg.observe !== false;
    TA.util.clear(el);
    const root = h('div', { class: 'ch' });
    el.appendChild(root);
    const st = { hidden: new Set() };
    let cur = Object.assign({}, opts || {});
    let dead = false, lastW = -1, ro = null, offTheme = null, onWin = null;
    const measure = () => {
      let w = el.clientWidth;
      if (!w && el.getBoundingClientRect) w = el.getBoundingClientRect().width;
      return Math.max(160, Math.floor(w || 560));
    };
    function repaint() {
      if (dead) return;
      hideTip();
      try {
        TA.util.clear(root);
        render(root, cur, lastW, st, repaint);
      } catch (e) {
        console.error('[charts]', e);
        TA.util.clear(root);
        root.appendChild(emptyBox('Não foi possível desenhar o gráfico', 80));
      }
    }
    function paint(force) {
      if (dead) return;
      const w = measure();
      if (!force && w === lastW) return;
      lastW = w;
      repaint();
    }
    paint(true);
    if (observe) {
      if (typeof ResizeObserver !== 'undefined') { ro = new ResizeObserver(() => paint(false)); ro.observe(el); }
      else { onWin = () => paint(false); window.addEventListener('resize', onWin); }
    }
    offTheme = TA.bus.on('theme', () => paint(true));
    return {
      update(o) { cur = Object.assign({}, cur, o || {}); paint(true); },
      destroy() {
        dead = true;
        if (ro) ro.disconnect();
        if (onWin) window.removeEventListener('resize', onWin);
        if (offTheme) offTheme();
        hideTip();
        TA.util.clear(root);
        if (root.parentNode) root.parentNode.removeChild(root);
      },
    };
  }

  /* ------------------------------------------------------------------ linhas / áreas */
  function normSeries(list, xType) {
    return (Array.isArray(list) ? list : []).map((s, i) => {
      const raw = Array.isArray(s && s.points) ? s.points : [];
      const pts = [];
      raw.forEach((p) => {
        if (p === null || p === undefined) return;
        const px = Array.isArray(p) ? p[0] : (p.x !== undefined ? p.x : p.t);
        const py = Array.isArray(p) ? p[1] : (p.y !== undefined ? p.y : p.v);
        const x = toX(px, xType);
        if (Number.isFinite(x)) pts.push({ x, y: toNum(py) });
      });
      pts.sort((a, b) => a.x - b.x);
      return { name: (s && s.name) || `Série ${i + 1}`, color: (s && s.color) || defColor(i), pts };
    });
  }

  function segments(pts) {
    const segs = [];
    let cur = null;
    pts.forEach((p) => {
      if (p.y === null) { cur = null; return; }
      if (!cur) { cur = []; segs.push(cur); }
      cur.push(p);
    });
    return segs;
  }

  function renderLine(root, o, w, st, redraw) {
    const height = o.height || 220;
    const xType = o.xType === 'linear' ? 'linear' : 'time';
    const all = normSeries(o.series, xType);
    if (!all.some((s) => s.pts.some((p) => p.y !== null))) { root.appendChild(emptyBox(o.emptyText, height)); return; }
    const vis = all.filter((s) => !st.hidden.has(s.name));
    const stacked = !!o.stacked;
    const fmtY = o.yFormat || fmtCompact;

    // domínio x (sempre sobre todas as séries, para o eixo não "pular" ao ocultar uma)
    const allX = new Set();
    all.forEach((s) => s.pts.forEach((p) => allX.add(p.x)));
    let x0 = Infinity, x1 = -Infinity;
    allX.forEach((x) => { if (x < x0) x0 = x; if (x > x1) x1 = x; });
    if (x0 === x1) { const pad = xType === 'time' ? 30 * 60e3 : 1; x0 -= pad; x1 += pad; }
    const xsVis = [];
    { const set = new Set(); vis.forEach((s) => s.pts.forEach((p) => set.add(p.x))); set.forEach((x) => xsVis.push(x)); xsVis.sort((a, b) => a - b); }

    vis.forEach((s) => { s.map = new Map(); s.pts.forEach((p) => s.map.set(p.x, p.y)); });
    let dmin = Infinity, dmax = -Infinity;
    if (stacked) {
      const cum = new Map(xsVis.map((x) => [x, 0]));
      vis.forEach((s) => {
        s.lo = new Map(); s.hi = new Map();
        xsVis.forEach((x) => { const base = cum.get(x); const v = Math.max(0, s.map.get(x) || 0); s.lo.set(x, base); s.hi.set(x, base + v); cum.set(x, base + v); });
      });
      cum.forEach((v) => { if (v > dmax) dmax = v; });
      dmin = 0;
    } else {
      vis.forEach((s) => s.pts.forEach((p) => { if (p.y !== null) { if (p.y < dmin) dmin = p.y; if (p.y > dmax) dmax = p.y; } }));
    }
    if (!Number.isFinite(dmin)) { dmin = 0; dmax = 1; }
    const yMin = o.yMin !== undefined && o.yMin !== null ? o.yMin : Math.min(0, dmin);
    const ay = yAxis(yMin, Math.max(dmax, yMin), fmtY);

    const m = { t: 8, r: 14, b: 24, l: ay.left };
    const pw = Math.max(40, w - m.l - m.r), ph = Math.max(40, height - m.t - m.b);
    const X = (x) => m.l + ((x - x0) / (x1 - x0)) * pw;
    const Y = (v) => m.t + ph - ((v - ay.min) / (ay.max - ay.min || 1)) * ph;

    const svg = S('svg', { class: 'ch-svg', viewBox: `0 0 ${w} ${height}`, width: w, height, role: 'img', 'font-size': 11 });
    // grade e eixo Y
    ay.ticks.forEach((t, i) => {
      const y = r1(Y(t));
      svg.appendChild(S('line', { class: t === 0 || i === 0 ? 'ch-axis-line' : 'ch-grid', x1: m.l, x2: w - m.r, y1: y, y2: y }));
      svg.appendChild(S('text', { class: 'ch-text', x: m.l - 7, y: y + 4, 'text-anchor': 'end' }, ay.labels[i]));
    });
    // eixo X
    const span = x1 - x0;
    let xt, xStep = 0;
    if (xType === 'time') { const tt = timeTicks(x0, x1, Math.max(2, Math.floor(pw / (span > 864e5 ? 100 : 76)))); xt = tt.ticks; xStep = tt.step; }
    else { const sc = niceScale(x0, x1, Math.max(3, Math.floor(pw / 80))); xt = sc.ticks.filter((t) => t >= x0 && t <= x1); }
    const fmtXAxis = (t) => (o.xFormat ? o.xFormat(t) : xType === 'time' ? fmtTimeTick(t, xStep, span) : fmtCompact(t));
    xt.forEach((t) => {
      const x = r1(X(t));
      svg.appendChild(S('line', { class: 'ch-tick', x1: x, x2: x, y1: m.t + ph, y2: m.t + ph + 4 }));
      svg.appendChild(S('text', { class: 'ch-text', x, y: m.t + ph + 16, 'text-anchor': x > w - 28 ? 'end' : x < m.l + 14 ? 'start' : 'middle' }, fmtXAxis(t)));
    });

    // séries
    const areas = S('g', null), lines = S('g', null), dots = S('g', null);
    vis.forEach((s) => {
      const style = (prop) => `${prop}:${s.color}`;
      if (stacked) {
        const top = xsVis.map((x, i) => `${i ? 'L' : 'M'}${r1(X(x))} ${r1(Y(s.hi.get(x)))}`).join('');
        const bot = xsVis.slice().reverse().map((x) => `L${r1(X(x))} ${r1(Y(s.lo.get(x)))}`).join('');
        if (o.area !== false) areas.appendChild(S('path', { class: 'ch-area stk', d: top + bot + 'Z', style: style('fill') }));
        lines.appendChild(S('path', { class: 'ch-line', d: top, style: style('stroke') }));
        if (xsVis.length === 1) dots.appendChild(S('circle', { class: 'ch-dot', cx: r1(X(xsVis[0])), cy: r1(Y(s.hi.get(xsVis[0]))), r: 3, style: style('fill') }));
        return;
      }
      const segs = segments(s.pts);
      const manyDots = s.pts.length <= 30;
      segs.forEach((seg) => {
        if (seg.length === 1) { dots.appendChild(S('circle', { class: 'ch-dot', cx: r1(X(seg[0].x)), cy: r1(Y(seg[0].y)), r: 3, style: style('fill') })); return; }
        const d = seg.map((p, i) => `${i ? 'L' : 'M'}${r1(X(p.x))} ${r1(Y(p.y))}`).join('');
        if (o.area) {
          const base = r1(Y(Math.max(ay.min, Math.min(0, ay.max))));
          areas.appendChild(S('path', { class: 'ch-area', d: `${d}L${r1(X(seg[seg.length - 1].x))} ${base}L${r1(X(seg[0].x))} ${base}Z`, style: style('fill') }));
        }
        lines.appendChild(S('path', { class: 'ch-line', d, style: style('stroke') }));
        if (manyDots) seg.forEach((p) => dots.appendChild(S('circle', { class: 'ch-dot', cx: r1(X(p.x)), cy: r1(Y(p.y)), r: 2.5, style: style('fill') })));
      });
    });
    svg.appendChild(areas); svg.appendChild(lines); svg.appendChild(dots);

    // hover: crosshair + pontos + tooltip
    if (xsVis.length) {
      const cross = S('line', { class: 'ch-cross', y1: m.t, y2: m.t + ph, style: 'display:none' });
      const hov = S('g', null);
      const overlay = S('rect', { class: ['ch-overlay', o.onPointClick && 'ch-click'], x: m.l, y: m.t, width: pw, height: ph });
      svg.appendChild(cross); svg.appendChild(hov); svg.appendChild(overlay);
      const locate = (e) => {
        const rc = svg.getBoundingClientRect();
        const px = (e.clientX - rc.left) * (rc.width ? w / rc.width : 1);
        let best = -1, bd = Infinity;
        for (let i = 0; i < xsVis.length; i++) { const d = Math.abs(X(xsVis[i]) - px); if (d < bd) { bd = d; best = i; } }
        return best;
      };
      const fmtXTip = (x) => (o.xFormat ? o.xFormat(x) : xType === 'time' ? fmtTimeFull(x, xStep) : TA.fmt.num(x));
      const valueAt = (s, x) => { const v = s.map.get(x); return v === undefined ? null : v; };
      const show = (i) => {
        const x = xsVis[i], cx = r1(X(x));
        cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('style', '');
        TA.util.clear(hov);
        vis.forEach((s) => {
          const v = valueAt(s, x);
          if (v === null) return;
          hov.appendChild(S('circle', { class: 'ch-dot hov', cx, cy: r1(Y(stacked ? s.hi.get(x) : v)), r: 4, style: 'fill:' + s.color }));
        });
      };
      overlay.addEventListener('mousemove', (e) => { const i = locate(e); if (i >= 0) show(i); });
      overlay.addEventListener('mouseleave', () => { cross.setAttribute('style', 'display:none'); TA.util.clear(hov); });
      addTip(overlay, (e) => {
        const i = locate(e);
        if (i < 0) return '';
        const x = xsVis[i];
        let total = 0;
        const rows = vis.map((s) => {
          const v = valueAt(s, x);
          if (v !== null) total += v;
          return h('div', { class: 'ch-tip-r' }, swatch(s.color), h('span', { class: 'ch-tip-n' }, s.name), h('b', null, v === null ? '—' : fmtY(v)));
        });
        return h('div', { class: 'ch-tip' }, h('div', { class: 'ch-tip-h' }, fmtXTip(x)), rows,
          stacked && vis.length > 1 ? h('div', { class: 'ch-tip-r tot' }, h('span', { class: 'ch-tip-n' }, 'Total'), h('b', null, fmtY(total))) : null);
      });
      if (o.onPointClick) {
        overlay.addEventListener('click', (e) => {
          const i = locate(e);
          if (i < 0) return;
          const x = xsVis[i];
          o.onPointClick({ x, index: i, values: vis.map((s) => ({ name: s.name, value: valueAt(s, x), color: s.color })) });
        });
      }
    }
    root.appendChild(svg);
    if (o.legend !== false && all.length > 1) root.appendChild(legendEl(all, st, redraw));
  }

  /* ------------------------------------------------------------------ barras verticais (séries por bucket) */
  function catInfo(c) {
    let t = NaN;
    if (typeof c === 'number' && c > 1e11) t = c;
    else if (typeof c === 'string' && /^\d{4}-\d{2}-\d{2}[T ]/.test(c)) t = Date.parse(c);
    return { raw: c, t, label: c === null || c === undefined ? '—' : String(c) };
  }

  function renderBars(root, o, w, st, redraw) {
    const height = o.height || 220;
    const fmtY = o.yFormat || fmtCompact;
    const cats = (Array.isArray(o.categories) ? o.categories : []).map(catInfo);
    const all = (Array.isArray(o.series) ? o.series : []).map((s, i) => ({
      name: (s && s.name) || `Série ${i + 1}`, color: (s && s.color) || defColor(i),
      values: cats.map((_, j) => { const v = toNum(s && s.values ? s.values[j] : null); return v === null ? 0 : Math.max(0, v); }),
    }));
    const n = cats.length;
    const total = all.reduce((a, s) => a + s.values.reduce((x, y) => x + y, 0), 0);
    if (!n || !all.length || total <= 0) { root.appendChild(emptyBox(o.emptyText, height)); return; }
    const vis = all.filter((s) => !st.hidden.has(s.name));
    const stacked = !!o.stacked;
    const isTime = o.xType !== 'category' && cats.every((c) => Number.isFinite(c.t));
    let step = 0;
    if (isTime && n > 1) { step = Infinity; for (let i = 1; i < n; i++) { const d = cats[i].t - cats[i - 1].t; if (d > 0 && d < step) step = d; } if (!Number.isFinite(step)) step = 0; }
    const span = isTime && n > 1 ? cats[n - 1].t - cats[0].t : 0;
    const labelOf = (c) => (o.xFormat ? o.xFormat(c.raw) : isTime ? fmtTimeTick(c.t, step || 36e5, span) : c.label);
    const titleOf = (c) => (o.xFormat ? o.xFormat(c.raw) : isTime ? fmtTimeFull(c.t, step) : c.label);

    let dmax = 0;
    for (let i = 0; i < n; i++) {
      if (stacked) dmax = Math.max(dmax, vis.reduce((a, s) => a + s.values[i], 0));
      else vis.forEach((s) => { dmax = Math.max(dmax, s.values[i]); });
    }
    const ay = yAxis(0, dmax || 1, fmtY);
    const m = { t: 8, r: 10, b: 24, l: ay.left };
    const pw = Math.max(40, w - m.l - m.r), ph = Math.max(40, height - m.t - m.b);
    const Y = (v) => m.t + ph - (v / (ay.max || 1)) * ph;
    const band = pw / n;
    const inner = band * (band < 6 ? 0.9 : 0.78);
    const k = stacked ? 1 : Math.max(1, vis.length);
    const bw = Math.max(1, inner / k);

    const svg = S('svg', { class: 'ch-svg', viewBox: `0 0 ${w} ${height}`, width: w, height, role: 'img', 'font-size': 11 });
    ay.ticks.forEach((t, i) => {
      const y = r1(Y(t));
      svg.appendChild(S('line', { class: i === 0 ? 'ch-axis-line' : 'ch-grid', x1: m.l, x2: w - m.r, y1: y, y2: y }));
      svg.appendChild(S('text', { class: 'ch-text', x: m.l - 7, y: y + 4, 'text-anchor': 'end' }, ay.labels[i]));
    });
    // rótulos do eixo X (pula alguns se não couberem)
    const labels = cats.map(labelOf);
    const maxLen = labels.reduce((a, l) => Math.max(a, l.length), 1);
    const every = Math.max(1, Math.ceil((maxLen * 6.3 + 12) / band));
    for (let i = 0; i < n; i += every) {
      const cx = r1(m.l + band * i + band / 2);
      svg.appendChild(S('line', { class: 'ch-tick', x1: cx, x2: cx, y1: m.t + ph, y2: m.t + ph + 4 }));
      svg.appendChild(S('text', { class: 'ch-text', x: cx, y: m.t + ph + 16, 'text-anchor': 'middle' }, labels[i]));
    }
    // barras
    const g = S('g', null);
    for (let i = 0; i < n; i++) {
      const bx0 = m.l + band * i + (band - inner) / 2;
      let acc = 0;
      vis.forEach((s, j) => {
        const v = s.values[i];
        if (v <= 0) return;
        const y1 = stacked ? Y(acc + v) : Y(v);
        const hh = (stacked ? Y(acc) : Y(0)) - y1;
        if (stacked) acc += v;
        if (hh <= 0) return;
        g.appendChild(S('rect', { class: 'ch-bar', x: r1(bx0 + (stacked ? 0 : j * bw)), y: r1(y1), width: r1(Math.max(1, bw - (bw > 4 && !stacked && k > 1 ? 1 : 0))), height: r1(Math.max(1, hh)), rx: bw > 6 ? 1.5 : 0, style: 'fill:' + s.color }));
      });
    }
    svg.appendChild(g);
    // alvos de hover/clique, um por categoria
    const segAt = (e, i) => {
      const rc = svg.getBoundingClientRect();
      const sc = rc.width ? w / rc.width : 1;
      const px = (e.clientX - rc.left) * sc, py = (e.clientY - rc.top) * sc;
      if (stacked) { let acc = 0; for (const s of vis) { const v = s.values[i]; if (py <= Y(acc) && py >= Y(acc + v) && v > 0) return s; acc += v; } return null; }
      const j = Math.floor((px - (m.l + band * i + (band - inner) / 2)) / bw);
      return vis[j] || null;
    };
    for (let i = 0; i < n; i++) {
      const hv = S('rect', { class: ['ch-hover', o.onBarClick && 'ch-click'], x: r1(m.l + band * i), y: m.t, width: r1(band), height: ph });
      addTip(hv, () => {
        let tot = 0;
        const rows = vis.map((s) => { tot += s.values[i]; return h('div', { class: 'ch-tip-r' }, swatch(s.color), h('span', { class: 'ch-tip-n' }, s.name), h('b', null, fmtY(s.values[i]))); });
        return h('div', { class: 'ch-tip' }, h('div', { class: 'ch-tip-h' }, titleOf(cats[i])), rows,
          vis.length > 1 ? h('div', { class: 'ch-tip-r tot' }, h('span', { class: 'ch-tip-n' }, 'Total'), h('b', null, fmtY(tot))) : null);
      });
      if (o.onBarClick) {
        hv.addEventListener('click', (e) => {
          const s = segAt(e, i);
          o.onBarClick({ index: i, category: cats[i].raw, label: titleOf(cats[i]), series: s ? s.name : null, values: vis.map((x) => ({ name: x.name, value: x.values[i], color: x.color })) });
        });
      }
      svg.appendChild(hv);
    }
    root.appendChild(svg);
    if (o.legend !== false && all.length > 1) root.appendChild(legendEl(all, st, redraw));
  }

  /* ------------------------------------------------------------------ barras horizontais (HTML: rótulo, barra, valor) */
  function renderHbars(root, o) {
    const items = (Array.isArray(o.items) ? o.items : []).filter((it) => it && toNum(it.value) !== null).map((it) => Object.assign({}, it, { value: toNum(it.value) }));
    if (!items.length) { root.appendChild(emptyBox(o.emptyText, o.emptyHeight || 90)); return; }
    const fmt = o.valueFormat || fmtCompact;
    const max = items.reduce((a, it) => Math.max(a, it.value), 0) || 1;
    const rows = items.map((it, i) => {
      let pct = Math.max(0, (it.value / max) * 100);
      if (it.value > 0 && pct < 1.5) pct = 1.5;
      const color = it.color || o.color || defColor(0);
      const clickable = !!(it.href || it.onClick);
      const kids = [
        h('div', { class: 'ch-hb-head' },
          h('span', { class: 'ch-hb-label', title: String(it.label ?? '') }, String(it.label ?? '—')),
          it.sub ? h('span', { class: 'ch-hb-sub' }, it.sub) : null,
          h('b', { class: 'ch-hb-val num' }, fmt(it.value))),
        h('div', { class: 'ch-hb-track' }, h('div', { class: 'ch-hb-fill', style: { width: pct + '%', background: color } })),
      ];
      let row;
      if (it.href) row = h('a', { class: 'ch-hb-row click', href: it.href }, kids);
      else if (it.onClick) {
        row = h('div', { class: 'ch-hb-row click', role: 'button', tabindex: 0, onClick: () => it.onClick(it), onKeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); it.onClick(it); } } }, kids);
      } else row = h('div', { class: 'ch-hb-row' }, kids);
      addTip(row, `${it.label ?? '—'}\n${fmt(it.value)}${it.sub ? '\n' + it.sub : ''}`);
      return row;
    });
    root.appendChild(h('div', { class: 'ch-hb' }, rows));
  }

  /* ------------------------------------------------------------------ rosca + legenda */
  function renderDonut(root, o) {
    const fmt = o.valueFormat || fmtCompact;
    const items = (Array.isArray(o.items) ? o.items : []).map((it, i) => ({
      label: String(it && it.label !== undefined && it.label !== null ? it.label : '—'), value: toNum(it && it.value), color: (it && it.color) || defColor(i), raw: it,
    })).filter((it) => it.value !== null && it.value > 0);
    const total = items.reduce((a, it) => a + it.value, 0);
    if (!items.length || total <= 0) { root.appendChild(emptyBox(o.emptyText, o.emptyHeight || 140)); return; }
    const size = o.size || 164, thick = o.thickness || 22;
    const c = size / 2, r = (size - thick) / 2, C = 2 * Math.PI * r;
    const svg = S('svg', { class: 'ch-svg ch-donut-svg', viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: 'img' });
    svg.appendChild(S('circle', { class: 'ch-ring', cx: c, cy: c, r, 'stroke-width': thick }));
    const g = S('g', { class: 'ch-slices', transform: `rotate(-90 ${c} ${c})` });
    let off = 0;
    const click = (it) => { if (it.raw && it.raw.onClick) it.raw.onClick(it.raw); else if (o.onSliceClick) o.onSliceClick(it.raw); };
    const clickable = (it) => !!((it.raw && it.raw.onClick) || o.onSliceClick);
    const tipFor = (it) => `${it.label}\n${fmt(it.value)} (${TA.fmt.pct(it.value / total, 1)})`;
    items.forEach((it) => {
      const len = (it.value / total) * C;
      const gap = items.length > 1 ? Math.min(1.5, len * 0.4) : 0;
      const sl = S('circle', {
        class: ['ch-slice', clickable(it) && 'ch-click'], cx: c, cy: c, r, 'stroke-width': thick,
        'stroke-dasharray': `${r1(Math.max(0, len - gap))} ${r1(C - Math.max(0, len - gap))}`, 'stroke-dashoffset': r1(-off), style: 'stroke:' + it.color,
      });
      addTip(sl, tipFor(it));
      if (clickable(it)) sl.addEventListener('click', () => click(it));
      g.appendChild(sl);
      off += len;
    });
    svg.appendChild(g);
    const cv = o.centerValue !== undefined && o.centerValue !== null ? (typeof o.centerValue === 'number' ? fmt(o.centerValue) : o.centerValue) : fmt(total);
    const center = h('div', { class: 'ch-donut-center' }, h('div', { class: 'ch-donut-val num' }, cv), h('div', { class: 'ch-donut-lbl' }, o.centerLabel !== undefined ? o.centerLabel : 'total'));
    const legend = h('div', { class: 'ch-dl' }, items.map((it) => {
      const frac = it.value / total;
      const row = h(clickable(it) ? 'button' : 'div', { class: ['ch-dl-row', clickable(it) && 'click'], type: clickable(it) ? 'button' : null, onClick: clickable(it) ? () => click(it) : null },
        swatch(it.color), h('span', { class: 'ch-dl-name', title: it.label }, it.label), h('b', { class: 'num' }, fmt(it.value)), h('span', { class: 'ch-dl-pct num' }, TA.fmt.pct(frac, frac < 0.1 ? 1 : 0)));
      return row;
    }));
    root.appendChild(h('div', { class: 'ch-donut-wrap' }, h('div', { class: 'ch-donut', style: { width: size + 'px', height: size + 'px' } }, svg, center), legend));
  }

  /* ------------------------------------------------------------------ histograma */
  function renderHist(root, o, w) {
    const height = o.height || 180;
    const fmtX = o.xFormat || fmtCompact;
    const edges = (Array.isArray(o.edges) ? o.edges : []).map(Number);
    const counts = (Array.isArray(o.counts) ? o.counts : []).map((c) => toNum(c) || 0);
    const n = Math.min(counts.length, edges.length - 1);
    if (n <= 0 || edges.slice(0, n + 1).some((e) => !Number.isFinite(e)) || !counts.slice(0, n).some((c) => c > 0)) { root.appendChild(emptyBox(o.emptyText, height)); return; }
    const color = o.color || defColor(0);
    const unit = o.countLabel || 'runs';
    const markers = (Array.isArray(o.markers) ? o.markers : []).filter((mk) => mk && Number.isFinite(Number(mk.x)));
    const ay = yAxis(0, Math.max.apply(null, counts.slice(0, n)) || 1, TA.fmt.compact, 4);
    const m = { t: 8 + (markers.length ? 14 + (markers.length > 1 ? 11 : 0) : 0), r: 12, b: 24, l: ay.left };
    const pw = Math.max(40, w - m.l - m.r), ph = Math.max(40, height - m.t - m.b);
    const Y = (v) => m.t + ph - (v / (ay.max || 1)) * ph;
    const bin = pw / n;
    const binPos = (v) => {   // posição em "unidades de bin" (funciona para bins uniformes ou não)
      if (v <= edges[0]) return 0;
      if (v >= edges[n]) return n;
      for (let i = 0; i < n; i++) if (v < edges[i + 1]) return i + (v - edges[i]) / ((edges[i + 1] - edges[i]) || 1);
      return n;
    };
    const svg = S('svg', { class: 'ch-svg', viewBox: `0 0 ${w} ${height}`, width: w, height, role: 'img', 'font-size': 11 });
    ay.ticks.forEach((t, i) => {
      const y = r1(Y(t));
      svg.appendChild(S('line', { class: i === 0 ? 'ch-axis-line' : 'ch-grid', x1: m.l, x2: w - m.r, y1: y, y2: y }));
      svg.appendChild(S('text', { class: 'ch-text', x: m.l - 7, y: y + 4, 'text-anchor': 'end' }, ay.labels[i]));
    });
    const elabels = [];
    for (let i = 0; i <= n; i++) elabels.push(String(fmtX(edges[i])));
    const every = Math.max(1, Math.ceil((elabels.reduce((a, l) => Math.max(a, l.length), 1) * 6.3 + 14) / bin));
    for (let i = 0; i <= n; i += every) {
      const x = r1(m.l + i * bin);
      svg.appendChild(S('line', { class: 'ch-tick', x1: x, x2: x, y1: m.t + ph, y2: m.t + ph + 4 }));
      svg.appendChild(S('text', { class: 'ch-text', x, y: m.t + ph + 16, 'text-anchor': i === 0 ? 'start' : i === n ? 'end' : 'middle' }, elabels[i]));
    }
    for (let i = 0; i < n; i++) {
      if (counts[i] <= 0) continue;
      svg.appendChild(S('rect', { class: 'ch-bar', x: r1(m.l + i * bin + (bin > 4 ? 0.5 : 0)), y: r1(Y(counts[i])), width: r1(Math.max(1, bin - (bin > 4 ? 1 : 0))), height: r1(Math.max(1, Y(0) - Y(counts[i]))), style: 'fill:' + color }));
    }
    markers.forEach((mk, i) => {
      const x = r1(m.l + binPos(Number(mk.x)) * bin);
      svg.appendChild(S('line', { class: 'ch-marker', x1: x, x2: x, y1: m.t - 4, y2: m.t + ph }));
      svg.appendChild(S('text', { class: 'ch-text ch-marker-t', x: x + (x > w - 70 ? -4 : 4), y: markers.length > 1 ? (i % 2 ? 12 : 23) : 14, 'text-anchor': x > w - 70 ? 'end' : 'start' }, String(mk.label || '')));
    });
    for (let i = 0; i < n; i++) {
      const hv = S('rect', { class: 'ch-hover', x: r1(m.l + i * bin), y: m.t, width: r1(bin), height: ph });
      addTip(hv, () => h('div', { class: 'ch-tip' }, h('div', { class: 'ch-tip-h' }, `${fmtX(edges[i])} – ${fmtX(edges[i + 1])}`),
        h('div', { class: 'ch-tip-r' }, swatch(color), h('span', { class: 'ch-tip-n' }, unit), h('b', null, TA.fmt.num(counts[i])))));
      svg.appendChild(hv);
    }
    root.appendChild(svg);
  }

  /* ------------------------------------------------------------------ API pública */
  TA.charts = {
    /** line(el, {series:[{name,color?,points:[[t,v],...]}], xType:'time'|'linear', yFormat, xFormat, height, area, stacked, yMin, legend, onPointClick({x,index,values})}) */
    line: (el, opts) => mount(el, opts, renderLine),
    /** bars(el, {categories, series:[{name,color?,values}], stacked, yFormat, xFormat, height, legend, onBarClick({index,category,label,series,values})}) */
    bars: (el, opts) => mount(el, opts, renderBars),
    /** hbars(el, {items:[{label,value,color?,sub?,href?,onClick?}], valueFormat, color}) */
    hbars: (el, opts) => mount(el, opts, renderHbars, { observe: false }),
    /** donut(el, {items:[{label,value,color?,onClick?}], centerLabel, centerValue, valueFormat, onSliceClick, size}) */
    donut: (el, opts) => mount(el, opts, renderDonut, { observe: false }),
    /** hist(el, {edges, counts, xFormat, color, markers:[{x,label}], height, countLabel}) */
    hist: (el, opts) => mount(el, opts, renderHist),
    /** utilitários expostos para outras views */
    niceScale, timeTicks,
  };
})();
