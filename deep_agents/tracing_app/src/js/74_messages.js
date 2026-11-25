/* Markdown seguro e lista de mensagens estilo chat/LangSmith.
   Expõe: TA.ui.markdown(text), TA.ui.messages(messages, opts), TA.ui.messageStats(messages), TA.ui.messageText(msg),
          TA.ui.searchResults(textOuObjeto), TA.ui.parseSearchResults(texto), TA.ui.tryJson(texto), TA.ui.estimateTokens(chars).
   Nada aqui usa innerHTML com dados: tudo vira nós DOM (texto sempre como nó de texto). */
(function () {
  const h = TA.h;
  const CLIP_CHARS = 1200;      // acima disso a mensagem fica "colapsada" com "mostrar tudo"
  const BIG_CHARS = 40000;      // acima disso o markdown só é montado depois de "mostrar tudo"
  const MD_MAX = 300000;        // teto de caracteres convertidos de uma vez

  const estimateTokens = (chars) => Math.max(0, Math.round((chars || 0) / 4));
  TA.ui.estimateTokens = estimateTokens;

  /* ================================================================== markdown: inline */
  const INLINE = [
    { type: 'code', re: /`([^`\n]+)`/g },
    { type: 'link', re: /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g },
    { type: 'bold', re: /\*\*([^\n]+?)\*\*/g },
    { type: 'strike', re: /~~([^\n]+?)~~/g },
    { type: 'italic', re: /\*([^\s*][^*\n]*?)\*/g },
    { type: 'url', re: /https?:\/\/[^\s<>"'`\])]+/g },
  ];

  function extLink(href, kids) {
    return h('a', { href, target: '_blank', rel: 'noopener noreferrer', class: 'ms-link' }, kids);
  }

  /** texto com marcações inline -> array de nós/strings */
  function inline(text, depth) {
    depth = depth || 0;
    const out = [];
    let pos = 0;
    const cache = INLINE.map(() => undefined);
    function find(i) {
      let m = cache[i];
      if (m === null) return null;
      if (m === undefined || m.index < pos) {
        INLINE[i].re.lastIndex = pos;
        m = INLINE[i].re.exec(text);
        cache[i] = m;
      }
      return m;
    }
    while (pos < text.length) {
      let best = null, bi = -1;
      for (let i = 0; i < INLINE.length; i++) {
        if (depth > 3 && INLINE[i].type !== 'code') continue;
        const m = find(i);
        if (m && (best === null || m.index < best.index)) { best = m; bi = i; }
      }
      if (!best) break;
      if (best.index > pos) out.push(text.slice(pos, best.index));
      const type = INLINE[bi].type;
      if (type === 'url') {
        const url = best[0].replace(/[.,;:!?]+$/, '');
        pos = best.index + url.length;
        out.push(extLink(url, url));
        continue;
      }
      pos = best.index + best[0].length;
      if (type === 'code') out.push(h('code', { class: 'ms-icode' }, best[1]));
      else if (type === 'link') out.push(extLink(best[2], best[1]));
      else if (type === 'bold') out.push(h('strong', null, inline(best[1], depth + 1)));
      else if (type === 'strike') out.push(h('del', null, inline(best[1], depth + 1)));
      else out.push(h('em', null, inline(best[1], depth + 1)));
    }
    if (pos < text.length) out.push(text.slice(pos));
    return out;
  }

  /* ================================================================== markdown: blocos */
  const RE_FENCE = /^\s*(```+|~~~+)\s*(.*)$/;
  const RE_HEAD = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const RE_HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
  const RE_QUOTE = /^\s{0,3}>\s?(.*)$/;
  const RE_UL = /^(\s*)([-*+])\s+(.*)$/;
  const RE_OL = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
  const RE_TSEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

  function codeBlock(text, lang) {
    return h('div', { class: 'ms-codeblock' },
      h('div', { class: 'ms-codehead' }, h('span', { class: 'ms-codelang' }, lang || 'texto'), h('span', { class: 'spacer' }), TA.ui.copyBtn(text)),
      h('pre', null, h('code', null, text)));
  }

  function splitRow(line) {
    let s = line.trim().replace(/\\\|/g, '\u0001');
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|')) s = s.slice(0, -1);
    return s.split('|').map((c) => c.replace(/\u0001/g, '|').trim());
  }

  function isBlockStart(line, next) {
    return RE_FENCE.test(line) || RE_HEAD.test(line) || RE_HR.test(line) || RE_QUOTE.test(line) || RE_UL.test(line) || RE_OL.test(line)
      || (line.includes('|') && next !== undefined && next.includes('|') && RE_TSEP.test(next));
  }

  function parseList(lines, i, depth) {
    const first = RE_UL.exec(lines[i]) || RE_OL.exec(lines[i]);
    const ordered = !RE_UL.test(lines[i]);
    const base = first[1].length;
    const startNum = ordered ? parseInt(first[2], 10) : null;
    const items = [];
    let j = i;
    const match = (l) => RE_UL.exec(l) || RE_OL.exec(l);
    while (j < lines.length) {
      const line = lines[j];
      if (!line.trim()) {
        let k = j + 1;
        while (k < lines.length && !lines[k].trim()) k++;
        if (k >= lines.length) break;
        const mk = match(lines[k]);
        const ind = lines[k].match(/^\s*/)[0].length;
        if (mk && ind < base + 2 && ind >= base && (!RE_UL.test(lines[k])) === ordered) { j = k; continue; }
        if (ind >= base + 2 && items.length) { items[items.length - 1].lines.push(''); j++; continue; }
        break;
      }
      const m = match(line);
      const ind = line.match(/^\s*/)[0].length;
      if (m && ind < base + 2) {
        if (ind < base) break;
        if ((!RE_UL.test(line)) !== ordered) break;
        items.push({ lines: [m[3]] });
        j++;
        continue;
      }
      if (!items.length) break;
      const cur = items[items.length - 1];
      if (ind >= base + 2) { cur.lines.push(line.slice(Math.min(ind, base + 2))); j++; continue; }
      const prev = lines[j - 1];
      if (prev && prev.trim() && !isBlockStart(line, lines[j + 1])) { cur.lines.push(line.trim()); j++; continue; }
      break;
    }
    const list = h(ordered ? 'ol' : 'ul', { class: 'ms-list-md', start: ordered && startNum !== 1 ? startNum : null });
    items.forEach((it) => {
      let first1 = it.lines[0];
      let prefix = null;
      const t = /^\[( |x|X)\]\s+/.exec(first1);
      if (t) { prefix = h('span', { class: 'ms-task' }, t[1] === ' ' ? '☐' : '☑'); first1 = first1.slice(t[0].length); }
      const kids = parseBlocks([first1].concat(it.lines.slice(1)), depth + 1);
      const li = h('li', null, prefix);
      // item "enxuto": o primeiro parágrafo vira o texto do próprio <li> (o marcador de tarefa fica na mesma linha)
      const firstP = kids[0];
      if (firstP && firstP.getAttribute && firstP.getAttribute('class') === 'ms-p') {
        while (firstP.firstChild) li.appendChild(firstP.firstChild);
        kids.slice(1).forEach((k) => li.appendChild(k));
      } else kids.forEach((k) => li.appendChild(k));
      list.appendChild(li);
    });
    return { node: list, next: j };
  }

  function parseBlocks(lines, depth) {
    const out = [];
    let i = 0;
    if (depth > 8) { out.push(h('p', null, lines.join('\n'))); return out; }
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      let m = RE_FENCE.exec(line);
      if (m) {
        const fence = m[1];
        const lang = (m[2] || '').trim().split(/\s+/)[0] || '';
        const buf = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith(fence)) { buf.push(lines[i]); i++; }
        i++;
        out.push(codeBlock(buf.join('\n'), lang));
        continue;
      }
      m = RE_HEAD.exec(line);
      if (m) { out.push(h('h' + m[1].length, { class: 'ms-h ms-h' + m[1].length }, inline(m[2]))); i++; continue; }
      if (RE_HR.test(line)) { out.push(h('hr', { class: 'ms-hr' })); i++; continue; }
      if (RE_QUOTE.test(line)) {
        const buf = [];
        while (i < lines.length && RE_QUOTE.test(lines[i])) { buf.push(RE_QUOTE.exec(lines[i])[1]); i++; }
        out.push(h('blockquote', { class: 'ms-quote' }, parseBlocks(buf, depth + 1)));
        continue;
      }
      if (line.includes('|') && i + 1 < lines.length && lines[i + 1].includes('|') && RE_TSEP.test(lines[i + 1])) {
        const head = splitRow(line);
        const aligns = splitRow(lines[i + 1]).map((c) => (/^:-+:$/.test(c) ? 'center' : /-:$/.test(c) ? 'right' : null));
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) { rows.push(splitRow(lines[i])); i++; }
        const cell = (tag, c, idx) => h(tag, { style: aligns[idx] ? { textAlign: aligns[idx] } : null }, inline(c));
        out.push(h('div', { class: 'ms-table-wrap' }, h('table', { class: 'ms-table' },
          h('thead', null, h('tr', null, head.map((c, idx) => cell('th', c, idx)))),
          h('tbody', null, rows.map((r) => h('tr', null, head.map((_, idx) => cell('td', r[idx] === undefined ? '' : r[idx], idx))))))));
        continue;
      }
      if (RE_UL.test(line) || RE_OL.test(line)) {
        const r = parseList(lines, i, depth);
        out.push(r.node);
        i = Math.max(r.next, i + 1);
        continue;
      }
      // parágrafo: junta linhas até uma linha em branco ou o começo de outro bloco
      const buf = [line];
      i++;
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], lines[i + 1])) { buf.push(lines[i]); i++; }
      const kids = [];
      buf.forEach((l, idx) => { if (idx) kids.push(h('br')); kids.push(inline(l.trim())); });
      out.push(h('p', { class: 'ms-p' }, kids));
    }
    return out;
  }

  /** markdown seguro -> Node (div.ms-md). Só links http(s); nada de HTML cru. */
  TA.ui.markdown = function markdown(text) {
    let s = text === null || text === undefined ? '' : (typeof text === 'string' ? text : TA.util.pretty(text));
    const root = h('div', { class: 'ms-md' });
    let cut = false;
    if (s.length > MD_MAX) { s = s.slice(0, MD_MAX); cut = true; }
    try {
      parseBlocks(s.replace(/\r\n?/g, '\n').split('\n'), 0).forEach((n) => root.appendChild(n));
    } catch (e) {
      TA.util.clear(root);
      root.appendChild(h('pre', { class: 'ms-pre' }, s));
    }
    if (cut) root.appendChild(h('div', { class: 'ms-cut' }, 'Texto cortado para exibição (use "Texto" ou copie para ver tudo).'));
    return root;
  };

  /* ================================================================== utilitários de mensagem */
  function tryJson(text) {
    if (typeof text !== 'string') return undefined;
    const t = text.trim();
    if (t.length < 2 || t.length > 3e6 || (t[0] !== '{' && t[0] !== '[')) return undefined;
    try { return JSON.parse(t); } catch (e) { return undefined; }
  }
  TA.ui.tryJson = tryJson;

  function parseMaybe(s) {
    if (typeof s !== 'string') return s === undefined ? {} : s;
    try { return JSON.parse(s); } catch (e) { return s; }
  }

  function roleOf(m) {
    const t = String((m && (m.type || m.role)) || '').toLowerCase();
    if (t.includes('system')) return 'system';
    if (t.includes('human') || t === 'user') return 'human';
    if (t === 'ai' || t.includes('assistant') || t.startsWith('aimessage')) return 'ai';
    if (t.includes('tool') || t === 'function') return 'tool';
    return 'other';
  }

  const ROLE = {
    system: { label: 'Sistema', icon: 'layers' },
    human: { label: 'Usuário', icon: 'user' },
    ai: { label: 'Assistente', icon: 'bot' },
    tool: { label: 'Tool', icon: 'tool' },
    other: { label: 'Mensagem', icon: 'chat' },
  };

  /** conteúdo da mensagem -> { text, reasoning[], other[], blockCalls[] } */
  function splitContent(m) {
    const res = { text: '', reasoning: [], other: [], blockCalls: [] };
    const c = m ? m.content : null;
    if (c === null || c === undefined) return res;
    if (typeof c === 'string') { res.text = c; return res; }
    if (!Array.isArray(c)) { res.other.push({ label: 'conteúdo', value: c }); return res; }
    const texts = [];
    c.forEach((b) => {
      if (b === null || b === undefined) return;
      if (typeof b === 'string') { texts.push(b); return; }
      const t = b.type;
      if (t === 'text' || t === 'output_text' || t === 'input_text') texts.push(b.text || '');
      else if (t === 'thinking') res.reasoning.push({ text: b.thinking || '', encrypted: false });
      else if (t === 'redacted_thinking') res.reasoning.push({ text: '', encrypted: true, size: (b.data || '').length });
      else if (t === 'reasoning') {
        const parts = [];
        (Array.isArray(b.summary) ? b.summary : []).forEach((s) => parts.push(typeof s === 'string' ? s : (s && s.text) || ''));
        (Array.isArray(b.content) ? b.content : []).forEach((s) => parts.push(typeof s === 'string' ? s : (s && s.text) || ''));
        res.reasoning.push({ text: parts.filter(Boolean).join('\n\n'), encrypted: !!b.encrypted_content, size: (b.encrypted_content || '').length });
      } else if (t === 'tool_use' || t === 'server_tool_use') res.blockCalls.push({ id: b.id || null, name: b.name || '', args: b.input === undefined ? {} : b.input });
      else if (t === 'function_call' || t === 'tool_call') res.blockCalls.push({ id: b.call_id || b.id || null, name: b.name || '', args: parseMaybe(b.arguments !== undefined ? b.arguments : b.args) });
      else if (t === 'image' || t === 'image_url' || t === 'input_image') {
        const url = typeof b.image_url === 'string' ? b.image_url : (b.image_url && b.image_url.url) || (b.source && b.source.url) || b.url || '';
        res.other.push({ label: 'imagem', url: /^https?:\/\//.test(url) ? url : '', size: url.length });
      } else if (t === 'tool_result') {
        const inner = typeof b.content === 'string' ? b.content : Array.isArray(b.content) ? b.content.map((x) => (typeof x === 'string' ? x : x && x.text) || '').join('\n') : '';
        texts.push(inner);
      } else res.other.push({ label: t || 'bloco', value: b });
    });
    let acc = '';
    texts.forEach((t, i) => {
      if (i && acc && !acc.endsWith('\n') && !t.startsWith('\n')) acc += '\n\n';
      acc += t;
    });
    res.text = acc;
    return res;
  }

  function callsOf(m, parts) {
    const out = [];
    const seen = new Set();
    (Array.isArray(m && m.tool_calls) ? m.tool_calls : []).forEach((c) => {
      if (!c || typeof c !== 'object') return;
      const id = c.id || c.call_id || null;
      out.push({ id, name: c.name || (c.function && c.function.name) || '', args: c.args !== undefined ? c.args : parseMaybe(c.function && c.function.arguments) });
      if (id) seen.add(id);
    });
    ((parts || splitContent(m)).blockCalls).forEach((c) => { if (!c.id || !seen.has(c.id)) out.push(c); });
    return out;
  }

  function charsOf(m, parts, calls) {
    let n = parts.text.length;
    parts.reasoning.forEach((r) => { n += r.text.length; });
    calls.forEach((c) => { try { n += JSON.stringify(c.args === undefined ? {} : c.args).length + (c.name || '').length; } catch (e) { /* ignora */ } });
    return n;
  }

  TA.ui.messageText = function messageText(m) { return splitContent(m).text; };

  TA.ui.messageStats = function messageStats(messages) {
    const list = Array.isArray(messages) ? messages : [];
    let chars = 0;
    list.forEach((m) => { if (!m) return; const p = splitContent(m); chars += charsOf(m, p, callsOf(m, p)); });
    return `${TA.fmt.num(list.length)} ${list.length === 1 ? 'mensagem' : 'mensagens'} · ${TA.fmt.num(chars)} caracteres`;
  };

  /* ================================================================== resultados de busca */
  function parseSearchResults(text) {
    if (typeof text !== 'string') return null;
    const re = /(?:^|\n)\[(\d+)\] ([^\n]*)\n(https?:\/\/\S+)[ \t]*(?:\n|$)/g;
    const heads = [];
    let m;
    while ((m = re.exec(text))) {
      heads.push({ n: m[1], title: m[2], url: m[3], start: m.index, end: m.index + m[0].length });
      if (re.lastIndex === m.index) re.lastIndex++;
    }
    if (!heads.length) return null;
    return heads.map((x, i) => ({ n: x.n, title: x.title, url: x.url, content: text.slice(x.end, i + 1 < heads.length ? heads[i + 1].start : text.length).trim() }));
  }
  TA.ui.parseSearchResults = parseSearchResults;

  function searchItems(src) {
    if (typeof src === 'string') {
      const a = parseSearchResults(src);
      if (a) return a;
      const j = tryJson(src);
      return j === undefined ? null : searchItems(j);
    }
    const arr = Array.isArray(src) ? src : (src && Array.isArray(src.results) ? src.results : null);
    if (!arr || !arr.length) return null;
    const items = arr.filter((r) => r && typeof r === 'object' && (r.url || r.link)).map((r, i) => ({
      n: String(i + 1), title: r.title || r.name || r.url || r.link, url: r.url || r.link, content: String(r.content || r.snippet || r.description || ''),
    }));
    return items.length ? items : null;
  }

  function domainOf(url) { try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return ''; } }

  /** lista amigável de resultados de busca (título, domínio, trecho); devolve null se o texto não parecer uma busca */
  TA.ui.searchResults = function searchResults(src) {
    const items = searchItems(src);
    if (!items) return null;
    const list = h('div', { class: 'ms-results' }, h('div', { class: 'ms-res-count' }, `${items.length} ${items.length === 1 ? 'resultado' : 'resultados'}`));
    items.forEach((r) => {
      const long = r.content.length > 360;
      const snip = h('div', { class: 'ms-res-snip' }, long ? r.content.slice(0, 360) + '… ' : r.content);
      if (long) snip.appendChild(h('button', { type: 'button', class: 'ms-more', onClick: () => { snip.textContent = r.content; } }, 'mais'));
      const safe = /^https?:\/\//i.test(r.url);
      list.appendChild(h('div', { class: 'ms-res' },
        h('span', { class: 'ms-res-n' }, r.n),
        h('div', { class: 'ms-res-main' },
          safe ? extLink(r.url, r.title) : h('span', { class: 'ms-res-title' }, r.title),
          h('div', { class: 'ms-res-url' }, h('span', { class: 'chip' }, domainOf(r.url) || 'web'), h('span', { class: 'truncate' }, r.url)),
          r.content ? snip : null)));
    });
    return list;
  };

  /* ================================================================== lista de mensagens */
  const MODE_LABEL = { md: 'MD', text: 'Texto', results: 'Resultados', json: 'Árvore', raw: 'JSON' };

  function reasoningBlock(r) {
    const body = r.text
      ? TA.ui.markdown(r.text)
      : h('div', { class: 'ms-note' }, r.encrypted ? `Raciocínio criptografado pelo provedor (${TA.fmt.num(r.size)} caracteres), sem resumo disponível.` : '(vazio)');
    return h('details', { class: 'ms-reason' },
      h('summary', null, TA.ui.icon('zap', 'sm'), ` Raciocínio${r.text ? ` · ${TA.fmt.num(r.text.length)} caracteres` : ''}`), body);
  }

  function otherBlock(o) {
    if (o.url !== undefined && o.label === 'imagem') {
      return h('div', { class: 'ms-note' }, o.url ? ['Imagem: ', extLink(o.url, TA.fmt.trunc(o.url, 80))] : `Imagem embutida (${TA.fmt.num(o.size)} caracteres)`);
    }
    return h('details', { class: 'ms-reason' }, h('summary', null, ` Bloco "${o.label}"`), TA.ui.jsonTree(o.value, { expand: 1 }));
  }

  function callBlock(c, opts) {
    const ref = opts.toolRef && c.id ? opts.toolRef(c.id) : null;
    const refKind = ref && ref.status ? TA.util.statusKind(ref.status) : '';
    return h('div', { class: 'ms-call' },
      h('div', { class: 'ms-call-head' },
        TA.ui.icon('tool', 'sm'),
        h('span', { class: 'ms-call-name' }, c.name || '(sem nome)'),
        c.id ? h('button', { type: 'button', class: 'chip mono ms-id', title: 'Copiar tool_call_id: ' + c.id, onClick: () => TA.util.copy(c.id) }, TA.fmt.short(c.id, 14)) : null,
        ref && ref.status ? h('span', { class: ['badge', refKind] }, h('span', { class: 'dot' }), TA.util.statusLabel(ref.status)) : null,
        ref && ref.duration_s !== undefined && ref.duration_s !== null ? h('span', { class: 'ms-stat' }, TA.fmt.dur(ref.duration_s)) : null,
        h('span', { class: 'spacer' }),
        ref && ref.href ? h('a', { class: 'btn sm', href: ref.href, onClick: ref.onClick || null }, 'Abrir span ', TA.ui.icon('external', 'sm')) : null,
        TA.ui.copyBtn(() => TA.util.pretty(c.args === undefined ? {} : c.args))),
      h('div', { class: 'ms-call-args' }, c.args !== null && typeof c.args === 'object'
        ? TA.ui.jsonTree(c.args, { expand: 2 }) : h('pre', { class: 'ms-pre' }, String(c.args === undefined ? '' : c.args))));
  }

  function makeCard(m, env) {
    const opts = env.opts;
    const role = roleOf(m);
    const meta = ROLE[role];
    const parts = splitContent(m);
    const calls = callsOf(m, parts);
    const text = parts.text;
    const chars = charsOf(m, parts, calls);
    const isErr = role === 'tool' && (m.status === 'error' || m.is_error === true);
    const origin = role === 'tool' && m.tool_call_id ? env.callMap[m.tool_call_id] : null;
    const toolName = role === 'tool' ? (m.name || (origin && origin.name) || null) : null;
    const ref = role === 'tool' && opts.toolRef && m.tool_call_id ? opts.toolRef(m.tool_call_id) : null;

    // modos disponíveis e o padrão
    const modes = [];
    const parsed = role === 'tool' || role === 'other' ? tryJson(text) : undefined;
    const isSearch = role === 'tool' && !!text && ((toolName || '').indexOf('search') >= 0 || /^\[1\] /.test(text)) && !!parseSearchResults(text);
    if (isSearch) modes.push('results');
    if (parsed !== undefined) modes.push('json');
    modes.push('md', 'text', 'raw');
    let defMode = isSearch ? 'results' : parsed !== undefined ? 'json' : (role === 'tool' || opts.markdown === false ? 'text' : 'md');
    if (role === 'tool' && !isSearch && parsed === undefined && opts.markdown !== false && /^(#{1,6} |\s*[-*] \S|\s*\d+\. \S|```|\*\*)/m.test(text)) defMode = 'md';
    let mode = defMode;
    let open = !(role === 'system' && opts.collapseSystem);
    let expanded = false;
    const cache = {};

    const bodyHost = h('div', { class: 'ms-body' });
    const modeBtns = {};
    const modeBar = h('div', { class: 'ms-modes', role: 'group', 'aria-label': 'Formato' }, modes.map((k) => {
      const b = h('button', { type: 'button', class: 'ms-modebtn', title: k === 'raw' ? 'Mensagem inteira em JSON' : k === 'text' ? 'Texto bruto' : MODE_LABEL[k], onClick: (e) => { e.stopPropagation(); setMode(k); } }, MODE_LABEL[k]);
      modeBtns[k] = b;
      return b;
    }));
    const chev = h('button', { type: 'button', class: 'ms-chev', 'aria-label': 'Recolher ou expandir', onClick: (e) => { e.stopPropagation(); setOpen(!open); } }, TA.ui.icon('chevR', 'sm'));
    const usage = role === 'ai' && m.usage_metadata ? m.usage_metadata : null;
    const preview = h('span', { class: 'ms-preview' }, TA.fmt.trunc(text || (calls[0] ? `chama ${calls.map((c) => c.name).join(', ')}` : ''), 160));
    const head = h('div', { class: 'ms-head', onClick: (e) => { if (!e.target.closest('a,button')) setOpen(!open); } },
      chev,
      h('span', { class: 'ms-avatar' }, TA.ui.icon(meta.icon, 'sm')),
      h('span', { class: 'ms-role' }, role === 'other' ? (m.type || m.role || meta.label) : meta.label),
      toolName ? h('span', { class: 'chip mono ms-toolname' }, toolName) : (m.name && role !== 'tool' ? h('span', { class: 'chip mono' }, m.name) : null),
      role === 'tool' && m.status ? h('span', { class: ['badge', isErr ? 'err' : 'ok'] }, h('span', { class: 'dot' }), isErr ? 'erro' : 'sucesso') : null,
      role === 'tool' && m.tool_call_id ? h('button', { type: 'button', class: 'chip mono ms-id', title: 'Copiar tool_call_id: ' + m.tool_call_id, onClick: (e) => { e.stopPropagation(); TA.util.copy(m.tool_call_id); } }, TA.fmt.short(m.tool_call_id, 14)) : null,
      ref && ref.href ? h('a', { class: 'ms-reflink', href: ref.href, onClick: ref.onClick || null }, 'span ', TA.ui.icon('external', 'sm')) : null,
      preview,
      h('span', { class: 'spacer' }),
      usage ? h('span', { class: 'ms-stat', title: 'tokens da resposta (usage_metadata)' }, `${TA.fmt.num(usage.input_tokens)} → ${TA.fmt.num(usage.output_tokens)} tok`) : null,
      h('span', { class: 'ms-stat', title: 'caracteres · tokens estimados (caracteres / 4)' }, `${TA.fmt.num(chars)} car · ~${TA.fmt.num(estimateTokens(chars))} tok`),
      modeBar,
      TA.ui.copyBtn(() => (mode === 'raw' ? TA.util.pretty(m) : (text || (calls.length ? TA.util.pretty(calls.map((c) => ({ name: c.name, args: c.args }))) : '')))));

    function textNode(md) {
      const big = text.length > BIG_CHARS && !expanded;
      let node;
      if (md === 'results') node = TA.ui.searchResults(text);
      else if (md === 'json') node = parsed !== undefined ? TA.ui.jsonTree(parsed, { expand: 2 }) : null;
      else if (md === 'md' && !big) node = TA.ui.markdown(text);
      if (!node) node = h('pre', { class: 'ms-pre' }, big ? text.slice(0, CLIP_CHARS) + '…' : text);
      if (text.length <= CLIP_CHARS) return node;
      const clip = h('div', { class: ['ms-clip', !expanded && 'ms-clipped'] }, node);
      const btn = h('button', { type: 'button', class: 'ms-showall', onClick: () => { expanded = !expanded; paint(); } },
        expanded ? 'Recolher' : `Mostrar tudo (${TA.fmt.num(text.length)} caracteres)`);
      return h('div', null, clip, btn);
    }

    function build(md) {
      if (md === 'raw') return h('div', { class: 'ms-rawjson' }, TA.ui.jsonTree(m, { expand: 1 }));
      const kids = [];
      parts.reasoning.forEach((r) => kids.push(reasoningBlock(r)));
      if (text) kids.push(textNode(md));
      else if (!calls.length && !parts.reasoning.length && !parts.other.length) kids.push(h('div', { class: 'ms-note' }, '(sem conteúdo)'));
      parts.other.forEach((o) => kids.push(otherBlock(o)));
      calls.forEach((c) => kids.push(callBlock(c, opts)));
      const ak = m.additional_kwargs;
      if (ak && typeof ak === 'object' && Object.keys(ak).length) {
        kids.push(h('details', { class: 'ms-reason' }, h('summary', null, ' additional_kwargs'), TA.ui.jsonTree(ak, { expand: 1 })));
      }
      return h('div', { class: 'ms-parts' }, kids);
    }

    function paint() {
      const key = mode + (expanded ? '+' : '');
      if (!cache[key]) {
        try { cache[key] = build(mode); } catch (e) { cache[key] = TA.ui.error(e); }
      }
      TA.util.clear(bodyHost);
      bodyHost.appendChild(cache[key]);
      Object.keys(modeBtns).forEach((k) => modeBtns[k].classList.toggle('on', k === mode));
    }
    function setMode(k) { if (modeBtns[k]) { mode = k; if (open) paint(); else { Object.keys(modeBtns).forEach((x) => modeBtns[x].classList.toggle('on', x === mode)); } } }
    function setOpen(o) {
      open = !!o;
      el.classList.toggle('ms-open', open);
      chev.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) paint();
    }
    const el = h('div', { class: ['ms-msg', 'ms-role-' + role, isErr && 'ms-err'] },
      head,
      origin && origin.args && typeof origin.args === 'object' ? h('div', { class: 'ms-sub' }, 'args: ', h('code', null, TA.fmt.trunc(JSON.stringify(origin.args), 200))) : null,
      bodyHost);
    Object.keys(modeBtns).forEach((k) => modeBtns[k].classList.toggle('on', k === mode));
    setOpen(open);
    return { el, setMode: (k) => setMode(k === 'auto' ? defMode : k), setOpen, defMode };
  }

  /** lista de mensagens no formato de tracing/serialize.py. opts: {collapseSystem=true, markdown=true, toolbar=true, toolRef(id)->{href,onClick?,status?,duration_s?}} */
  TA.ui.messages = function messages(list, opts) {
    opts = Object.assign({ collapseSystem: true, markdown: true, toolbar: true }, opts || {});
    const msgs = Array.isArray(list) ? list.filter((m) => m !== null && m !== undefined && typeof m === 'object') : [];
    const root = h('div', { class: 'ms-wrap' });
    if (!msgs.length) { root.appendChild(h('div', { class: 'ms-note' }, 'Nenhuma mensagem.')); return root; }
    const callMap = {};
    msgs.forEach((m) => callsOf(m).forEach((c) => { if (c.id) callMap[c.id] = c; }));
    const cards = msgs.map((m) => {
      try { return makeCard(m, { opts, callMap }); } catch (e) { return { el: TA.ui.error(e), setMode() {}, setOpen() {} }; }
    });
    if (opts.toolbar !== false && msgs.length > 0) {
      const seg = TA.ui.seg({
        options: [{ value: 'auto', label: 'Markdown' }, { value: 'text', label: 'Texto' }, { value: 'raw', label: 'JSON' }], value: 'auto',
        onChange: (v) => cards.forEach((c) => c.setMode(v)),
      });
      root.appendChild(h('div', { class: 'ms-toolbar' },
        h('span', { class: 'ms-statline' }, TA.ui.messageStats(msgs)),
        h('span', { class: 'spacer' }),
        h('button', { type: 'button', class: 'btn sm ghost', onClick: () => cards.forEach((c) => c.setOpen(true)) }, 'Expandir tudo'),
        h('button', { type: 'button', class: 'btn sm ghost', onClick: () => cards.forEach((c) => c.setOpen(false)) }, 'Recolher tudo'),
        seg.el));
    }
    root.appendChild(h('div', { class: 'ms-list' }, cards.map((c) => c.el)));
    return root;
  };
})();
