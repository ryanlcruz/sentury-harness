<!-- Título: `tipo: o que mudou`, em português (feat, fix, docs, test ou refactor).
     Descreva o estado final e o porquê, não as voltas que o trabalho deu. -->

Fecha #

## O que mudou

## Por que

<!-- O problema que isso resolve. Para comportamento novo de ferramenta, modelo ou permissão,
     diga como você mediu: o teste, o replay ou a bancada, e o que mostraram. -->

## Como verifiquei

<!-- Preencha com o comando e o resultado, para quem revisa poder repetir. -->

- **Testes**: `PYTHONUTF8=1 python -m pytest -q -n 4 tests`:
- **Sistema**:
- **Interface** (se mexeu em `sentury/client`): `npm run build`:

- [ ] Um teste falha sem esta mudança e passa com ela
- [ ] Comportamento novo está declarado em arquivo de dado (`tools.yaml`, `sentury/policies/`, `sentury/context/base/`), não cravado no código
- [ ] Os comentários explicam o porquê, sem a história do conserto
- [ ] Nenhuma chave, token ou senha, e nenhum pacote novo sem conversa antes na issue
