# Configuração

## Instalar

Você precisa de Python 3.13 e, para a interface, Node com npm.

```bash
bash scripts/instalar.sh          # Linux/Mac; no Windows: .\scripts\instalar.ps1
python sentury.py                 # interface e API em http://127.0.0.1:8000
```

O instalador prepara o ambiente Python, o navegador de reserva e a interface.
`--sem-navegador` e `--sem-interface` pulam essas partes. No fim ele confere o
que falta na máquina; para conferir de novo sem subir o agente:

```bash
python -m sentury.doctor          # ou --json; sai com 1 se falta algo
```

O mesmo passo a passo à mão:

```bash
python -m venv .venv                                   # Python 3.13
.venv/bin/pip install -e "./sentury/plugins/robinbandit[yaml,providers,auth]"
.venv/bin/pip install -e ".[dev]"                      # ".[extras]" traz navegador e embeddings
cd sentury/client && npm ci && npm run build
```

Outros jeitos de subir:

```bash
python sentury.py --dev           # interface com recarga durante o desenvolvimento
python sentury.py --api           # só a API; Swagger em /docs
```

Mudança no código Python pede reiniciar a API. Mudança na interface pede
`npm run build` e recarregar a página.

Com `--dev`, `http://localhost:5173/?atlas` abre o Atlas: a interface com dados
de exemplo, folha por folha (conversa, bloco vivo, passos, sinais, estados,
Escritório). A folha Vitrine tem as cenas usadas nas imagens do README. Serve para ver e ajustar a tela sem depender de um modelo.

## Contas de modelo

Copie `.env.example` para `.env` e configure só os provedores que vai usar.
Uma conta basta para começar. Uma chave com várias contas vai separada por
vírgula. Sem conta configurada, a interface abre em modo de demonstração. As
contas também se cadastram pela tela de Configurações.

## Variáveis que mudam comportamento

| Variável | Padrão | O que faz |
|---|---|---|
| `SENTURY_HOME` | `~/.sentury` | onde mora o estado da máquina: memória, skills, sessões, permissões |
| `SENTURY_ARTEFATOS_DIR` | `Documentos/Sentury` | onde ficam os arquivos que o Sentury entrega (veja [Entregas](entregas.md#onde-o-arquivo-fica)) |
| `SENTURY_AUTOLEARN` | `true` | liga a revisão que guarda memória e skills |
| `SENTURY_APRENDER_A_CADA` | `10` | de quantas em quantas voltas a revisão acontece |
| `SENTURY_EMBEDDINGS` | `false` | busca vetorial local |
| `SENTURY_GEMINI_EMBEDDINGS` | `false` | busca vetorial pelo Gemini |
| `SENTURY_NAVEGADOR_CANAL` | `chrome` | o navegador que o Sentury abre sozinho: `chrome`, `msedge` ou `chromium` |
| `SENTURY_API_TOKEN` | vazio | token exigido pela API |
| `SENTURY_HQ_TOKEN` | vazio | token do HQ dos residentes |

O resto está comentado no `.env.example`.

## Mudar o comportamento sem caçar código

O que o Sentury faz mora em arquivos de dado:

| Arquivo | O que muda |
|---|---|
| `sentury/tools/tools.yaml` | as ferramentas, a orientação de cada uma e o efeito |
| `sentury/policies/shell.yaml` | o que o shell pode rodar |
| `sentury/context/base/*.md` | os textos que vão ao modelo |
| `sentury/skills/` | as skills que vêm com o Sentury |
| `sentury/client/src/domain/blocoVivo/apps.json` | os programas com ícone e cor no painel |
| `sentury/domains/setores/` | os setores (pacotes de área) |

Veja também [Onde mora cada coisa](ONDE-MORA-CADA-COISA.md).

Pela interface, o Context Engine mostra a identidade do Sentury, o contrato
central e os playbooks que vão ao modelo; os playbooks são editáveis ali mesmo,
e uma edição concorrente não apaga a outra.

O [Tato Runtime](https://github.com/ryanlcruz/tato-runtime) leva o
computador e o navegador do Sentury a outros agentes, como servidor MCP.

## Voz e Telegram

A ligação por voz em tempo real usa o Gemini Live e precisa de
`GEMINI_API_KEY`. A chave fica no servidor, e o navegador fala só com o Sentury.
Você pode interromper a fala do agente, e no meio da ligação ele consulta dado
real com as ferramentas de leitura. Também dá para ditar no campo de mensagem.

O Telegram se configura na tela de canais. Por ele você conversa com o Sentury,
chama um residente pelo nome, acompanha tarefas e aprova pedidos de permissão
com um botão, sem abrir a interface.
