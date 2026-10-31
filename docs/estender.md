# Estender o Sentury

Quase tudo que muda o comportamento do Sentury mora em arquivo de texto, não em
código. Trocar a descrição de uma ferramenta, liberar um comando, ligar um
gatilho ou ensinar um procedimento é editar um arquivo e salvar. O código
guarda o como (o laço, a permissão, o despacho); o arquivo declara o quê.

## Os arquivos que mudam o comportamento

| Arquivo | O que muda |
|---|---|
| `sentury/tools/tools.yaml` | cada ferramenta: descrição, orientação ao modelo, parâmetros, efeito (`leitura`, `escrita`, `destrutiva`) |
| `sentury/policies/shell.yaml` | o que o shell roda direto e o que pede aprovação |
| `sentury/policies/hooks.yaml` | gatilhos que rodam um comando quando algo acontece |
| `sentury/policies/artefatos.yaml` | os formatos de arquivo reconhecidos e a frase de quando ficam prontos |
| `sentury/policies/rotas.yaml` | as rotas de recuperação: que falha conhecida aponta para qual caminho |
| `sentury/context/base/*.md` | os textos que vão ao modelo: identidade, núcleo, como terminar o trabalho |
| `sentury/context/SOUL.md`, `PLANNER.md`, `RESPONDER.md`, `SUBAGENT.md` | ajustes de voz, de planejamento e de resposta por cima dos textos base |
| tela Context Engine | a identidade, o contrato central e os playbooks que vão ao modelo, editáveis na interface |
| `sentury/domains/setores/<nome>/` | um setor: métricas, persona, ferramentas e playbooks próprios |
| `~/.sentury/mcp.json` | servidores MCP seus |
| `~/.sentury/skills/` | as skills que você ou o Sentury escreveram |

Os YAML são relidos quando o arquivo muda, sem reiniciar. Um arquivo ilegível
não derruba o Sentury: ele usa o padrão embutido e avisa no log.
`SENTURY_POLICIES_DIR` aponta os YAML de `policies/` para outra pasta.

O que protege não se afrouxa por arquivo. A lista do que nunca roda, a ordem da
permissão e a redação de segredos ficam no código, e nenhum arquivo de dado
(nem o próprio Sentury) consegue abrir o que elas fecham. Veja
[Segurança e permissões](seguranca.md).

## Hooks

Uma instrução no prompt ("rode os testes depois de editar") é um pedido: o
modelo pode esquecer, justamente quando errou. Um hook roda porque o evento
aconteceu, e o resultado volta para o agente ler no mesmo turno.

<p align="center">
  <img src="assets/demos/motion-hooks.gif" width="720" alt="Animação de um hook: o agente edita um arquivo, o evento dispara o hook, o comando passa pela permissão do shell e o resultado volta ao agente">
</p>

Os hooks moram em `sentury/policies/hooks.yaml`:

```yaml
hooks:
  - nome: testes-apos-edicao
    quando: arquivo_alterado
    padrao: "*.py"
    comando: python -m pytest -q
    descricao: Roda a suíte quando um arquivo Python é alterado
    timeout_s: 120
    ativo: true
```

| Campo | O que é |
|---|---|
| `quando` | o evento: `arquivo_alterado` (uma ferramenta escreveu, editou ou gerou um arquivo) ou `ferramenta_concluida` (uma ferramenta terminou) |
| `padrao` | glob do arquivo, comparado com o caminho inteiro e com o nome (`*.py` pega `app/rota.py`) |
| `ferramenta` | dispara só para esta ferramenta; vazio vale para qualquer uma |
| `comando` | o que roda, no shell |
| `timeout_s` | quanto esperar; passando disso, o comando segue em segundo plano e o agente recebe o id para acompanhar em `processos` |
| `ativo` | os exemplos do repositório vêm todos com `false` |

O comando de um hook passa pela mesma permissão de qualquer comando. Declarar o
hook diz quando ele roda, não dá o direito de rodar: se o comando altera algo e
você ainda não autorizou, ele não roda e o agente fica sabendo. O resultado
chega ao agente como observação ("rodou por causa do que você acabou de
fazer"), com o fim da saída. Um teste que quebrou não derruba o turno; o
agente decide o que fazer com a informação.

## Setores

Um setor especializa o Sentury numa área sem copiar o motor: o que medir, como
falar, ferramentas próprias, playbooks e servidores MCP. Veja
[Setores](setores.md).

## Skills

Uma skill é um procedimento em Markdown que o Sentury lê quando a tarefa pede.
Solte uma pasta com `SKILL.md` em `~/.sentury/skills/`, ou peça ao próprio
Sentury para escrever uma. Veja [Memória e aprendizado](aprendizado.md).

## Servidores MCP

Ferramentas de outro serviço entram por um servidor MCP declarado em
`~/.sentury/mcp.json`, com a mesma permissão das ferramentas do Sentury. Veja
[Ferramentas](ferramentas.md#ferramentas-suas-mcp).

## Modelos

Provedores, contas e modos moram no RobinBandit, o roteador de modelos, com
painel próprio. Veja [Modelos](modelos.md).

## Toda mudança se mede

Antes de confiar numa mudança de comportamento, dá para medir: a suíte de
testes, os casos de ouro (`python -m sentury.evals`), o replay de turnos
gravados e a comparação de uma flag ligada e desligada. Veja
[Observabilidade](observabilidade.md).
