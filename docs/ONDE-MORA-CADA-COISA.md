# Onde mora cada coisa

O que vai junto quando alguém clona o repositório, e o que fica só nesta
máquina. A regra é uma só: **declaração é do projeto, decisão é da máquina.**

## Vai junto no clone

Chega funcionando num PC novo.

| Arquivo | O que é |
|---|---|
| `sentury/policies/shell.yaml` | o que o shell pode rodar |
| `sentury/policies/hooks.yaml` | gatilhos por evento (todos desligados) |
| `sentury/policies/artefatos.yaml` | formatos que viram artefato |
| `sentury/policies/rotas.yaml` | rotas de recuperação de falhas conhecidas |
| `sentury/plugins/robinbandit/config/sentury.yaml` | provedores, tiers, regras de erro, cooldown |
| `sentury/domains/setores/*/pack.yaml` | os setores e suas métricas |
| `sentury/mutation/registro/*.json` | o que já foi tentado, e por quê (a pasta nasce na primeira mutação) |
| `sentury/evals/` | casos de avaliação e regressões |

O registro de mutação mora no repositório de propósito: é memória do projeto,
precisa ser revisável junto do diff e serve para a próxima pessoa não repetir a
tentativa. Veja [Ciclo de mutação](observabilidade.md#ciclo-de-mutação).

## Fica só nesta máquina

Em `~/.sentury/` e `~/.robinbandit/`. **Não vai no clone, e não se recria.**

| Arquivo | O que é | Por que não viaja |
|---|---|---|
| `permissoes.json` | o que você autorizou | permissão dada aqui não deve valer noutra máquina |
| `agendamentos.json` | rotinas agendadas | apontam para esta instalação |
| `mcp.json` | servidores MCP conectados | comando e caminho são locais |
| `contas.json` · `cofre.json` | contas e segredos | nunca versionar segredo |
| `memory/` · `skills/` · `state/` | memória, skills e sessões | são o histórico de quem usou |
| `~/.robinbandit/ranking.json` | o que o roteador aprendeu | medido com estas chaves, neste plano, nesta região |
| `~/.robinbandit/config.yaml` | preferências do roteador | sobrepõe o do repo sem exigir um fork |

## Num PC novo

Os YAMLs do sistema chegam e funcionam. O que é seu não existe lá: o agente
volta a perguntar autorização, e o bandit volta a medir do zero.

Isso não é perda: um ranking aprendido com as chaves de outra pessoa seria um
viés que ela nunca mediu, e uma permissão herdada seria uma autorização que
ninguém deu.

**Para levar junto de propósito**, copie `~/.sentury/` e `~/.robinbandit/` à mão.
Copie o `cofre.json` só se souber o que está fazendo: ele carrega segredo.
