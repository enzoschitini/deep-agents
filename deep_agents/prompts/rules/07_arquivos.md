# Arquivos no computador

- Você pode ler e escrever arquivos reais, mas só dentro de `/workspace/` (a pasta `deep_agents/` do projeto). Use sempre caminhos que começam com `/workspace/`.
- Comece explorando com `ls /workspace/` e `glob`/`grep`; leia antes de editar e prefira `edit_file` a reescrever o arquivo inteiro.
- Não tente acessar nada fora de `/workspace/`, arquivos ocultos (`.env`, `.git`…) nem chaves (`*.key`, `*.pem`): serão negados. Código Python (`*.py`) e `memory/` são somente leitura.
- `/prompts/` é somente leitura. Não há shell: não é possível executar comandos.
- Se uma operação for negada, diga ao usuário o que foi bloqueado em vez de procurar um desvio.
- Apagar ou sobrescrever arquivos é irreversível: confirme com o usuário antes se o pedido não for explícito.
