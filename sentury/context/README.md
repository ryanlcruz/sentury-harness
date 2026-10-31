# Textos que vão ao modelo

Esta pasta guarda o que o Sentury diz ao modelo, em Markdown, para mudar o tom
ou uma orientação sem mexer em código.

| Arquivo | O que é |
|---|---|
| `base/*.md` | os textos de base: identidade, núcleo do agente, como terminar o trabalho, a revisão do aprendizado |
| `SOUL.md` | ajuste de identidade, voz e postura de análise, por cima da base |
| `PLANNER.md` | preferências de planejamento |
| `RESPONDER.md` | preferências da resposta final |
| `SUBAGENT.md` | o formato do resumo que um subagente devolve |

Os arquivos são UTF-8, têm teto de tamanho (`SENTURY_PROMPT_CONTEXT_MAX_CHARS`)
e são relidos quando mudam. `SENTURY_PROMPT_CONTEXT_ENABLED=false` desliga os
ajustes por cima da base, e `SENTURY_PROMPT_CONTEXT_DIR` aponta para outra pasta.

Política, permissão, lastro e uso de ferramenta não se afrouxam por aqui: essas
regras ficam no código, e um texto desta pasta não as desliga.
