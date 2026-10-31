# Setores

Um Sentury, muitos pacotes. Especialidade não ganha um agente próprio: um
`sentury-coder` seria uma cópia do motor, e correção feita numa não chegaria
nas outras.

Cada pasta aqui é um setor. Ligar é `SENTURY_DOMAIN=<nome>`; desligar é trocar
por outro ou tirar a pasta.

```
dominios/
  coder/
    pack.yaml      o que o setor é      (obrigatório)
    persona.md     como ele fala        (opcional)
    tools.py       o que ele sabe fazer (opcional)
    skills/        procedimentos        (opcional)
```

## `pack.yaml` — o que o setor é

```yaml
nome: coder

metricas:
  cobertura:
    label: Cobertura de testes
    unidade: "%"
    fonte: suite de testes
    descricao: Percentual de linhas cobertas.
    maior_melhor: true
    grupo: operacao        # ou `experiencia`, para percepção de quem usa

fontes: [repositorio, ci]
capacidades: [ler_arquivo, editar_arquivo]
persona_arquivo: persona.md
```

Pacote sem métrica nenhuma é recusado: um agente que fala de um setor sem
saber medir nada dele afirma mais do que sabe.

## `tools.py` — o que ele sabe fazer

YAML não declara uma API interna. Para isso, código:

```python
def registrar(api):
    async def status_do_build(argumentos):
        return {"ok": True, "fila": 3}

    api.ferramenta(
        "status_do_build",
        status_do_build,
        descricao="Estado da fila de build.",
        categoria="conhecimento",
        quando_usar=["build pipeline deploy"],
    )
```

O nome ganha o prefixo do setor (`coder.status_do_build`) — dois pacotes podem
chamar a mesma coisa de `status`, e sem o prefixo o segundo apagaria o
primeiro em silêncio.

`categoria` decide o que o Harness exige: `conhecimento` é leitura e roda
direto; `execucao` e `acao` pedem autorização como qualquer outra escrita.

**Só o setor ativo tem o código carregado.** Ele roda no mesmo processo, então
carregar o de todos daria superfície que ninguém pediu. Pacote que quebra não
derruba o agente: não carrega, aparece no log, e o resto segue.

## `steering/` — como se trabalha no setor

Uma pasta com `.md`, cada um um playbook, cada um com a regra que decide se ele
entra no turno.

```markdown
---
titulo: Migração de banco
quando: arquivos
arquivos:
  - "*.sql"
  - "**/migrations/*.py"
---

Toda migração de subida tem a de descida escrita junto, no mesmo commit.
```

Três regras, e a diferença entre elas é o custo:

| `quando`   | entra                                    |
|------------|------------------------------------------|
| `sempre`   | em todo turno do setor                   |
| `arquivos` | quando o turno toca um arquivo que casa  |
| `manual`   | só quando alguém pede pelo nome          |

`sempre` ocupa prompt em todo turno — use para o que vale sem exceção, e deixe
`arquivos` para o que só importa perto de um certo tipo de código. Regra que o
Sentury não reconhece vira `manual`, porque uma regra que ninguém entende não
pode virar a mais cara por engano.

**Isto não é uma skill.** Skill é procedimento *recuperado*: o agente tem uma
dúvida, a busca acha, ele lê. Steering é contexto *injetado por regra*, porque
não é resposta a pergunta nenhuma — é o que vale sempre ali. Se dependesse da
busca, valeria só quando o agente já suspeitasse, e o valor dele está em chegar
antes da suspeita.

Há teto por playbook e no conjunto: um pacote não pode empurrar a conversa para
fora da janela de contexto de quem o instalou.

## `mcp.json` — servidores que o setor traz junto

Mesmo formato do `mcp.json` do usuário, para dar para testar copiando um bloco
que já funciona:

```json
{
  "servidores": [
    {
      "id": "github",
      "nome": "GitHub",
      "transporte": "stdio",
      "comando": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env_vars": ["GITHUB_TOKEN"],
      "ativo": false
    }
  ]
}
```

O `id` ganha o prefixo do pacote na leitura (`pacote:coder:github`), e o painel
recusa editar ou remover daqui: o servidor é do pacote e some junto com ele.
Gravá-lo no arquivo do usuário deixaria um servidor órfão quando o setor fosse
desinstalado, e impediria uma atualização do pacote de chegar em quem já
instalou.

`env_vars` declara só o **nome** da variável. O valor continua no ambiente de
quem instalou — um pacote nunca carrega credencial.

Prefira `ativo: false` no exemplo que vem no repositório: ligar sozinho subiria
um processo que ninguém pediu na primeira vez que alguém espia o setor.

## O que é do motor e o que é do setor

Ferramenta declarada com `setor` no registro só entra na mesa quando aquele
setor está ativo. O generalista recebia dezesseis de CX — `analyze_nps`,
`root_cause`, `executive_summary` — e oferecer NPS a quem desligou o setor de
propósito é ferramenta de domínio na mesa de quem não tem o domínio.

O que é genérico fica para todo mundo: `executar_python`, `generate_chart`,
`executar_comando`, a fila de ações. Consultar dado não é de CX: banco e
planilha da pessoa se consultam pelo `executar_python` ou pelo cliente do banco
no terminal.
