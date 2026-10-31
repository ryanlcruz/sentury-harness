# Modelos

## RobinBandit

O [RobinBandit](https://github.com/ryanlcruz/RobinBandit) gerencia
provedores, contas e a escolha de modelo. Ele mora em
`sentury/plugins/robinbandit/` e se instala da pasta local.

Três modos, escolhidos na tela de Configurações:

| Modo | Como escolhe |
|---|---|
| Router | escolhe por disponibilidade, desempenho e qualidade observada, e aprende com o uso |
| Reforçado | começa no provedor que você escolheu e usa outro se ele falhar |
| Dedicado | usa só as contas que você escolheu |

| Provedor | Como entra |
|---|---|
| Claude | chave de API |
| Claude Code | o login do aplicativo, sem chave |
| Codex | o login do ChatGPT, sem chave |
| Gemini | chave de API |
| Groq | chave de API |
| OpenRouter | chave de API, com acesso a muitos modelos |
| Compatível com OpenAI | qualquer serviço que fale a mesma API, inclusive local |

As telas de Runtime mostram os provedores, o catálogo de modelos, os servidores
MCP e o catálogo de ferramentas.

A escolha vale o turno inteiro: mudar no meio vale no próximo. Algumas contas
usam o login do aplicativo oficial do provedor; outras usam chave de API. As
chaves moram no cofre do RobinBandit, em `~/.robinbandit/`.

Mais detalhes: [README do RobinBandit](../sentury/plugins/robinbandit/README.md).

## Esforço

O esforço é uma escolha separada do modo: Automático, Leve, Médio ou Profundo.
Veja [Conversa e interface](conversa.md#esforço).

## Chamada de ferramenta

Onde a API do provedor tem chamada de ferramenta nativa, o Sentury usa. Num
provedor sem ela, o modelo escreve a chamada no texto e o Sentury interpreta;
os dois caminhos passam pelo mesmo laço e pelas mesmas permissões.

## O que o Sentury não faz

O Sentury não escolhe esforço, perfil de modelo nem modo lendo palavras da
mensagem. Lista de palavras só reconhece algumas línguas escritas com a grafia
certa, e quem escreve diferente seria tratado diferente. Essa escolha volta a
existir quando houver um modelo de classificação de verdade.
