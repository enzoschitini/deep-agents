Aqui vai a comparação atualizada com os três.

| | `system_prompt=` | `memory=["AGENTS.md"]` | `HarnessProfile` |
|---|---|---|---|
| **Onde fica** | Uma string no código Python | Um arquivo (ou vários) no backend | Um objeto registrado com `register_harness_profile(...)` |
| **O que segue** | A chamada do `create_deep_agent` | O projeto | O **modelo** escolhido |
| **Quando se aplica** | Sempre, em toda chamada em que você o passa | Sempre, nos arquivos listados em `memory=` | Automaticamente, quando o modelo correspondente é selecionado |
| **Papel** | Define quem o agente é e como se comporta | Dá contexto sobre o projeto (convenções, comandos, fatos) | Ajusta o comportamento para as manias de cada modelo |
| **O que pode conter** | Texto de instrução | Texto em markdown | Prompt base, sufixo de prompt, descrições de ferramentas reescritas, ferramentas ou middleware a excluir, middleware extra e ajustes no subagente general-purpose |
| **Quem edita** | Você, no código | Você ou o time, sem mexer no código | Você, no código (ou empacotado como plugin) |
| **Carregamento** | Instrução base | `MemoryMiddleware`, na inicialização | Aplicado pelo `create_deep_agent` conforme o modelo |

**Exemplo de divisão:**

- **System prompt:** "Você é um pesquisador especialista. Faça uma pesquisa completa e escreva um relatório polido."
- **AGENTS.md:** "Responda no idioma da pergunta. Termine sempre com uma lista de fontes. Não invente URLs."
- **HarnessProfile:** "Quando o modelo for `openai:gpt-6.1-sol`, acrescente ao prompt: 'Responda em menos de 100 palavras.'" (esse é o exemplo da própria página)

O system prompt e o AGENTS.md valem para o seu agente, qualquer que seja o modelo. O profile vale para um modelo específico, qualquer que seja o agente. Se você trocar de Gemini para Claude, o prompt e o AGENTS.md continuam iguais, e o profile do modelo antigo deixa de ser aplicado.

O `HarnessProfile` só vale a pena quando você usa mais de um modelo e algum deles precisa de um empurrão que os outros não precisam. Por exemplo, se um modelo ignora a ferramenta de busca, você reescreve a descrição dela só para ele. No seu mini agent, com um modelo só, ele ainda não faz falta.

A página também fala em "semântica de merge" e em chaves de registro, mas só aponta para a página de Profiles. Não sei como o `base_system_prompt` do profile se combina com o seu `system_prompt=`, então confira isso lá antes de depender dele.

Sources: [Customize Deep Agents – seção Profiles](https://docs.langchain.com/oss/python/deepagents/customization#profiles)