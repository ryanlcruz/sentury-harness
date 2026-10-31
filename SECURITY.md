# Segurança

O Sentury roda comandos, lê e escreve arquivos e usa o navegador no computador da pessoa. Uma falha
que deixe uma ação passar sem a aprovação dela, vaze uma chave do cofre ou contorne a política de
permissão é tratada com prioridade.

## Como avisar

Não abra issue pública. Use o aviso privado do GitHub: na aba **Security** do repositório, clique em
**Report a vulnerability**. Só a manutenção vê o que você escrever ali.

Diga o que a falha permite, os passos para reproduzir e a versão ou o commit em que você viu. Se
tiver uma prova, mande junto, sem chave, token ou senha de verdade.

## O que esperar

A primeira resposta chega em até sete dias. Confirmada a falha, o conserto sai antes de qualquer
divulgação, e você combina com a manutenção quando o aviso público pode sair. Quem avisa com
responsabilidade recebe o crédito na correção, se quiser.

## O que está no escopo

O núcleo do Sentury: o laço do turno, a política de permissão, a execução isolada, o cofre de chaves,
as ferramentas, os agentes residentes, a extensão do navegador e a interface. Falha num pacote de
terceiro vai primeiro para o projeto dele; avise aqui também se o Sentury precisar se proteger
enquanto isso.
