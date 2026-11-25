/* Driver do smoke: funções chamadas pelo runner Python (smoke/runner.py) sobre o DOM falso. Carregado DEPOIS do app. */
(function (G) {
  'use strict';
  const S = G.__smoke;

  const pathOf = (hash) => String(hash || '').replace(/^#\/?/, '').split('?')[0];
  S.path = () => pathOf(G.location.hash);
  S.visit = (hash) => { G.location.hash = hash; };

  /** simula o fim do carregamento da página (o boot do app espera o DOMContentLoaded) */
  S.load = function () {
    G.document.readyState = 'interactive';
    G.document.dispatchEvent(new G.Event('DOMContentLoaded', { bubbles: true }));
    G.document.readyState = 'complete';
    G.dispatchEvent(new G.Event('load'));
  };

  /** devolve (e limpa) tudo que foi capturado desde a última chamada */
  S.takeErrors = function () {
    const out = { errors: S.errors, soft: S.soft, warnings: S.warnings };
    S.errors = []; S.soft = []; S.warnings = [];
    return JSON.stringify(out);
  };
  S.setPhase = (p) => { S.phase = p; };

  const viewEl = () => G.document.getElementById('view');
  const squash = (s) => String(s).replace(/\s+/g, ' ').trim();

  /** estado visível da tela, para as verificações do runner */
  S.state = function () {
    const view = viewEl();
    const text = view ? view.textContent : '';
    const sus = [];
    const re = /\bNaN\b|\bundefined\b|\[object Object\]|Invalid Date|\bInfinity\b/g;
    let m;
    while ((m = re.exec(text)) !== null && sus.length < 4) {
      const ctx = squash(text.slice(Math.max(0, m.index - 30), m.index + m[0].length + 30));
      if (!sus.includes(ctx)) sus.push(ctx);
    }
    const body = G.document.body.textContent;
    return {
      hash: G.location.hash,
      hasView: !!view,
      viewChars: squash(text).length,
      head: squash(text).slice(0, 140),
      errboxes: S.qsa('.errbox', view || G.document).map((e) => squash(e.textContent).slice(0, 300)),
      loading: view ? S.qsa('.loading, .spinner', view).length : 0,
      construction: !!view && view.children.length === 1 && /Em construção/.test(view.textContent),
      notFound: !!view && /Página não encontrada/.test(text),
      missingModule: /ainda não (foi )?carregad[oa]/i.test(text) ? squash(text.match(/[^.]{0,60}ainda não (foi )?carregad[oa][^.]{0,40}/i)[0]) : '',
      suspicious: sus,
      theme: G.document.documentElement.getAttribute('data-theme'),
      bodyChars: body.length,
    };
  };
  S.hasText = (s) => G.document.body.textContent.includes(s);
  S.quick = () => {
    const view = viewEl();
    return JSON.stringify({ path: S.path(), errboxes: S.qsa('.errbox', view || G.document).map((e) => squash(e.textContent).slice(0, 300)), notFound: !!view && /Página não encontrada/.test(view.textContent) });
  };

  /* ------------------------------------------------------------------ ações de interação */
  S.done = new Set();
  let pending = null;

  const hiddenUp = (el, root) => { for (let p = el; p && p !== root; p = p.parentNode) if (p.classList && p.classList.contains('hidden')) return true; return false; };
  const label = (el) => {
    const t = squash(el.textContent).slice(0, 28) || el.getAttribute('title') || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    const cls = (el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    return el.localName + (cls ? '.' + cls : '') + (t ? ' "' + t + '"' : '');
  };

  function collect(root) {
    const out = [];
    const seen = new Map();
    const groups = new Map();
    const stack = [];
    for (let i = root._c.length - 1; i >= 0; i--) stack.push(root._c[i]);
    while (stack.length) {
      const el = stack.pop();
      if (el.nodeType !== 1) continue;
      for (let i = el._c.length - 1; i >= 0; i--) stack.push(el._c[i]);
      if (el.disabled || hiddenUp(el, root)) continue;
      const ln = el.localName;
      let kind = null;
      if (ln === 'select') kind = 'select';
      else if (ln === 'textarea') kind = 'type';
      else if (ln === 'input') { const t = el.type; kind = t === 'checkbox' || t === 'radio' ? 'click' : (t === 'text' || t === 'search' ? 'type' : null); }
      else if (ln === 'a') kind = (el.getAttribute('href') || '').startsWith('#') ? 'link' : null;
      else if (ln === 'button' || ln === 'summary' || ['button', 'tab'].includes(el.getAttribute('role')) || S.clickables.has(el)) kind = 'click';
      if (!kind) continue;
      const cls = el.getAttribute('class') || '';
      const gkey = kind + '|' + ln + '|' + cls;
      const tabLike = /\btab\b|\bseg\b/.test(cls) || !!el.closest('.seg, .tabs');
      const cap = kind === 'link' ? 2 : (tabLike ? 12 : 6);
      const used = groups.get(gkey) || 0;
      if (used >= cap) continue;
      const prefix = gkey + '|' + squash(el.textContent).slice(0, 40);
      const n = seen.get(prefix) || 0;
      seen.set(prefix, n + 1);
      const sig = prefix + '|' + n;
      if (S.done.has(sig)) continue;
      groups.set(gkey, used + 1);
      out.push({ sig, kind, el });
    }
    return out;
  }

  /** escolhe a próxima ação ainda não feita (sem executar); devolve {desc} ou null */
  S.nextAction = function () {
    const view = viewEl();
    pending = null;
    if (!view) return null;
    const c = collect(view)[0];
    if (!c) return null;
    S.done.add(c.sig);
    pending = c;
    return { desc: (c.kind === 'type' ? 'digitar em ' : c.kind === 'select' ? 'trocar ' : c.kind === 'link' ? 'seguir link ' : 'clicar em ') + label(c.el) };
  };
  S.perform = function () {
    const c = pending; pending = null;
    if (!c) return false;
    const el = c.el;
    if (c.kind === 'select') {
      const opts = Array.from(el.options);
      if (opts.length < 2) return true;
      const cur = el.value;
      const target = opts.find((o, i) => i > 0 && o.value !== cur) || opts[0];
      el.value = target.value;
      el.dispatchEvent(new G.Event('input', { bubbles: true }));
      el.dispatchEvent(new G.Event('change', { bubbles: true }));
    } else if (c.kind === 'type') {
      el.focus();
      el.value = 'a';
      el.dispatchEvent(new G.InputEvent('input', { bubbles: true, data: 'a', inputType: 'insertText' }));
      el.dispatchEvent(new G.KeyboardEvent('keyup', { bubbles: true, key: 'a' }));
      el.dispatchEvent(new G.Event('change', { bubbles: true }));
      el.blur();
    } else el.click();
    return true;
  };

  /** passa o mouse sobre os elementos que registraram listeners de hover (tooltips, destaques) */
  S.hover = function (limit) {
    let n = 0;
    const view = viewEl();
    for (const el of Array.from(S.hoverables)) {
      if (n >= limit) break;
      if (!el.isConnected || (view && !view.contains(el))) { if (!el.isConnected) S.hoverables.delete(el); continue; }
      const init = { clientX: 100, clientY: 100, bubbles: true };
      el.dispatchEvent(new G.MouseEvent('mouseenter', { clientX: 100, clientY: 100 }));
      el.dispatchEvent(new G.MouseEvent('mouseover', init));
      el.dispatchEvent(new G.MouseEvent('mousemove', init));
      el.dispatchEvent(new G.MouseEvent('mouseleave', { clientX: 100, clientY: 100 }));
      el.dispatchEvent(new G.MouseEvent('mouseout', init));
      n++;
    }
    return n;
  };
  S.keys = function () {
    ['Escape', '/', 'ArrowDown'].forEach((key) => G.document.dispatchEvent(new G.KeyboardEvent('keydown', { key, bubbles: true })));
    return 3;
  };
  S.resize = function (w) {
    G.innerWidth = w;
    G.dispatchEvent(new G.Event('resize'));
    return w;
  };

  /** ações globais do shell: tema, atualizar, intervalo de tempo */
  S.globalAction = function (name) {
    const q = (sel) => G.document.querySelector(sel);
    if (name === 'theme') {
      const b = q('button[title="Alternar tema"]');
      if (!b) return 'botão de tema ausente';
      b.click();
      return G.document.documentElement.getAttribute('data-theme');
    }
    if (name === 'refresh') {
      const b = q('button[title="Atualizar"]');
      if (!b) return 'botão atualizar ausente';
      b.click();
      G.TA.bus.emit('refresh', { reason: 'smoke' });
      return 'ok';
    }
    if (name === 'range' || name === 'range-restore') {
      const s = q('.topbar select');
      if (!s) return 'seletor de intervalo ausente';
      s.value = name === 'range' ? '7d' : 'all';
      s.dispatchEvent(new G.Event('change', { bubbles: true }));
      return s.value;
    }
    return 'ação desconhecida';
  };
}(globalThis));
