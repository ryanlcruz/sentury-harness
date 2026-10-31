# Observabilidade

Mudar o Sentury é fácil, e por isso toda mudança precisa de um jeito de ser
medida. Cada turno deixa rastro, e há telas e comandos para ler esse rastro,
repetir turnos e comparar o antes e o depois.

## As telas

| Tela | O que mostra |
|---|---|
| Traces e intervenções | cada turno com as gerações do modelo, as ferramentas chamadas, a latência e as correções que o Harness fez (uma chamada repetida que ele pulou, um número sem origem que ganhou aviso) |
| Uso, limites e créditos | chamadas, fallbacks, requisições por minuto, latência e saldo de cada conta, como o RobinBandit informa |
| Evals | os casos de avaliação e o resultado da última rodada |
| Diagnósticos | verificações reais do ambiente, do armazenamento, do roteador e da voz, sem resultado inventado |
| Armazenamento da memória | onde a memória mora e quanto ocupa |

## Replay de turnos

Cada turno é gravado com o estado de entrada, as respostas do modelo, as
ferramentas chamadas e o resultado. O replay repete o turno contra o código de
hoje e compara: as mesmas ferramentas, na mesma ordem, com o mesmo efeito.
Leitura pode rodar de novo; o que age no mundo (escrever arquivo, rodar
comando, mandar mensagem) usa o resultado gravado, então repetir nunca toca o
mundo outra vez.

## Ciclo de mutação

Uma mudança no próprio Sentury (um prompt, uma regra, um trecho do laço) pode
ser tratada como experimento, em vez de ir direto para o código em uso.

<p align="center">
  <img src="assets/demos/motion-mutacao.gif" width="720" alt="Animação do ciclo de mutação: a mudança nasce numa cópia isolada, turnos gravados são repetidos antes e depois, e uma pessoa decide promover ou reverter">
</p>

| Etapa | O que acontece |
|---|---|
| Propor | abre o registro com o alvo e a hipótese, e cria uma cópia isolada do código (uma worktree do git) a partir do commit atual |
| Construir | a mudança é feita na cópia; sem diferença em relação ao original, não há o que avaliar |
| Avaliar | os turnos gravados são repetidos antes e depois da mudança, com as mesmas respostas do modelo, e o resultado fica no registro |
| Decidir | promover exige o nome de quem decidiu, e quem decide faz o merge com o diff na frente; nada é promovido sozinho |
| Reverter | tira a mudança, joga a cópia fora e guarda o motivo; o branch fica como evidência |

Reprovada não é apagada: o registro guarda o que foi tentado, o diff e o
motivo, para a próxima pessoa não repetir a mesma tentativa. Os registros ficam
em `sentury/mutation/registro/` (ou em `SENTURY_MUTATION_DIR`), criados na
primeira mutação.

O ciclo é uma biblioteca (`sentury/mutation/ciclo.py`), usada por código e por
testes. Nenhuma tela nem comando do Sentury o dispara.

## Avaliações

| Comando | O que faz |
|---|---|
| `python -m sentury.evals` | roda os casos de ouro, que cobrem o laço inteiro com um modelo simulado; é o que roda na suíte |
| `python -m sentury.evals.dos_tracos` | repete turnos gravados que alguém rotulou com o que eles provam |
| `python -m sentury.evals.ab_flags` | compara o mesmo conjunto de pedidos com uma flag ligada e desligada, com modelo de verdade |
| `python -m sentury.evals.aprendizado` | confere se a revisão periódica guarda o que devia, e só isso; `--live` usa um modelo de verdade |

## Atlas

Com `python sentury.py --dev`, `http://localhost:5173/?atlas` abre o Atlas: a
interface com dados de exemplo, folha por folha. Serve para ver e ajustar a tela
sem depender de um modelo, e a folha Vitrine tem as cenas das imagens do README.
