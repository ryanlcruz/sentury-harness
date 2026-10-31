# Setores

O Sentury é generalista. Um setor o especializa numa área de trabalho
(engenharia, atendimento, financeiro) sem criar outro agente: o motor é o
mesmo, e o setor é uma pasta que diz o que medir, como falar, que ferramentas
próprias usar e como se trabalha ali.

<p align="center">
  <img src="assets/demos/motion-setores.gif" width="720" alt="Animação de setores: um pacote com métricas, ferramentas, playbooks e servidores entra no motor, que é o mesmo para todos">
</p>

Correção feita no motor chega a todos os setores de uma vez. É o contrário de
manter um "Sentury para código" e um "Sentury para atendimento" separados, em
que cada conserto precisaria ser repetido.

## Ligar um setor

Na interface, em **Conhecimento > Setores**, cada setor mostra as métricas que
sabe medir e um botão **Ligar**. A escolha fica em `~/.sentury/setor.json`, da
sua máquina: dois computadores com o mesmo clone podem usar setores diferentes.
Sem escolha, vale `SENTURY_DOMAIN` (padrão `generalista`).

Trocar de setor no meio de uma conversa deixa uma marca no histórico, para o
modelo não ler as mensagens antigas como se fossem do setor novo.

## O que vem no repositório

| Setor | O que traz |
|---|---|
| `coder` | engenharia de software: métricas de cobertura, build e defeitos; playbooks de como mexer no código e de migração SQL; um servidor MCP de exemplo, desligado |

O `coder` é o exemplo do formato e mostra o mínimo, quase só declaração. Um
setor também pode trazer código próprio: ferramentas de análise, gerador de
dados de demonstração, skills, base de conhecimento e voz própria.

## O que é uma pasta de setor

```
sentury/domains/setores/meu-setor/
  pack.yaml      o que o setor é: métricas, fontes, capacidades, persona
  tools.py       ferramentas próprias, quando YAML não basta
  steering/      playbooks, cada um com a regra de quando entra no turno
  mcp.json       servidores MCP que o setor traz junto
  skills/        procedimentos do setor
```

Só o `pack.yaml` é obrigatório, e precisa de pelo menos uma métrica: um setor
que não sabe medir nada afirma mais do que sabe. Os valores de cada métrica
saem do dado, não do arquivo: o setor declara a coluna, e as categorias vêm de
uma consulta ao próprio dado.

| Parte | Como funciona |
|---|---|
| Ferramentas (`tools.py`) | ganham o prefixo do setor (`coder.status_do_build`), para dois setores não se apagarem; leitura roda direto e o resto pede aprovação como qualquer escrita; só o setor ativo carrega código, e um setor com defeito não derruba o Sentury |
| Playbooks (`steering/`) | entram por regra, não por busca: `sempre` (todo turno), `arquivos` (quando o turno toca um arquivo que casa com o padrão) ou `manual` (só quando alguém pede); há teto de tamanho por playbook e no conjunto |
| Servidores (`mcp.json`) | mesmo formato do `mcp.json` seu; somem junto com o setor; guardam só o nome da variável de ambiente, nunca a credencial |
| Ferramentas de outro setor | ficam fora da mesa: quem usa o generalista não recebe ferramenta de NPS |

O passo a passo completo, com exemplos de cada arquivo, está no
[LEIA-ME dos setores](../sentury/domains/setores/LEIA-ME.md).

## Um contrato, qualquer setor

Tudo que um setor pode dizer ao motor está no `DomainPack`
(`sentury/domains/pack.py`). Um teste de conformidade confere cada setor contra
esse contrato: só cita ferramenta que existe, as métricas são coerentes e a
ferramenta que o setor declara é dele. Um setor novo que passa no teste entra
sem mudar o comportamento do resto.
