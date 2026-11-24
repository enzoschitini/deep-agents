// Chat UI statica: nessun backend, le risposte sono finte.
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

  // Risposte finte: ognuna ha i passaggi di delega e il testo finale.
  const REPLIES = [
    {
      steps: [["pesquisador", "Cerco fonti sul web", false], ["redator", "Scrivo la sintesi", true]],
      text: "Ho cercato tra le fonti più recenti e ho preparato una sintesi.\n\n**Cosa ho trovato**\n- L'agente principale pianifica il lavoro e lo divide in compiti piccoli.\n- Ogni subagent lavora in un contesto isolato, così la conversazione resta pulita.\n- Il risultato torna all'agente principale, che lo rilegge prima di risponderti.\n\nEcco un esempio minimo:\n\n```python\nagent = create_deep_agent(\n    model=model,\n    subagents=[pesquisador, redator],\n)\n```\n\nVuoi che approfondisca uno di questi punti?",
    },
    {
      steps: [["redator", "Scrivo una bozza", true]],
      text: "Ecco una prima bozza:\n\n> I subagent non sono un trucco di prompt. Sono un modo di tenere il contesto in ordine mentre il lavoro cresce.\n\nL'ho tenuta breve di proposito. Posso renderla più tecnica, più informale, oppure aggiungere un invito all'azione in chiusura.",
    },
    {
      steps: [["pesquisador", "Leggo la documentazione", false]],
      text: "Per ora questa è una risposta simulata, ma la struttura è quella vera: tu scrivi, l'agente decide a chi delegare, i subagent lavorano e tu vedi i passaggi mentre accadono.\n\nQuando collegheremo il backend, basterà sostituire la funzione `fakeReply()` con una chiamata reale.",
    },
  ];

  let chats = [];       // {id, title, messages:[{role, text}]}
  let current = null;
  let busy = false;
  let timers = [];
  let replyIdx = 0;

  const icons = {
    copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>',
    redo: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.6M20 5v6h-6"/></svg>',
    check: '<svg viewBox="0 0 24 24" class="check"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  };

  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  // Markdown minimale: blocchi di codice, elenchi, citazioni, grassetto, codice inline.
  function md(src) {
    const parts = src.split(/```(?:\w+)?\n?/);
    return parts.map((chunk, i) => {
      if (i % 2) return `<pre><code>${esc(chunk.replace(/\n$/, ""))}</code></pre>`;
      return chunk.trim().split(/\n{2,}/).filter(Boolean).map((block) => {
        const lines = block.split("\n");
        const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
        if (lines.every((l) => /^- /.test(l))) return `<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`;
        if (lines.every((l) => /^> /.test(l))) return `<blockquote>${lines.map((l) => inline(l.slice(2))).join("<br>")}</blockquote>`;
        return `<p>${lines.map(inline).join("<br>")}</p>`;
      }).join("");
    }).join("");
  }

  function scrollDown() { scroller.scrollTop = scroller.scrollHeight; }

  function renderHistory() {
    historyEl.innerHTML = chats.length ? '<div class="group">Recenti</div>' : "";
    chats.forEach((c) => {
      const b = document.createElement("button");
      b.textContent = c.title;
      b.title = c.title;
      if (c === current) b.setAttribute("aria-current", "true");
      b.onclick = () => { if (!busy) { open(c); app.classList.remove("side-open"); } };
      historyEl.appendChild(b);
    });
  }

  function renderWelcome() {
    thread.innerHTML = `
      <div class="welcome">
        <h1>Da dove vuoi iniziare?</h1>
        <p>Scrivi una richiesta: l'agente principale decide se rispondere da solo o delegare a un subagent.</p>
        <div class="chips">${SUGGESTIONS.map(([t, d], i) => `<button class="chip" data-i="${i}"><b>${t}</b>${d}</button>`).join("")}</div>
      </div>`;
    thread.querySelectorAll(".chip").forEach((el) => {
      el.onclick = () => send(SUGGESTIONS[el.dataset.i][0]);
    });
  }

  function userNode(text) {
    const d = document.createElement("div");
    d.className = "msg user";
    d.innerHTML = `<div class="bubble"></div>`;
    d.firstChild.textContent = text;
    return d;
  }

  function botNode(text) {
    const d = document.createElement("div");
    d.className = "msg bot";
    d.innerHTML = `<div class="bot-avatar"></div><div class="bot-body"><div class="steps"></div><div class="prose"></div></div>`;
    if (text != null) { d.querySelector(".prose").innerHTML = md(text); addActions(d, text); }
    return d;
  }

  function addActions(node, text) {
    const a = document.createElement("div");
    a.className = "actions";
    a.innerHTML = `<button data-a="copy">${icons.copy}Copia</button><button data-a="redo">${icons.redo}Rigenera</button>`;
    a.querySelector('[data-a="copy"]').onclick = (e) => {
      navigator.clipboard?.writeText(text);
      const btn = e.currentTarget;
      btn.innerHTML = `${icons.check}Copiato`;
      setTimeout(() => (btn.innerHTML = `${icons.copy}Copia`), 1500);
    };
    a.querySelector('[data-a="redo"]').onclick = () => {
      if (busy) return;
      const last = current.messages.filter((m) => m.role === "user").pop();
      if (!last) return;
      current.messages.pop();
      node.remove();
      respond(last.text);
    };
    node.querySelector(".bot-body").appendChild(a);
  }

  function open(chat) {
    current = chat;
    thread.innerHTML = "";
    chat.messages.forEach((m) => thread.appendChild(m.role === "user" ? userNode(m.text) : botNode(m.text)));
    renderHistory();
    scrollDown();
  }

  function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }

  function setBusy(v) {
    busy = v;
    sendBtn.classList.toggle("busy", v);
    sendBtn.setAttribute("aria-label", v ? "Interrompi" : "Invia");
    sendBtn.disabled = v ? false : !input.value.trim();
  }

  function stepNode(agent, label, amber) {
    const s = document.createElement("div");
    s.className = "step";
    s.innerHTML = `<span class="tag ${amber ? "amber" : ""}">${agent}</span><span>${label}</span><span class="state"><span class="spin"></span></span>`;
    return s;
  }
  const finishStep = (s) => (s.querySelector(".state").innerHTML = icons.check);

  // Simula la risposta: pensiero, passi di delega, poi testo in streaming.
  function respond(userText) {
    const reply = REPLIES[replyIdx++ % REPLIES.length];
    const node = botNode(null);
    const steps = node.querySelector(".steps"), prose = node.querySelector(".prose");
    prose.innerHTML = '<span class="thinking" aria-label="L\'agente sta pensando"><i></i><i></i><i></i></span>';
    thread.appendChild(node);
    scrollDown();
    setBusy(true);

    let t = 700;
    const stepEls = [];
    reply.steps.forEach(([agent, label, amber]) => {
      later(() => {
        if (!stepEls.length) prose.innerHTML = "";
        const prev = stepEls[stepEls.length - 1];
        if (prev) finishStep(prev);
        const el = stepNode(agent, label, amber);
        stepEls.push(el); steps.appendChild(el); scrollDown();
      }, t);
      t += 1300;
    });

    later(() => {
      stepEls.forEach(finishStep);
      prose.innerHTML = "";
      stream(reply.text, prose, node);
    }, t);
  }

  function stream(text, prose, node) {
    let i = 0;
    prose.classList.add("caret");
    (function tick() {
      i = Math.min(text.length, i + 2 + Math.floor(Math.random() * 3));
      prose.innerHTML = md(text.slice(0, i));
      scrollDown();
      if (i < text.length) return later(tick, 18);
      prose.classList.remove("caret");
      current.messages.push({ role: "bot", text });
      addActions(node, text);
      setBusy(false);
      scrollDown();
    })();
  }

  function stop() {
    clearTimers();
    const last = thread.lastElementChild;
    if (last?.classList.contains("bot")) {
      const prose = last.querySelector(".prose");
      prose.classList.remove("caret");
      if (prose.querySelector(".thinking")) prose.innerHTML = "<p><i>Risposta interrotta.</i></p>";
      last.querySelectorAll(".spin").forEach((s) => s.parentElement.innerHTML = "");
      const text = prose.textContent.trim() || "Risposta interrotta.";
      current.messages.push({ role: "bot", text });
      addActions(last, text);
    }
    setBusy(false);
  }

  function send(text) {
    text = text.trim();
    if (!text || busy) return;
    if (!current) {
      current = { id: Date.now(), title: text.length > 38 ? text.slice(0, 38) + "…" : text, messages: [] };
      chats.unshift(current);
      thread.innerHTML = "";
      renderHistory();
    }
    current.messages.push({ role: "user", text });
    thread.appendChild(userNode(text));
    input.value = "";
    autosize();
    scrollDown();
    respond(text);
  }

  function newChat() {
    if (busy) stop();
    current = null;
    renderWelcome();
    renderHistory();
    input.focus();
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 200) + "px";
    if (!busy) sendBtn.disabled = !input.value.trim();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    busy ? stop() : send(input.value);
  });
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!busy) send(input.value); }
  });
  $("newChat").onclick = () => { newChat(); app.classList.remove("side-open"); };
  $("openSide").onclick = () => app.classList.add("side-open");
  $("closeSide").onclick = $("scrim").onclick = () => app.classList.remove("side-open");

  renderWelcome();
  input.focus();
})();
