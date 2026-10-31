# Como contribuir

Contribuição é bem-vinda: conserto, teste, ferramenta nova, setor, documentação ou uma pergunta.
Este guia leva de um clone limpo até um PR pronto para revisão.

## Escolher o que fazer

As issues marcadas `good first issue` e `help wanted` são as prontas para quem chega. Cada uma diz
por qual arquivo começar e quanto trabalho costuma dar. Uma issue está livre quando não tem pessoa
atribuída nem PR que a feche. Comente que vai pegá-la antes de começar, para ninguém fazer o mesmo
trabalho em paralelo; se em uma semana ninguém da manutenção responder, pode seguir.

Mudança grande pede conversa antes do código: ferramenta nova, mudança no laço do turno, na política
de permissão ou num contrato como o `DomainPack`. Abra uma issue com o problema, a proposta e o que
ela afeta, e espere um acordo sobre o rumo. Conserto pequeno e óbvio pode ir direto para PR.

Até o seu primeiro PR ser aceito, mantenha um aberto por vez. Depois, até três.

## Preparar o ambiente

O Sentury roda em Python 3.13 (o 3.14 ainda não roda a versão fixada do pandas). O script de
instalação cria o `.venv`, instala o roteador de modelos da pasta local e o resto das dependências:

```bash
# Windows (PowerShell)
.\scripts\instalar.ps1

# Linux e macOS
./scripts/instalar.sh

python sentury.py          # interface e API em http://127.0.0.1:8000
```

A interface fica em `sentury/client` (React, Vite, TypeScript). Ela instala exatamente o que está no
`package-lock.json`, e nenhum pacote roda script ao instalar:

```bash
cd sentury/client
npm ci
npm run build
```

Pacote novo, em Python ou no `npm`, é conversa na issue antes. Pacote do registro roda código na
máquina de quem instala, e o golpe mais comum é um nome quase igual ao de um pacote conhecido.

## Rodar os testes

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m pytest -q -n 4 tests
```

O `PYTHONUTF8=1` evita que os testes em paralelo quebrem quando o caminho da pasta tem acento. Ao
iterar, rode só o arquivo de teste afetado; a suíte inteira, uma vez no fim. Não edite arquivo
enquanto a suíte roda: alguns testes leem o código-fonte e falham por causa da edição.

O CI roda no Linux. Se você desenvolve no Windows, cuidado com o que muda entre os dois, como a barra
dos caminhos (`\` contra `/`) e a quebra de linha. Um teste que só passa num deles é um teste quebrado.

## O que um PR precisa ter

Um problema por PR. Conserto de bug vem com um teste que falha sem o conserto e passa com ele, e é
essa prova que a revisão procura primeiro. Teste que falha não se conserta afrouxando a asserção.

Comportamento mora em arquivo de dado, não em Python. Ferramenta nova e propriedade de ferramenta são
declaradas em `sentury/tools/tools.yaml`; texto que vai ao modelo fica nos `.md` de
`sentury/context/base/`; regra de comando fica em `sentury/policies/shell.yaml`. Uma lista de nomes cravada
no código é tratada como defeito na revisão.

| Onde | O que mora ali |
|---|---|
| `sentury/harness/` | O turno: laço, política, contexto e retomada |
| `sentury/exec/` | Execução isolada e a decisão de permissão de cada ação |
| `sentury/tools/` | As ferramentas, declaradas em `tools.yaml` |
| `sentury/residentes/` | Os agentes residentes: manifesto, fila, Mesa e decisões |
| `sentury/domains/` | Os setores plugáveis, cada um com o seu `DomainPack` |
| `sentury/client/` | A interface |

Comentário explica o porquê do código como ele é hoje, em uma ou duas frases, sem a história do
conserto, sem data e sem citar projeto de fora como inspiração. A mesma regra vale para docstring de
teste.

A escrita do projeto é português direto, em frase curta. Sem travessão como pontuação, sem emoji e
sem as fórmulas de texto gerado ("não é só X, é Y", "vale ressaltar", "robusto").

O título do commit e do PR segue `tipo: o que mudou`, em português, com `feat`, `fix`, `docs`,
`test` ou `refactor`. A descrição do PR parte do modelo que o GitHub abre sozinho: o que mudou, por
quê, e como você verificou, com o comando que rodou e o resultado.

## Uso de IA

Usar IA é bem-vindo, inclusive um agente abrindo o PR por você, e não precisa declarar. Quem abre o
PR responde por ele: entendeu cada linha, rodou os testes e sustenta a mudança na revisão. PR que o
autor não consegue explicar é fechado.

Se um agente trabalha por você, ele segue as mesmas regras. Antes de começar, confere que a issue
está livre e que você ainda não tem PR aberto além do limite:

```bash
gh issue view N --json closedByPullRequestsReferences,assignees
gh pr list --author @me --state open
```

Ele abre o PR pronto para revisão, não como rascunho, e não dá estrela no repositório por você: as
regras de uso do GitHub tratam estrela automatizada como manipulação de ranking.

## Segurança

Falha de segurança não vai em issue pública. O caminho está em [SECURITY.md](SECURITY.md).

## Licença

Ao contribuir, você concorda que a sua contribuição segue a licença do projeto, a
[MIT](LICENSE).
