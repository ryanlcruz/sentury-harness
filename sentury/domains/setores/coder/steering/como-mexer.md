---
titulo: Como mexer no código deste time
quando: sempre
---

Antes de alterar algo que mais de um lugar usa, rode `codigo` com `acao: chamadas`
no sentido `chamado_por`. Menção não é dependência, e é o acoplamento longe do
lugar mexido que faz o teste quebrar onde ninguém procurou.

Depois de escrever ou editar, rode `diagnosticos` antes de rodar teste. A suíte
leva minutos e raramente aponta a linha; o diagnóstico leva milissegundos e
aponta.

Quando quebrar algo, `historico_do_arquivo` mostra como o arquivo estava antes.
Olhe o diff antes de restaurar — voltar o arquivo inteiro desfaz junto o que
tinha dado certo.
