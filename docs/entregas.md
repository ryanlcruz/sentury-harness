# Entregas e artefatos

Quando você pede um relatório, uma planilha, um gráfico ou um painel, o Sentury
entrega um arquivo de verdade, anexado à conversa e guardado na área
**Artefatos**. Esta página explica de onde o arquivo sai e o que é conferido
antes de ele chegar a você.

<p align="center">
  <img src="assets/demos/motion-artefatos.gif" width="720" alt="Animação de uma entrega: a análise vira arquivo, o arquivo é conferido e vira anexo; uma página com erro de script volta ao modelo para consertar">
</p>

## De onde sai o arquivo

Há dois caminhos.

O primeiro são as ferramentas de exportação (`export_pdf`, `export_xlsx`,
`export_csv`, `export_html` e `generate_chart`). Elas partem de um resultado já
calculado nesta conversa e refazem a conta a partir da receita dele (a
ferramenta e os argumentos usados), em vez de copiar números do texto que o modelo
escreveu. Sem um resultado calculado antes, não há o que exportar, e a
ferramenta diz isso.

O segundo é o código. Um script em `executar_python` que grava um arquivo
(`.png`, `.xlsx`, `.pdf`, `.html`, `.md` e outros) tem esse arquivo anexado à
resposta.

Nos dois caminhos o arquivo volta ao modelo com o lugar onde ficou, e ele
confere o arquivo antes de responder. Não há frase pronta de "arquivo gerado":
quem escreve a resposta é o mesmo modelo que fez o trabalho.

Os formatos reconhecidos e o tipo de cada um moram em
`sentury/policies/artefatos.yaml`. Um formato novo é uma linha nesse arquivo.

## Onde o arquivo fica

O arquivo é entrega para você, então fica na sua pasta de documentos, em
`Documentos/Sentury/`, e não dentro do projeto nem no estado interno do
Sentury. O nome nunca sobrescreve um arquivo que já está lá: o segundo
`grafico.png` vira `grafico-2.png`.

| Sistema | Pasta |
|---|---|
| Windows | a pasta Documentos que o sistema informa, inclusive quando o OneDrive a redireciona |
| Linux | a pasta de documentos declarada no XDG (`~/.config/user-dirs.dirs`), que já traz o nome traduzido; sem ela, `~/Documents` ou `~/Documentos` |
| macOS | `~/Documents` |
| Servidor sem pasta de documentos | `~/Sentury` |

Para outro lugar, defina `SENTURY_ARTEFATOS_DIR`. Quando você pede um caminho
("salve na pasta do projeto"), o arquivo vai para lá, com a permissão normal de
escrita.

A conversa guarda só onde o arquivo está, e o anexo lê o arquivo do disco ao
abrir. Apagar ou mover arquivos dessa pasta é seguro: nada do Sentury depende
deles, e o anexo de um arquivo que saiu de lá avisa onde ele estava.

## O que é conferido

Antes de anexar, o arquivo passa por uma checagem do formato:

| Formato | O que se confere |
|---|---|
| PDF | a assinatura do começo e o marcador de fim, para não entregar um PDF cortado |
| XLSX e PPTX | o pacote do Office: que o zip abre e tem a pasta de trabalho ou a apresentação dentro |
| CSV | que tem linhas e separador |
| PNG | que é PNG mesmo e tem tamanho |
| HTML e SVG | a estrutura mínima e, com o navegador disponível, que a página abre sem erro |

Uma página HTML que não abre volta ao modelo com o erro que o navegador
mostrou, para ele consertar, até duas vezes. O conserto que apaga boa parte do
conteúdo é recusado: melhor a página com defeito e o aviso do que uma página
limpa sem os dados. Os outros formatos chegam com o resultado da checagem
junto, e o anexo mostra o aviso quando algo falhou.

Número na resposta que não aparece em nenhum resultado de ferramenta da
conversa ganha aviso de valor sem origem. Veja [Conversa e interface](conversa.md).

## Gráficos

O gráfico em PNG é desenhado na sua máquina, com matplotlib. O serviço público
QuickChart só é usado com `SENTURY_QUICKCHART=true`, porque nesse caso os
dados do gráfico saem da máquina para o servidor dele. Um gráfico também pode
vir desenhado na própria conversa, pelo [painel](conversa.md#respostas-que-desenham).

## A área Artefatos

A área Artefatos guarda o que vale reabrir daqui a dias: arquivos produzidos e
planos que atravessam turnos. Uma tabela da conversa vai para lá quando você
clica em **Abrir no painel**, embaixo dela; nenhuma vai sozinha. Bloco de código
e passo intermediário ficam na conversa. Fechar uma aba não apaga o artefato;
descartar é uma ação separada. A regra completa está em
[Regra de artefatos](interface/regra-de-artefatos.md).
