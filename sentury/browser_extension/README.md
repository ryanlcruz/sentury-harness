# Tato no Chrome (prévia local)

Esta extensão liga o navegador **já aberto no perfil do usuário** ao agente. Cada conversa ganha uma aba criada pela extensão e colocada num grupo com o nome de quem está usando (`Claude Code 1a2b3c4d`, `Sentury 1a2b3c4d`). Ao criar ou reabrir a aba, o Chrome vem para a frente. Ações posteriores continuam na mesma aba sem roubar o foco. Se você fechar a aba, o agente para e pede para reabrir. Reiniciar o servidor não fecha a aba.

Nas abas próprias, uma borda, uma seta e um balão mostram o que o agente está fazendo: nas cores do Tato, ou em amarelo quando é a Sentury. Elas não são injetadas nas demais abas, não interceptam cliques e são ocultadas durante a captura de imagem para não contaminar a leitura do agente. A faixa do próprio Chrome ("Tato começou a depurar este navegador") fica enquanto a aba está sendo usada.

## Instalação manual

1. Inicie o Sentury (porta 8000), o Tato (porta 47812) ou os dois.
2. No Chrome, abra `chrome://extensions`, ative **Modo do desenvolvedor**, escolha **Carregar sem compactação** e selecione esta pasta.
3. Pronto: a extensão se conecta sozinha em até um minuto (o ícone mostra **Conectado ao Tato**). O servidor reconhece o ID fixo desta extensão, definido pela `key` do `manifest.json`.

Se o servidor abrir depois do Chrome, a conexão vem na tentativa seguinte, ou na hora pelo botão **Tentar agora** do ícone. Com o Sentury e o Tato abertos, a extensão fica ligada aos dois ao mesmo tempo, e cada aba atende só a quem a abriu.

Sem a extensão conectada, o navegador aguarda a conexão: o agente **não troca silenciosamente** para um Chromium isolado nem perde o contexto da aba. O provedor Playwright continua disponível apenas por seleção explícita para testes e ambientes isolados; não é a mesma sessão logada do Chrome.

## Limite de acesso e segurança

A extensão pede a permissão `debugger`, que **tecnicamente é ampla no Chrome**. Não é uma permissão de aba única concedida pelo navegador. O limite de abas é imposto pelo nosso código: ele só guarda IDs retornados por `chrome.tabs.create`, não aceita ID de aba vindo do agente ou da API, e não assume uma aba vizinha quando a sua é fechada. A conexão WebSocket exige código local de uso único; depois usa um token guardado na extensão. O backend valida URLs de navegação e redirecionamentos antes de liberá-los.

Por enquanto esta é uma prévia: ainda precisa de verificação manual no Chrome instalado, especialmente em sites com pop-ups, downloads e autenticação. Não instale a extensão sem aceitar essa permissão e revisar o código se desejar. Ela é Chrome/Chromium; outros navegadores padrão ainda não são suportados.
