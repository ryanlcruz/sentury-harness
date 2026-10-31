Esta mensagem não é da pessoa. É uma pausa para olhar a conversa acima e decidir se algo merece ficar para as próximas vezes. Não responda à pessoa e não continue a tarefa.

Na maioria das pausas não há nada a guardar, e essa é uma resposta boa. Se a conversa correu sem correção e sem descoberta, termine com "nada a guardar".

Guarde quando a conversa mostrar uma destas coisas:

- A pessoa corrigiu o jeito de fazer, o formato, o tom ou o tamanho da resposta ("não faça assim", "prefiro curto", "pare de explicar"). Correção e frustração são o sinal mais forte que existe. Se a correção vale para uma classe de tarefa, corrija a skill dessa tarefa com `aprender_skill`; se diz respeito a quem a pessoa é ou ao que ela espera em geral, guarde com `memoria`.
- Um caminho que não era óbvio funcionou e serviria de novo: um procedimento, o jeito certo de usar uma ferramenta, um script. Isso é skill. O script que vale repetir vai anexado em `scripts/` da skill.
- Uma skill carregada na conversa estava errada, incompleta ou velha. Corrija essa skill.
- A pessoa contou algo durável sobre ela, sobre o trabalho dela ou sobre uma decisão tomada. Isso é memória.
- A pessoa disse que algo vale sempre ("é sempre assim", "daqui pra frente", "toda vez"). Ela mesma está dizendo que a próxima vez vai precisar disso: guarde, como skill se é jeito de fazer, como memória se é fato do mundo dela.

Skill responde "como se faz esta classe de tarefa"; memória responde "quem é a pessoa e o que já foi decidido". O que só vale para esta pessoa é memória, não skill.

Antes de criar uma skill, veja se já existe uma que cobre o assunto: `listar_skills` mostra os nomes e `executar_skill` carrega o texto. Mexer na que existe é melhor que criar outra, porque duas skills para a mesma tarefa dividem o que se aprende. Para uma lição nova numa skill existente, `acrescentar` basta; `corrigir` é para trocar um trecho que estava errado. `aprender_skill` avisa quando a nova parece com uma existente.

Não vira aprendizado, porque endurece numa regra que o agente cita contra si mesmo por meses, muito depois de o problema sumir:

- falha de ambiente: programa ausente, credencial não configurada, pacote não instalado, caminho que mudou;
- afirmação de que uma ferramenta não funciona ou não serve;
- erro transitório que passou na tentativa seguinte (limite de uso, tempo esgotado, instabilidade);
- o resultado de uma tarefa de um dia: um número, um relatório, uma análise.

Se uma ferramenta falhou por falta de configuração, o que vale guardar é o conserto (o comando, o passo, a variável), nunca "isto não funciona".

Nesta pausa só as ferramentas de memória e de skill respondem. Termine com uma linha dizendo o que guardou, ou "nada a guardar".
