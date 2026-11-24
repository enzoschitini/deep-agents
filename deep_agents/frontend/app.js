// Chat UI collegata al backend vero (python -m deep_agents.server). Le sessioni sono le stesse della CLI.
(() => {
  const $ = (id) => document.getElementById(id);
  const app = $("app"), thread = $("thread"), scroller = $("scroll");
  const form = $("form"), input = $("input"), sendBtn = $("send"), historyEl = $("history");

  const SUGGESTIONS = [
    ["Cerca novità su LangChain", "Il pesquisador cerca sul web e riassume."],
    ["Scrivi un post per LinkedIn", "Il redator prepara una bozza pronta da pubblicare."],
    ["Spiega i subagent dinamici", "Come l'agente principale delega il lavoro."],
    ["Confronta due framework di agenti", "Ricerca e sintesi in una tabella."],
  ];

  let state = { model: "", session: "", messages: [], sessions: [] };
  let busy = false;
  let controller = null;   // AbortController della risposta in corso

  const icons = {
    copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>',
    check: '<svg viewBox="0 0 24 24" class="check"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    x: '<svg viewBox="0 0 24 24" class="check err"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  };

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  // Markdown minimale: blocchi di codice, titoli, elenchi, citazioni, grassetto, codice inline, link.
  function md(src) {
    const inline = (t) => esc(t)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return src.split(/```(?:\w+)?\n?/).map((chunk, i) => {
      if (i % 2) return `<pre><code>${esc(chunk.replace(/\n$/, ""))}</code></pre>`;
      return chunk.trim().split(/\n{2,}/).filter(Boolean).map((block) => {
        const lines = block.split("\n");
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

  // ---------------------------------------------------------------- sidebar e stato
  function renderHistory() {
    historyEl.innerHTML = state.sessions.length ? '<div class="group">Sessioni</div>' : "";
    state.sessions.forEach((s) => {
      const b = document.createElement("button");
      b.textContent = s.preview || s.id;
      b.title = `${s.id} · ${s.count} messaggi`;
      if (s.id === state.session) b.setAttribute("aria-current", "true");
      b.onclick = async () => {
        if (busy) return;
        try { apply(await api("/api/session/resume", { id: s.id })); } catch (e) { toast(e.message); }
        app.classList.remove("side-open");
      };
      historyEl.appendChild(b);
    });
    $("model").textContent = state.model || "…";
  }

  function apply(newState) {
    state = newState;
    renderHistory();
    thread.innerHTML = "";
    if (!state.messages.length) return renderWelcome();
    state.messages.forEach((m) => thread.appendChild(m.role === "user" ? userNode(m.content) : botNode(m.content)));
    scrollDown();
  }

  async function newChat() {
    if (busy) return;
    try { apply(await api("/api/session/new", {})); } catch (e) { toast(e.message); }
    input.focus();
  }

  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 4000);
  }

  // ---------------------------------------------------------------- messaggi
  function renderWelcome() {
    thread.innerHTML = `
      <div class="welcome">
        <h1>Da dove vuoi iniziare?</h1>
        <p>Scrivi una richiesta: l'agente principale decide se rispondere da solo o delegare a un subagent.</p>
        <div class="chips">${SUGGESTIONS.map(([t, d], i) => `<button class="chip" data-i="${i}"><b>${t}</b>${d}</button>`).join("")}</div>
      </div>`;
    thread.querySelectorAll(".chip").forEach((el) => { el.onclick = () => send(SUGGESTIONS[el.dataset.i][0]); });
  }

  function userNode(text) {
    const d = document.createElement("div");
    d.className = "msg user";
    d.innerHTML = '<div class="bubble"></div>';
    d.firstChild.textContent = text;
    return d;
  }

  function botNode(text) {
    const d = document.createElement("div");
    d.className = "msg bot";
    d.innerHTML = '<div class="bot-avatar"></div><div class="bot-body"><div class="steps"></div><div class="prose"></div></div>';
    if (text != null) { d.querySelector(".prose").innerHTML = md(text); addActions(d, text); }
    return d;
  }

  function addActions(node, text) {
    const a = document.createElement("div");
    a.className = "actions";
    a.innerHTML = `<button>${icons.copy}Copia</button>`;
    a.firstChild.onclick = (e) => {
      navigator.clipboard?.writeText(text);
      const btn = e.currentTarget;
      btn.innerHTML = `${icons.check}Copiato`;
      setTimeout(() => (btn.innerHTML = `${icons.copy}Copia`), 1500);
    };
    node.querySelector(".bot-body").appendChild(a);
  }

  function setBusy(v) {
    busy = v;
    sendBtn.classList.toggle("busy", v);
    sendBtn.setAttribute("aria-label", v ? "Interrompi" : "Invia");
    sendBtn.disabled = v ? false : !input.value.trim();
  }

  // ---------------------------------------------------------------- passaggi dell'agente (eventi reali)
  function stepNode(ev) {
    const s = document.createElement("div");
    s.className = "step";
    s.dataset.id = ev.id;
    s.innerHTML = '<span class="tag"></span><span class="lbl"></span><span class="state"><span class="spin"></span></span>';
    s.querySelector(".tag").textContent = ev.name;
    s.querySelector(".tag").classList.toggle("amber", ev.kind === "subagent");
    s.querySelector(".lbl").textContent = ev.label || (ev.kind === "subagent" ? "delegato" : "strumento in uso");
    return s;
  }

  function sourcesNode(sources) {
    const d = document.createElement("div");
    d.className = "sources";
    d.innerHTML = '<div class="sources-title">Fonti</div>';
    sources.forEach((s) => {
      const a = document.createElement("a");
      a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = s.title || s.domain || s.url;
      a.title = s.url;
      const dom = document.createElement("span");
      dom.textContent = s.domain || "";
      a.appendChild(dom);
      d.appendChild(a);
    });
    return d;
  }

  // Rivela la risposta (già completa) in modo rapido, così un testo lungo non compare di colpo.
  function reveal(text, prose) {
    return new Promise((resolve) => {
      let i = 0;
      prose.classList.add("caret");
      const step = Math.max(4, Math.ceil(text.length / 120));
      (function tick() {
        if (!busy) { i = text.length; }   // interrotto: mostra tutto
        i = Math.min(text.length, i + step);
        prose.innerHTML = md(text.slice(0, i));
        scrollDown();
        if (i < text.length) return setTimeout(tick, 16);
        prose.classList.remove("caret");
        resolve();
      })();
    });
  }

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    if (!thread.querySelector(".msg")) thread.innerHTML = "";
    thread.appendChild(userNode(text));
    input.value = ""; autosize();

    const node = botNode(null);
    const steps = node.querySelector(".steps"), prose = node.querySelector(".prose");
    prose.innerHTML = '<span class="thinking" aria-label="L\'agente sta pensando"><i></i><i></i><i></i></span>';
    thread.appendChild(node);
    scrollDown();
    setBusy(true);
    controller = new AbortController();

    const finish = (id, error) => {
      const el = steps.querySelector(`[data-id="${CSS.escape(id)}"]`);
      if (el) el.querySelector(".state").innerHTML = error ? icons.x : icons.check;
      if (el && error) el.title = error;
    };

    let answered = false, failed = null;
    try {
      const res = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }), signal: controller.signal,
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

          if (ev.type === "step" && ev.phase === "start") {
            if (!steps.children.length) prose.innerHTML = "";
            steps.appendChild(stepNode(ev)); scrollDown();
          } else if (ev.type === "step") {
            finish(ev.id, ev.error);
          } else if (ev.type === "answer") {
            answered = true;
            steps.querySelectorAll(".spin").forEach((sp) => sp.parentElement.innerHTML = icons.check);
            prose.innerHTML = "";
            await reveal(ev.text, prose);
            const body = node.querySelector(".bot-body");
            if (ev.sources?.length) body.appendChild(sourcesNode(ev.sources));
            addActions(node, ev.text);
            if (ev.metrics) { const m = document.createElement("div"); m.className = "metrics"; m.textContent = ev.metrics; body.appendChild(m); }
          } else if (ev.type === "notice") {
            toast(ev.message);
          } else if (ev.type === "error") {
            failed = ev.message;
          }
        }
      }
    } catch (e) {
      if (e.name === "AbortError") {
        prose.classList.remove("caret");
        if (!answered) prose.innerHTML = "<p><i>Risposta interrotta. L'agente può finire in background e la risposta resta salvata nella sessione.</i></p>";
      } else {
        failed = e.message;
      }
    }

    if (failed) {
      steps.querySelectorAll(".spin").forEach((sp) => sp.parentElement.innerHTML = icons.x);
      prose.classList.remove("caret");
      prose.innerHTML = `<div class="error"><b>Errore.</b> ${esc(failed)}</div>`;
    }
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
  $("newChat").onclick = () => { newChat(); app.classList.remove("side-open"); };
  $("openSide").onclick = () => app.classList.add("side-open");
  $("closeSide").onclick = $("scrim").onclick = () => app.classList.remove("side-open");

  // Avvio: carica lo stato dal backend (stessa memoria della CLI).
  renderWelcome();
  api("/api/state").then(apply).catch(() => {
    thread.innerHTML = '<div class="welcome"><h1>Backend non raggiungibile</h1><p>Avvia il server con <code>python -m deep_agents.server</code> e apri l\'indirizzo che stampa, invece di aprire il file HTML direttamente.</p></div>';
  });
  input.focus();
})();
