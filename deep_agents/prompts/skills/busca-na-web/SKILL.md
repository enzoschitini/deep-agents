---
name: busca-na-web
description: Use sempre que for pesquisar na internet com `internet_search` — para planejar as buscas, escrever boas queries, refinar resultados fracos e saber quando parar.
---

# Busca na web

Método para buscar com `internet_search` de forma coerente e produtiva. Siga na ordem.

## 1. Decomponha antes de buscar

- Quebre a pergunta nas sub-perguntas independentes que ela realmente tem (de 1 a 5; um fato simples tem uma só), cada uma com um ângulo diferente (definição, estado atual, números, comparação, críticas).
- Identifique o que é **estável** (conceitos) e o que é **volátil** (versões, preços, leis, notícias). O volátil exige fonte recente.
- Lance as buscas independentes todas juntas, na mesma rodada (chamadas de `internet_search` em paralelo). Só busque depois de ler os resultados quando a busca depender deles.

## 2. Escreva queries curtas e específicas

- Use 3 a 8 palavras-chave, não a pergunta inteira em linguagem natural.
- Inclua o nome exato do produto, biblioteca, órgão ou pessoa, e o ano quando o tema muda rápido.
- Use aspas para frases exatas (`"deep agents" skills`) e `site:` para restringir a uma fonte oficial (`site:docs.langchain.com`).
- Busque na língua em que a melhor fonte provavelmente está (documentação técnica costuma estar em inglês), mesmo que a resposta final seja em outro idioma.

## 3. Refine quando o resultado vier fraco

Nunca repita a mesma query. Mude uma coisa por vez:

| Problema | Ajuste |
|---|---|
| Resultados genéricos ou off-topic | Acrescente termo técnico ou nome exato; use aspas |
| Só blogs e agregadores | Restrinja com `site:` à fonte oficial |
| Resultado desatualizado | Acrescente o ano ou "latest"/"changelog" |
| Pouca coisa encontrada | Troque por sinônimo ou termo mais amplo |
| Resultados demais | Acrescente um termo que exclua o ruído |

## 4. Avalie as fontes

- Prefira primárias (documentação oficial, repositório, artigo científico, página da empresa) a secundárias.
- Anote a data de cada fonte; descarte ou sinalize a que estiver velha demais para o tema.
- Confirme afirmações importantes em pelo menos duas fontes independentes. Se divergirem, registre as duas versões.

## 5. Saiba quando parar

Pare quando cada sub-pergunta tiver resposta apoiada em fonte, ou depois de 2 refinamentos sem avanço em uma sub-pergunta. Nesse caso, diga que não encontrou em vez de preencher a lacuna com suposição.

## Erros comuns

- Colar a pergunta do usuário inteira como query.
- Fazer a mesma busca com palavras quase iguais.
- Parar na primeira fonte que "parece boa".
- Tratar o snippet do resultado como se fosse a página lida.
- Esquecer de registrar a URL de onde veio cada informação.
