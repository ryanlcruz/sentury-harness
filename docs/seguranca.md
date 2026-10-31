# Segurança e permissões

O modelo decide o próximo passo, mas não executa nada por conta própria. Antes
de cada ferramenta, o Sentury confere se ela existe, se está disponível naquele
turno e se precisa da sua aprovação. Trocar de modelo não muda essas regras.

## A ordem da decisão

Cada ação que muda algo passa por esta ordem, e a primeira que responde decide:

1. **O que nunca roda:** código baixado e executado na hora, tomada de
   privilégio (elevação, serviço novo, usuário novo) e o que destrói a máquina
   (formatar disco, apagar a raiz, mexer no boot). Recusado em qualquer modo,
   inclusive com "permitir tudo". A lista mora em `sentury/exec/hardline.py`.
2. **Alvo sensível:** caminho crítico do sistema pede confirmação desta vez.
3. **Negado por você:** o que você negou para sempre.
4. **Permitir tudo**, se ligado.
5. **Sempre:** o que você autorizou para sempre.
6. **Nesta conversa:** o que você autorizou na conversa.
7. **Uma vez:** a autorização desta vez, que se gasta ao usar.
8. **Perguntar:** um cartão na conversa.

Leitura comum segue direto. As permissões ficam em `~/.sentury/permissoes.json`,
nesta máquina; numa máquina nova, o Sentury volta a perguntar.

## O que pergunta sempre

Algumas ações pedem confirmação na hora, mesmo com "permitir tudo", "sempre" ou
"nesta conversa":

ação declarada `destrutiva` no `tools.yaml` (apaga ou não dá para desfazer), usar
o mouse e o teclado (`computador`, a cada turno), enviar, publicar, comprar ou se
candidatar pelo navegador, e instalar uma skill de fora.

Script é aprovado pelo conteúdo: se o arquivo muda depois da aprovação, a
pergunta volta.

## Texto de terceiros

Página, arquivo, resultado de busca e saída de comando entram no contexto
cercados como texto de fora: dado para ler, nunca instrução. Um pedido escrito
dentro de uma página não vira ordem. Skill instalada de fora entra como
procedimento, com o aviso de que foi escrita por terceiro e de que pedido para
mandar dado para fora ou mudar permissão não vem de você.

Texto de fora que tenta dar ordem ao agente ("ignore as instruções anteriores")
é reconhecido e marcado antes de chegar ao modelo.

## Rede

O navegador abre o que você abriria, endereço local inclusive: ele é o seu Chrome
(ou o Chromium na sua máquina), e validar a página que você está desenvolvendo é uso
comum. Só página em http ou https entra; `file://` e outros esquemas ficam de fora.

A `ler_pagina` e a `buscar_web` fazem a requisição pelo processo do Sentury, e o
resultado vai direto ao modelo. Na instalação local elas leem endereço local, que é
a sua própria máquina. Quando o Sentury roda como servidor (a HQ, que marca
`SENTURY_EM_SERVIDOR`), elas recusam endereço interno (rede do servidor, `localhost`,
metadados de nuvem), inclusive no meio de um redirecionamento: ali uma página lida
poderia mandar o agente buscar a credencial da própria máquina. Um site de teste local
passa no servidor pela lista `SENTURY_ORIGENS_LOCAIS_LIBERADAS`. O navegador dos
residentes, que roda na caixa isolada, recusa endereço interno sempre.

## Segredos

Chaves de provedor e contas moram no cofre do RobinBandit, em `~/.robinbandit/`
(no Windows, protegido pelo DPAPI). Nada de segredo vai para o repositório nem
para os arquivos de configuração do MCP, que guardam só o nome da variável. O
código que o Sentury roda recebe um ambiente sem as chaves da máquina, e
mensagens de erro e logs passam por redação de credencial.

## Rastro e medição

O histórico do trabalho fica na sua máquina e pode ser inspecionado. Testes de
replay repetem turnos gravados para conferir regressões sem repetir ações
reais. O Sentury não envia traces para um serviço de telemetria.
