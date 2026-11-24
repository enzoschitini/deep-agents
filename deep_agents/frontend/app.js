// Chat collegata al backend vero (python -m deep_agents.server). Le sessioni sono le stesse della CLI.
(() => {
  const $ = (id) => document.getElementById(id);
  const app = $("app"), frame = $("frame"), thread = $("thread"), scroller = $("scroll");
  const form = $("form"), input = $("input"), sendBtn = $("send"), historyEl = $("history"), search = $("search");

  const SUGGESTIONS = [
    "Cerca novità su LangChain",
    "Scrivi un post per LinkedIn",
    "Spiega i subagent dinamici",
    "Confronta due framework di agenti",
  ];
  const KNOWN_AGENTS = new Set(["pesquisador", "redator"]);

  let state = { model: "", session: "", messages: [], sessions: [] };
  let busy = false;
  let controller = null;   // AbortController della risposta in corso

  const ic = (name, cls = "") => `<svg class="icon ${cls}"><use href="#i-${name}"/></svg>`;
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const hhmm = (d) => d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

  // Markdown minimale: blocchi di codice, tabelle, titoli, elenchi, citazioni, grassetto, codice inline, link.
  function md(src) {
    const inline = (t) => esc(t)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return src.split(/```(?:\w+)?\n?/).map((chunk, i) => {
      if (i % 2) return `<pre><code>${esc(chunk.replace(/\n$/, ""))}</code></pre>`;
      return chunk.trim().split(/\n{2,}/).filter(Boolean).map((block) => {
        const lines = block.split("\n");
        if (/^\s*([-*_])\1{2,}\s*$/.test(block)) return "<hr>";
        if (lines.length >= 2 && lines.every((l) => /^\s*\|.*\|\s*$/.test(l)) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[1])) {
          const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
          const align = cells(lines[1]).map((c) => (/^:-+:$/.test(c) ? "center" : /-:$/.test(c) ? "right" : ""));
          const row = (l, tag) => `<tr>${cells(l).map((c, i) => `<${tag}${align[i] ? ` style="text-align:${align[i]}"` : ""}>${inline(c)}</${tag}>`).join("")}</tr>`;
          return `<div class="table-wrap"><table><thead>${row(lines[0], "th")}</thead><tbody>${lines.slice(2).map((l) => row(l, "td")).join("")}</tbody></table></div>`;
        }
        const head = block.match(/^(#{1,4})\s+(.*)$/);
        if (head && lines.length === 1) return `<h4>${inline(head[2])}</h4>`;
        if (lines.every((l) => /^\s*[-*] /.test(l))) return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
        if (lines.every((l) => /^\d+\. /.test(l))) return `<ol>${lines.map((l) => `<li>${inline(l.replace(/^\d+\. /, ""))}</li>`).join("")}</ol>`;
        if (lines.every((l) => /^> /.test(l))) return `<blockquote>${lines.map((l) => inline(l.slice(2))).join("<br>")}</blockquote>`;
        return `<p>${lines.map(inline).join("<br>")}</p>`;
      }).join("");
    }).join("");
  }

  const scrollDown = () => { scroller.scrollTop = scroller.scrollHeight; };

  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `errore ${res.status}`);
    return data;
  }

  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 4000);
  }

  // ---------------------------------------------------------------- barra laterale
  function dayLabel(date) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const d = new Date(date); d.setHours(0, 0, 0, 0);
    const diff = Math.round((today - d) / 86400000);
    if (diff <= 0) return "Oggi";
    if (diff === 1) return "Ieri";
    return d.toLocaleDateString("it-IT", { day: "numeric", month: "long", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" });
  }

  // Colori degli avatar delle sessioni: la palette degli agenti dell'interfaccia di riferimento.
  const TINTS = ["#4aa3ff", "#3ddc97", "#b58cff", "#ff6fb1", "#f5c84b", "#5fd6e6", "#d6adf2", "#ff8a5c"];
  function tintFor(id) {
    let h = 5381;
    for (const ch of String(id)) h = ((h << 5) + h + ch.charCodeAt(0)) >>> 0;
    return TINTS[h % TINTS.length];
  }

  function rowNode({ title, time, preview, current, onClick, blink, tint, session }) {
    const wrap = document.createElement("div");
    wrap.className = "agent-row-wrap";
    const b = document.createElement("div");   // non un <button>: dentro c'è il campo della rinomina
    b.setAttribute("role", "button"); b.tabIndex = 0;
    b.className = "agent-row";
    b.addEventListener("keydown", (e) => { if (e.target === b && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); b.click(); } });
    if (current) b.setAttribute("aria-current", "true");
    b.innerHTML = `<span class="avatar${blink ? " blink" : ""}" data-agent="main" aria-hidden="true"></span><span><span class="agent-row-heading"><strong class="agent-row-title"></strong><span class="agent-row-time"></span></span><span class="agent-row-preview"></span></span>`;
    if (tint) { const av = b.querySelector(".avatar"); av.dataset.tint = ""; av.style.setProperty("--tint", tint); }
    b.querySelector(".agent-row-title").textContent = title;
    b.querySelector(".agent-row-time").textContent = time;
    b.querySelector(".agent-row-preview").textContent = preview;
    b.title = title;
    b.onclick = onClick;
    wrap.appendChild(b);
    if (session) {   // sessioni salvate: menu "⋯" e tasto destro
      const more = document.createElement("button");
      more.type = "button"; more.className = "row-more"; more.setAttribute("aria-label", "Altre azioni"); more.setAttribute("aria-haspopup", "menu");
      more.innerHTML = ic("dots");
      more.onclick = (e) => { e.stopPropagation(); const r = more.getBoundingClientRect(); openRowMenu(session, wrap, r.left, r.bottom + 4, more); };
      wrap.appendChild(more);
      wrap.addEventListener("contextmenu", (e) => { e.preventDefault(); openRowMenu(session, wrap, e.clientX, e.clientY, more); });
    }
    return wrap;
  }

  // ---------------------------------------------------------------- menu delle sessioni, rinomina, eliminazione
  const rowMenu = $("rowMenu");
  let menuOwner = null;
  function closeRowMenu() { rowMenu.hidden = true; menuOwner?.setAttribute("aria-expanded", "false"); menuOwner = null; }
  function openRowMenu(session, wrap, x, y, owner) {
    closeRowMenu();
    rowMenu.innerHTML = "";
    const item = (label, icon, cls, fn) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "menuitem"); if (cls) b.className = cls;
      b.innerHTML = `${ic(icon)}<span>${label}</span>`;
      b.onclick = () => { closeRowMenu(); fn(); };
      rowMenu.appendChild(b);
    };
    item("Rinomina", "pencil", "", () => startRename(session, wrap));
    item("Elimina", "trash", "danger", () => deleteSession(session));
    rowMenu.hidden = false;
    const w = rowMenu.offsetWidth, h = rowMenu.offsetHeight;
    rowMenu.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + "px";
    rowMenu.style.top = Math.max(8, Math.min(y, innerHeight - h - 8)) + "px";
    menuOwner = owner; owner.setAttribute("aria-expanded", "true");
    rowMenu.querySelector("button").focus();
  }
  document.addEventListener("click", (e) => { if (!rowMenu.contains(e.target)) closeRowMenu(); });
  historyEl.addEventListener("scroll", closeRowMenu);
  rowMenu.addEventListener("click", (e) => e.stopPropagation());

  function startRename(session, wrap) {
    const h = wrap.querySelector(".agent-row-title");
    const input = document.createElement("input");
    input.className = "agent-row-title-input"; input.value = session.title || session.preview || ""; input.maxLength = 80;
    input.setAttribute("aria-label", "Nuovo nome della conversazione");
    h.replaceWith(input);
    input.focus(); input.select();
    let done = false;
    const finish = async (save) => {
      if (done) return; done = true;
      const value = input.value.trim();
      if (save && value !== (session.title || session.preview)) {
        try { state = await api("/api/session/rename", { id: session.id, title: value }); } catch (e) { toast(e.message); }
      }
      renderHistory();
    };
    input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); finish(true); } else if (e.key === "Escape") { e.preventDefault(); finish(false); } };
    input.onblur = () => finish(true);
    input.onclick = (e) => e.stopPropagation();
  }

  const dialog = $("dialog");
  function confirmDialog(title, text, okLabel) {
    $("dialogTitle").textContent = title; $("dialogText").textContent = text; $("dialogOk").textContent = okLabel;
    return new Promise((resolve) => {
      const done = (value) => {
        $("dialogOk").onclick = $("dialogCancel").onclick = dialog.oncancel = null;
        if (dialog.open) dialog.close();
        resolve(value);
      };
      $("dialogOk").onclick = () => done(true);
      $("dialogCancel").onclick = () => done(false);
      dialog.oncancel = (e) => { e.preventDefault(); done(false); };   // tasto Esc
      dialog.showModal();
      $("dialogCancel").focus();
    });
  }

  async function deleteSession(session) {
    if (busy) return toast("C'è una risposta in corso: attendi che finisca.");
    const name = session.title || session.preview || session.id;
    if (!(await confirmDialog("Eliminare questa conversazione?", `«${name.length > 60 ? name.slice(0, 59) + "…" : name}» sarà eliminata anche dalla CLI. Non si può annullare.`, "Elimina"))) return;
    try { apply(await api("/api/session/delete", { id: session.id })); } catch (e) { toast(e.message); }
  }

  $("clearAll").onclick = async () => {
    if (busy) return toast("C'è una risposta in corso: attendi che finisca.");
    const n = state.sessions.length;
    if (!n) return;
    if (!(await confirmDialog("Eliminare tutte le conversazioni?", `${n === 1 ? "Verrà eliminata 1 conversazione" : `Verranno eliminate ${n} conversazioni`}, anche per la CLI. Non si può annullare.`, "Elimina tutte"))) return;
    try { apply(await api("/api/session/delete_all", {})); toast("Conversazioni eliminate."); } catch (e) { toast(e.message); }
  };

  function renderHistory() {
    const q = search.value.trim().toLowerCase();
    historyEl.innerHTML = "";
    $("model").textContent = state.model || "…";
    renderModelMenu();

    const inList = state.sessions.some((s) => s.id === state.session);
    if (!inList && !q) {   // sessione corrente ancora vuota: la mostro, come una chat appena creata
      const sec = document.createElement("section");
      sec.innerHTML = '<span class="sidebar-section-name">Adesso</span>';
      sec.appendChild(rowNode({ title: "Nuova chat", time: hhmm(new Date()), preview: "Nessun messaggio", current: true, blink: true, onClick: () => {} }));
      historyEl.appendChild(sec);
    }

    $("clearAll").disabled = !state.sessions.length;
    const shown = state.sessions.filter((s) => !q || (s.title || s.preview || s.id).toLowerCase().includes(q));
    if (!shown.length && q) {
      historyEl.innerHTML = '<p class="agent-list-empty">Nessuna sessione corrisponde alla ricerca.</p>';
      return;
    }
    let lastLabel = null, sec = null;
    shown.forEach((s) => {
      const when = new Date(s.updated_at);
      const label = isNaN(when) ? "Sessioni" : dayLabel(when);
      if (label !== lastLabel) {
        sec = document.createElement("section");
        sec.innerHTML = `<span class="sidebar-section-name">${esc(label)}</span>`;
        historyEl.appendChild(sec);
        lastLabel = label;
      }
      sec.appendChild(rowNode({
        title: s.title || s.preview || s.id,
        session: s,
        time: isNaN(when) ? "" : hhmm(when),
        preview: `${s.count} messaggi`,
        current: s.id === state.session,
        tint: tintFor(s.id),
        onClick: async () => {
          closeDrawer();
          if (busy || s.id === state.session) return;
          try { apply(await api("/api/session/resume", { id: s.id })); } catch (e) { toast(e.message); }
        },
      }));
    });
  }

  function apply(newState) {
    state = newState;
    renderHistory();
    thread.innerHTML = "";
    if (!state.messages.length) return renderWelcome();
    const cur = state.sessions.find((s) => s.id === state.session);
    const when = cur && !isNaN(new Date(cur.updated_at)) ? new Date(cur.updated_at) : new Date();
    thread.appendChild(timeMarker(when));
    state.messages.forEach((m) => thread.appendChild(m.role === "user" ? userNode(m.content) : agentNode(m.content)));
    scroller.scrollTop = scroller.scrollHeight;
  }

  async function newChat() {
    closeDrawer();
    if (busy) return;
    try { apply(await api("/api/session/new", {})); } catch (e) { toast(e.message); }
    input.focus();
  }

  const closeDrawer = () => app.classList.remove("side-open");
  const toggleSide = () => frame.classList.toggle("collapsed");
  $("collapseSide").onclick = toggleSide;
  $("expandSide").onclick = toggleSide;
  $("railSessions").onclick = () => { toggleSide(); $("railSessions").setAttribute("aria-pressed", String(!frame.classList.contains("collapsed"))); };
  $("openSide").onclick = () => app.classList.add("side-open");
  $("scrim").onclick = closeDrawer;
  $("newChat").onclick = newChat;
  $("railBrand").onclick = newChat;
  search.addEventListener("input", renderHistory);

  // ---------------------------------------------------------------- modello
  const modelBtn = $("modelBtn"), modelMenu = $("modelMenu");
  function setModelMenu(open) { modelMenu.hidden = !open; modelBtn.setAttribute("aria-expanded", String(open)); }
  function renderModelMenu() {
    modelMenu.innerHTML = '<div class="menu-title">Modello</div>';
    (state.models || [state.model]).forEach((spec) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "menu-item"; b.setAttribute("role", "menuitemradio");
      b.setAttribute("aria-checked", String(spec === state.model));
      b.innerHTML = `<span></span>${spec === state.model ? ic("check") : ""}`;
      b.firstChild.textContent = spec;
      b.onclick = () => changeModel(spec);
      modelMenu.appendChild(b);
    });
  }
  async function changeModel(spec) {
    setModelMenu(false);
    if (busy) return toast("C'è una risposta in corso: attendi che finisca.");
    if (spec === state.model) return;
    modelBtn.setAttribute("aria-busy", "true");
    try {
      state = await api("/api/model", { model: spec });
      renderHistory(); renderModelMenu();
      toast(`Modello impostato: ${state.model}`);
    } catch (e) { toast(e.message); }
    modelBtn.removeAttribute("aria-busy");
  }
  modelBtn.onclick = (e) => { e.stopPropagation(); setMenu(false); setModelMenu(modelMenu.hidden); };
  modelMenu.addEventListener("click", (e) => e.stopPropagation());

  // ---------------------------------------------------------------- menu "+"
  const plusBtn = $("plusBtn"), plusMenu = $("plusMenu");
  function buildMenu() {
    plusMenu.innerHTML = '<div class="menu-title">Suggerimenti</div>';
    SUGGESTIONS.forEach((t) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "menuitem"); b.textContent = t;
      b.onclick = () => { setMenu(false); input.value = t; autosize(); input.focus(); };
      plusMenu.appendChild(b);
    });
    plusMenu.insertAdjacentHTML("beforeend", "<hr>");
    const n = document.createElement("button");
    n.type = "button"; n.setAttribute("role", "menuitem"); n.textContent = "Nuova chat";
    n.onclick = () => { setMenu(false); newChat(); };
    plusMenu.appendChild(n);
  }
  function setMenu(open) { plusMenu.hidden = !open; plusBtn.setAttribute("aria-expanded", String(open)); }
  plusBtn.onclick = (e) => { e.stopPropagation(); setModelMenu(false); setMenu(plusMenu.hidden); };
  document.addEventListener("click", (e) => { if (!plusMenu.contains(e.target)) setMenu(false); setModelMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { setMenu(false); setModelMenu(false); closeRowMenu(); closeDrawer(); } });
  buildMenu();

  // ---------------------------------------------------------------- messaggi
  function renderWelcome() {
    thread.innerHTML = `
      <div class="welcome">
        <span class="avatar blink" data-agent="main" aria-hidden="true"></span>
        <h2>Come posso aiutarti?</h2>
        <p>L'agente principale decide se rispondere da solo o delegare a un subagent. Vedrai i passaggi mentre accadono.</p>
        <div class="chips"></div>
      </div>`;
    const chips = thread.querySelector(".chips");
    SUGGESTIONS.forEach((t) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = t;
      b.onclick = () => send(t);
      chips.appendChild(b);
    });
  }

  function timeMarker(date) {
    const d = document.createElement("div");
    d.className = "time-marker";
    d.innerHTML = `<span>${esc(dayLabel(date))} ${hhmm(date)}</span>`;
    return d;
  }

  function userNode(text) {
    const d = document.createElement("div");
    d.className = "message-entry user";
    d.innerHTML = '<div class="message-shell"><div class="ui-bubble"></div></div>';
    d.querySelector(".ui-bubble").textContent = text;
    return d;
  }

  // Risposta dell'agente: attività in diretta, bolla col testo, fonti e azioni.
  function agentNode(text) {
    const d = document.createElement("div");
    d.className = "message-entry agent";
    d.innerHTML = '<div class="message-shell"><div class="agent-activity"></div><div class="ui-bubble md"></div></div>';
    const bubble = d.querySelector(".ui-bubble");
    if (text != null) { bubble.innerHTML = md(text); addActions(d, text); } else bubble.hidden = true;
    return d;
  }

  function addActions(node, text, metrics) {
    const row = document.createElement("div");
    row.className = "message-action-row";
    row.innerHTML = `<button type="button" class="message-action-button">${ic("copy")}Copia</button>`;
    const btn = row.firstChild;
    btn.onclick = () => {
      navigator.clipboard?.writeText(text);
      btn.innerHTML = `${ic("check")}Copiato`;
      setTimeout(() => (btn.innerHTML = `${ic("copy")}Copia`), 1500);
    };
    if (metrics) { const m = document.createElement("span"); m.className = "metrics"; m.textContent = metrics; m.title = metrics; row.appendChild(m); }
    node.querySelector(".message-shell").appendChild(row);
  }

  function setBusy(v) {
    busy = v;
    sendBtn.classList.toggle("busy", v);
    sendBtn.setAttribute("aria-label", v ? "Interrompi" : "Invia");
    sendBtn.disabled = v ? false : !input.value.trim();
  }

  // ---------------------------------------------------------------- passaggi dell'agente (eventi reali dello streaming)
  // Ogni evento SSE è uno StreamEvent.to_dict(): kind/phase/id/parent_id/label/name/agent/visibility/data...
  const DEBUG = new URLSearchParams(location.search).has("debug");
  if (DEBUG) document.body.classList.add("show-debug");
  const detailsBtn = $("detailsBtn");
  function setDetails(on, save = true) {
    document.body.classList.toggle("show-details", on);
    detailsBtn.setAttribute("aria-pressed", String(on));
    if (save) { try { localStorage.setItem("details", on ? "1" : "0"); } catch { /* senza storage resta per la sessione */ } }
  }
  let savedDetails = false;
  try { savedDetails = localStorage.getItem("details") === "1"; } catch { /* storage non disponibile */ }
  setDetails(savedDetails, false);
  detailsBtn.onclick = () => setDetails(!document.body.classList.contains("show-details"));

  // Tipi che non sono "attività" (hanno una resa propria o nessuna).
  const NOT_ACTIVITY = new Set(["response", "reasoning", "run", "notice", "sources", "tool_args"]);
  const KIND_ICON = { skill: "sparkle", todos: "list", async_task: "bot", file: "wrench", code_eval: "wrench", model_call: "bot", summarization: "list" };
  const isAgent = (ev) => ev.kind === "subagent" || ev.kind === "subagent_dynamic";

  function stepNode(ev) {
    const wrap = document.createElement("div");
    wrap.className = "act";
    wrap.dataset.id = ev.id;
    wrap.dataset.vis = ev.visibility || "primary";
    const s = document.createElement("div");
    s.className = "step";
    const lead = isAgent(ev)
      ? `<span class="avatar" data-agent="${KNOWN_AGENTS.has(ev.name) ? ev.name : "other"}" aria-hidden="true"></span>`
      : `<span class="step-tool-icon" aria-hidden="true">${ic(KIND_ICON[ev.kind] || (/search/.test(ev.name || "") ? "globe" : "wrench"))}</span>`;
    s.innerHTML = `${lead}<b></b><span class="lbl"></span><span class="dur"></span><span class="state"><span class="spin"></span></span>`;
    s.querySelector("b").textContent = ev.name || ev.kind;
    s.querySelector(".lbl").textContent = ev.label || (isAgent(ev) ? "al lavoro" : "in uso");
    const kids = document.createElement("div");
    kids.className = "children";
    wrap.append(s, kids);
    return wrap;
  }

  function sourcesNode(sources) {
    const d = document.createElement("div");
    d.className = "sources";
    sources.forEach((s) => {
      const a = document.createElement("a");
      a.className = "source-pill";
      a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.title = s.title || s.url;
      a.innerHTML = "<span></span><b></b>";
      a.firstChild.textContent = (s.domain || "").replace(/^www\./, "");
      a.lastChild.textContent = s.title || s.url;
      d.appendChild(a);
    });
    return d;
  }

  // Blocco comprimibile (<details>) per "pensiero" (testo intermedio) e ragionamento del modello.
  function foldNode(cls, title, vis) {
    const d = document.createElement("details");
    d.className = `fold ${cls}`;
    d.dataset.vis = vis;
    d.innerHTML = '<summary></summary><div class="fold-body md"></div>';
    d.querySelector("summary").textContent = title;
    return d;
  }

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    if (!thread.querySelector(".message-entry")) { thread.innerHTML = ""; thread.appendChild(timeMarker(new Date())); }
    thread.appendChild(userNode(text));
    input.value = ""; autosize();

    const node = agentNode(null);
    const shell = node.querySelector(".message-shell");
    const activity = node.querySelector(".agent-activity"), bubble = node.querySelector(".ui-bubble");
    const DOTS = '<span class="thinking" role="status" aria-label="L\'agente sta pensando"><i></i><i></i><i></i></span>';
    bubble.hidden = false;
    bubble.innerHTML = DOTS;
    thread.appendChild(node);
    scrollDown();
    setBusy(true);
    controller = new AbortController();

    const items = new Map();   // id evento -> nodo .act
    let respText = "", respId = null, streaming = false, renderQueued = false;
    let reasoning = null, reasoningText = "", reasoningId = null;
    let sourcesShown = false, ended = false, failed = null;

    const renderBubble = () => {
      renderQueued = false;
      bubble.hidden = false;
      bubble.classList.toggle("caret", streaming);
      bubble.innerHTML = md(respText);
      scrollDown();
    };
    const queueRender = () => { if (!renderQueued) { renderQueued = true; requestAnimationFrame(renderBubble); } };
    const resetBubble = (dots) => {
      renderQueued = false; streaming = false; respText = ""; respId = null;
      bubble.classList.remove("caret");
      bubble.innerHTML = dots ? DOTS : "";
      bubble.hidden = !dots;
    };
    const closeSpinners = (ok) => activity.querySelectorAll(".spin").forEach((sp) => (sp.parentElement.innerHTML = ic(ok ? "check" : "x", ok ? "ok" : "bad")));
    const showSources = (list) => {
      if (sourcesShown || !list?.length) return;
      sourcesShown = true;
      shell.appendChild(sourcesNode(list));
    };
    const finish = (el, ev, error) => {
      const state = el.querySelector(":scope > .step .state");
      if (state) state.innerHTML = error ? ic("x", "bad") : ic("check", "ok");
      if (ev.duration_s != null) el.querySelector(":scope > .step .dur").textContent = `${Number(ev.duration_s).toFixed(1)}s`;
      const tip = error || ev.summary;
      if (tip) el.querySelector(":scope > .step").title = String(tip);
    };

    function onActivity(ev) {
      let el = items.get(ev.id);
      if (!el) {
        if (ev.visibility === "debug" && !DEBUG) return;
        el = stepNode(ev);
        items.set(ev.id, el);
        (items.get(ev.parent_id)?.querySelector(":scope > .children") || activity).appendChild(el);
        if (!respText) bubble.hidden = true;   // niente puntini: l'attività è già visibile
        scrollDown();
      } else if (ev.phase === "start" && ev.label) {   // il replay di un evento (stesso id) aggiorna, non duplica
        el.querySelector(":scope > .step .lbl").textContent = ev.label;
      }
      if (ev.phase === "error") finish(el, ev, ev.error || "errore");
      else if (ev.phase === "end" || ev.phase === "info") finish(el, ev, null);
    }

    function onResponse(ev) {
      if (ev.agent && ev.agent !== "main") return;   // i token dei subagent (debug) non vanno nella bolla
      const d = ev.data || {};
      if (ev.phase === "delta") {
        if (respId !== null && ev.id !== respId) respText = "";
        respId = ev.id; streaming = true;
        respText += d.text || "";
        queueRender();
      } else if (ev.phase === "end") {
        const full = d.text ?? respText;
        if (d.final === false) {   // testo intermedio: diventa un "pensiero" comprimibile
          if (full.trim()) {
            const f = foldNode("thought", "Pensiero", "primary");
            f.querySelector(".fold-body").innerHTML = md(full);
            activity.appendChild(f);
          }
          resetBubble(false);
        } else {
          respText = full; streaming = false;
          if (full) renderBubble();
        }
      }
    }

    function onReasoning(ev) {
      if (ev.agent && ev.agent !== "main") return;
      if (!reasoning || reasoningId !== ev.id) {
        reasoning = foldNode("reasoning", "Ragionamento", "secondary");
        reasoningText = ""; reasoningId = ev.id;
        activity.appendChild(reasoning);
      }
      reasoningText += ev.data?.text || "";
      reasoning.querySelector(".fold-body").textContent = reasoningText;
    }

    function handle(ev) {
      switch (ev.kind) {
        case "response": return onResponse(ev);
        case "reasoning": return onReasoning(ev);
        case "sources": return showSources(ev.data?.sources);
        case "notice": return toast(ev.data?.message || ev.label || "");
        case "run":
          if (ev.phase === "error") { failed = ev.error || "errore"; return; }
          if (ev.phase === "end") {
            ended = true;
            const d = ev.data || {};
            closeSpinners(true);
            if (d.answer != null) { respText = d.answer; streaming = false; renderBubble(); }
            showSources(d.sources);
            addActions(node, d.answer ?? respText, d.metrics);
          }
          return;
        default:
          if (!NOT_ACTIVITY.has(ev.kind)) onActivity(ev);
      }
    }

    try {
      const res = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, debug: DEBUG }), signal: controller.signal,
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `errore ${res.status}`);

      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, cut).replace(/^data: /, "");
          buf = buf.slice(cut + 2);
          let ev; try { ev = JSON.parse(line); } catch { continue; }
          try { handle(ev); } catch (e) { console.error("evento non gestito", ev, e); }
        }
      }
    } catch (e) {
      if (e.name === "AbortError") {
        bubble.classList.remove("caret");
        if (!ended) {
          closeSpinners(false);
          if (!respText) {
            bubble.hidden = false;
            bubble.innerHTML = "<p><i>Risposta interrotta. L'agente può finire in background e la risposta resta salvata nella sessione.</i></p>";
          }
        }
      } else {
        failed = e.message;
      }
    }

    if (failed) {
      closeSpinners(false);
      streaming = false; renderQueued = false;
      bubble.classList.remove("caret");
      bubble.hidden = false;
      bubble.innerHTML = (respText ? md(respText) : "") + `<div class="error"><b>Errore.</b> ${esc(failed)}</div>`;
    } else if (!ended && !controller?.signal.aborted) {
      closeSpinners(false);   // il flusso si è chiuso senza `run/end`
    }
    bubble.classList.remove("caret");
    controller = null;
    setBusy(false);
    scrollDown();
    try { state = await api("/api/state"); renderHistory(); } catch { /* il prossimo invio riprova */ }
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 200) + "px";
    if (!busy) sendBtn.disabled = !input.value.trim();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) controller?.abort(); else send(input.value);
  });
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!busy) send(input.value); }
  });

  // Avvio: carica lo stato dal backend (stessa memoria della CLI).
  renderWelcome();
  api("/api/state").then(apply).catch(() => {
    thread.innerHTML = '<div class="welcome"><span class="avatar" data-agent="other" aria-hidden="true"></span><h2>Backend non raggiungibile</h2><p>Avvia il server con <code>python -m deep_agents.server</code> e apri l\'indirizzo che stampa, invece di aprire il file HTML direttamente.</p></div>';
  });
  input.focus();
})();
