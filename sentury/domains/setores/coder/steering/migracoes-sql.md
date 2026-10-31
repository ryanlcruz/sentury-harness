---
titulo: Migração de banco
quando: arquivos
arquivos:
  - "*.sql"
  - "**/migrations/*.py"
---

Migração é o único arquivo aqui que não dá para desfazer editando de volta:
quando ela roda em produção, o estado mudou. Então:

- toda migração de subida tem a de descida escrita junto, no mesmo commit;
- `DROP` e `ALTER ... DROP COLUMN` não entram na mesma migração que adiciona o
  substituto — duas migrações, dois deploys, com leitura dupla no meio;
- nada de `UPDATE` sem `WHERE` mesmo que a intenção seja a tabela inteira:
  escreva o `WHERE` que descreve a tabela inteira, para que a revisão veja que
  foi de propósito.
