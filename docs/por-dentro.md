# O Sentury por dentro

Boa parte do que o Sentury faz não aparece na tela: é a ordem em que as coisas
acontecem dentro de um turno. Esta página mostra cada mecanismo em movimento e
aponta onde ele está explicado em detalhe.

## O turno

<p align="center">
  <img src="assets/demos/motion-turno.gif" width="720" alt="Animação do turno: você pede, o modelo chama uma ferramenta, a permissão confere, a ferramenta roda e o resultado volta; uma escrita para num cartão até você aprovar">
</p>

Um modelo só decide o próximo passo e chama ferramentas. Toda chamada passa
pela permissão antes de rodar: leitura segue direto, escrita que você ainda não
autorizou vira um cartão. Quando você aprova, o turno continua do mesmo passo,
sem o modelo precisar pedir de novo. Veja [Conversa e interface](conversa.md).

## A ordem da permissão

<p align="center">
  <img src="assets/demos/motion-permissao.gif" width="720" alt="Animação da ordem da permissão: um comando atravessa oito etapas; o que nunca roda é recusado na primeira, um comando autorizado para sempre para na quinta, e o que nenhuma etapa responde vira cartão">
</p>

Oito etapas, e a primeira que responde decide. O que nunca roda (código
baixado e executado na hora, tomada de privilégio, destruir a máquina) é
recusado antes de qualquer outra, inclusive com "permitir tudo" ligado. Veja
[Segurança e permissões](seguranca.md).

## Hooks

<p align="center">
  <img src="assets/demos/motion-hooks.gif" width="720" alt="Animação de um hook: o agente edita um arquivo, o evento dispara o hook declarado, o comando passa pela permissão do shell e o resultado volta ao agente">
</p>

Uma instrução no prompt é um pedido que o modelo pode esquecer. Um hook roda
porque o evento aconteceu: o agente editou um `.py`, a suíte roda, e o
resultado volta para ele ler no mesmo turno. Veja [Estender o Sentury](estender.md#hooks).

## A revisão do aprendizado

<p align="center">
  <img src="assets/demos/motion-aprendizado.gif" width="720" alt="Animação da revisão: a cada dez voltas o Sentury revê a conversa, compara com o que já sabe e, quando há algo novo, grava na memória ou numa skill e avisa embaixo da resposta">
</p>

A cada dez voltas o próprio Sentury revê a conversa, com o mesmo modelo e só
com as ferramentas de memória e skill. Antes de gravar, compara com o que já
existe sem chamar modelo. Quase sempre não há nada novo; quando há, aparece
embaixo da resposta com desfazer. Veja [Memória e aprendizado](aprendizado.md).

## Rotas de recuperação

<p align="center">
  <img src="assets/demos/motion-rotas.gif" width="720" alt="Animação de uma rota: o sandbox nega um import, a rota diz ao modelo para usar um script que pede aprovação; uma recusa da política não ganha rota">
</p>

Quando uma ferramenta falha de um jeito conhecido, o resultado já traz o
caminho que funciona, para o modelo não insistir no mesmo erro nem desistir
respondendo só em texto. Recusa da política não ganha desvio. Veja
[Ferramentas](ferramentas.md#quando-uma-execução-falha).

## Entregas

<p align="center">
  <img src="assets/demos/motion-artefatos.gif" width="720" alt="Animação de uma entrega: a análise vira arquivo, o arquivo é conferido e vira anexo; uma página com erro de script volta ao modelo para consertar">
</p>

Relatório, planilha e painel saem do resultado calculado, não do texto que o
modelo escreveu. Antes de chegar a você, o arquivo é conferido: pacote do
Office íntegro, PDF completo, página que abre no navegador. Veja
[Entregas e artefatos](entregas.md).

## Setores

<p align="center">
  <img src="assets/demos/motion-setores.gif" width="720" alt="Animação de setores: um pacote com métricas, ferramentas, playbooks e servidores entra no motor, que é o mesmo para todos">
</p>

O motor é um só. Um setor é uma pasta que diz o que medir, como falar, que
ferramentas próprias usar e como trabalhar naquela área. Trocar de setor troca
o pacote, não o motor. Veja [Setores](setores.md).

## A caixa dos residentes

<p align="center">
  <img src="assets/demos/motion-caixa.gif" width="720" alt="Animação da caixa: a tarefa entra na fila do residente, ele trabalha numa caixa isolada cuja única saída para a rede é um proxy, e você vê a tela dele ao vivo">
</p>

Cada residente trabalha numa caixa própria, sem dividir disco, processo ou rede
com os outros. A única saída da caixa para a internet é um proxy que só deixa
passar os endereços aprovados. Veja [Residentes](residentes.md).

## O ciclo de mutação

<p align="center">
  <img src="assets/demos/motion-mutacao.gif" width="720" alt="Animação do ciclo de mutação: a mudança nasce numa cópia isolada, turnos gravados são repetidos antes e depois, e uma pessoa decide promover ou reverter">
</p>

Uma mudança no próprio Sentury nasce numa cópia isolada do código, é comparada
com turnos que já aconteceram e só entra com a decisão de uma pessoa. Veja
[Observabilidade](observabilidade.md#ciclo-de-mutação).
