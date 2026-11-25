/* Cliente da API (ver README.md). Todas as funções devolvem Promise com o JSON; erros viram `Error(mensagem)`. */

TA.api = (function () {
  const memo = new Map();

  async function get(path, params) {
    const url = '/api' + path + TA.util.qs(params);
    let res;
    try { res = await fetch(url, { headers: { Accept: 'application/json' } }); }
    catch (e) { throw new Error('Sem conexão com o servidor (' + e.message + ')'); }
    let body = null;
    try { body = await res.json(); } catch (e) { /* corpo vazio */ }
    if (!res.ok) throw new Error((body && body.error) || `HTTP ${res.status} em ${path}`);
    return body;
  }

  /** como `get`, mas lembra o resultado (use só para dados imutáveis: arquivos de runs já concluídos, configs) */
  function cached(path, params) {
    const key = path + TA.util.qs(params);
    if (!memo.has(key)) memo.set(key, get(path, params).catch((e) => { memo.delete(key); throw e; }));
    return memo.get(key);
  }

  /** parâmetros de intervalo do estado global (`TA.state.range`) */
  function rangeParams() {
    const since = TA.util.sinceOf(TA.state.range);
    return since ? { since } : {};
  }

  const enc = encodeURIComponent;
  return {
    get, cached, rangeParams,
    meta: () => get('/meta'),
    runs: (p) => get('/runs', { ...rangeParams(), ...p }),
    run: (id) => get('/runs/' + enc(id)),
    trace: (id) => get('/runs/' + enc(id) + '/trace'),
    span: (id, sid) => cached('/runs/' + enc(id) + '/spans/' + enc(sid)),
    file: (id, name) => get('/runs/' + enc(id) + '/files/' + enc(name)),
    sessions: (p) => get('/sessions', { ...rangeParams(), ...p }),
    session: (id) => get('/sessions/' + enc(id)),
    stats: (p) => get('/stats', { ...rangeParams(), ...p }),
    configs: () => get('/configs'),
    config: (hash) => cached('/configs/' + enc(hash)),
    configDiff: (a, b) => cached('/configs/diff', { a, b }),
    llmCalls: (p) => get('/llm_calls', { ...rangeParams(), ...p }),
    toolCalls: (p) => get('/tool_calls', { ...rangeParams(), ...p }),
  };
})();
