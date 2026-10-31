"""Agentes residentes: colegas persistentes que o Sentury cria e que moram na HQ.

Um residente tem identidade, objetivo, ferramentas próprias, memória e
orçamento. Existe depois da conversa que o criou e dorme até uma tarefa
chegar. Morar não é rodar o tempo todo: a fila acorda o worker, ele roda os
turnos da tarefa e volta a dormir.

Tudo mora em disco, sob `$SENTURY_HOME/residentes/`:

    agentes/<nome>/manifesto.json   quem é e o que pode
    agentes/<nome>/memoria.md       o que ele aprendeu e quer lembrar
    agentes/<nome>/workspace/       a pasta de trabalho dele
    tarefas/<id>.json               a fila, de todos os agentes
"""
