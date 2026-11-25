/* Inicialização: monta o shell e liga o roteador. Fica por último (ordem alfabética). */
(function () {
  function start() {
    const view = TA.shell.mount(document.getElementById('app'));
    TA.router.start(view);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
