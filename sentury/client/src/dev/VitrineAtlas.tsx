import React from 'react';
import { MessageBubble } from '../features/chat/MessageBubble';
import { ProcessingIndicator } from '../features/chat/ProcessingIndicator';
import { ChatMessage, CommandRun } from '../contracts/domain/session';
import { GoalCard } from '../features/chat/GoalCard';
import { respostaComCores, respostaDoHd } from './atlasBlocoVivo';
import { respostaCodigo, respostaProgramas } from './atlasVitrine';

/** As cenas que o README mostra. Cada uma fica numa caixa `data-cena`, para o
 * recorte pegar só ela. */
const voce = (id: string, content: string, timestamp: string): ChatMessage => (
  { id, sessionId: 'vitrine', role: 'user', content, timestamp });
const sentury = (id: string, content: string, timestamp: string, extra: Partial<ChatMessage> = {}): ChatMessage => (
  { id, sessionId: 'vitrine', role: 'assistant', content, timestamp, status: 'complete', ...extra });

const Cena: React.FC<{ nome: string; children: React.ReactNode }> = ({ nome, children }) => (
  <div data-cena={nome} className="mb-24 pt-2">{children}</div>
);

type Estado = 'pending' | 'running' | 'ok' | 'handledError';

const PASSOS: Array<{ id: string; title: string; tool: string; kind: 'read' | 'execute' | 'fetch' | 'search' }> = [
  { id: '1', title: 'Ler o log do servidor', tool: 'ler_arquivo', kind: 'read' },
  { id: '2', title: 'Medir o tempo de resposta das rotas', tool: 'executar_comando', kind: 'execute' },
  { id: '3', title: 'Consultar a página de status da hospedagem', tool: 'ler_pagina', kind: 'fetch' },
  { id: '4', title: 'Comparar com o deploy anterior', tool: 'executar_comando', kind: 'search' },
];

const RESPOSTA_DO_TURNO = [
  'A lentidão veio do deploy de ontem: a rota `/busca` passou de 180 ms para 1,4 s.',
  '',
  'O deploy trocou a consulta de produtos e ela deixou de usar o índice da coluna `categoria`. As outras rotas estão no tempo de sempre.',
  '',
  '| Rota | Antes | Depois |',
  '| --- | --- | --- |',
  '| `/busca` | 180 ms | 1,4 s |',
  '| `/produto` | 95 ms | 98 ms |',
  '| `/carrinho` | 120 ms | 118 ms |',
  '',
  'Quer que eu prepare a correção da consulta para você revisar?',
].join('\n');

/** A cena do turno avança por um evento `vitrine:passo` (0 a 4), para a gravação
 * do README controlar o ritmo; sem evento, fica no passo 3. */
const CenaDoTurno: React.FC = () => {
  const [passo, setPasso] = React.useState(3);
  React.useEffect(() => {
    const ouvir = (evento: Event) => setPasso(Number((evento as CustomEvent).detail) || 0);
    window.addEventListener('vitrine:passo', ouvir);
    return () => window.removeEventListener('vitrine:passo', ouvir);
  }, []);
  const estado = (indice: number): Estado => {
    if (indice === 2 && passo > 2) return 'handledError';
    if (indice < passo) return 'ok';
    return indice === passo ? 'running' : 'pending';
  };
  return (
    <>
      <MessageBubble message={voce('v-lento-p', 'Por que o site ficou lento depois do deploy de ontem?', '10:02')} />
      {passo < 4 ? (
        <ProcessingIndicator
          stages={[{ stage: PASSOS[passo].title, status: 'running' }]}
          plan={PASSOS.map((item, indice) => ({
            ...item, status: estado(indice),
            ...(indice === 2 && passo > 2 ? { resumo: 'A página não respondeu; segui pelos logs.' } : {}),
          }))}
        />
      ) : (
        <MessageBubble message={sentury('v-lento', RESPOSTA_DO_TURNO, '10:03', {
          traces: PASSOS.map(item => ({ stage: item.title, durationMs: 900, status: 'completed' as const })),
        })} />
      )}
    </>
  );
};


const SAIDA_DOS_TESTES: CommandRun['saida'] = {
  linhas: [
    ['out', '============================= test session starts ============================='],
    ['out', 'collected 48 items'],
    ['out', ''],
    ['out', 'tests/test_estoque.py ..........                                      [ 20%]'],
    ['out', 'tests/test_pedidos.py ...................                             [ 60%]'],
    ['err', 'tests/test_precos.py ....FF...........                               [100%]'],
    ['out', ''],
    ['err', 'FAILED tests/test_precos.py::test_reajuste_de_centavos - assert 10.5 == 10.51'],
    ['err', 'FAILED tests/test_precos.py::test_reajuste_em_lote - assert 1049.99 == 1050.0'],
    ['out', '========================= 2 failed, 46 passed in 3.41s ========================'],
  ],
  cortadas: 0,
  codigo: 1,
  resumo: '2 falharam, 46 passaram',
};

const RODOU_OS_TESTES: CommandRun[] = [
  { id: 'v-t1', title: 'Rodar a suíte de testes', tool: 'executar_comando', kind: 'execute',
    command: 'python -m pytest -q', status: 'ok', durationMs: 3600, saida: SAIDA_DOS_TESTES },
];

const CORRIGIU: CommandRun[] = [
  { id: 'v-e1', title: 'Corrigir o arredondamento do reajuste', tool: 'editar_arquivo', kind: 'edit',
    command: 'loja/precos.py', status: 'ok', durationMs: 120,
    diff: {
      arquivo: 'loja/precos.py', criado: false, adicionadas: 3, removidas: 2, cortado: false,
      trechos: [{
        cabecalho: '@@ -14,8 +14,9 @@ def aplicar_reajuste(preco, percentual):',
        linhas: [
          [' ', 'def aplicar_reajuste(preco, percentual):', 14, 14],
          [' ', '    """Preço com o reajuste, em centavos exatos."""', 15, 15],
          ['-', '    novo = round(preco, 2) * (1 + percentual / 100)', 16, null],
          ['-', '    return round(novo, 2)', 17, null],
          ['+', '    centavos = Decimal(str(preco)) * 100', null, 16],
          ['+', '    novo = centavos * (1 + Decimal(percentual) / 100)', null, 17],
          ['+', '    return float(novo.quantize(Decimal("1")) / 100)', null, 18],
        ],
      }],
    } },
  { id: 'v-e2', title: 'Rodar os testes de preço de novo', tool: 'executar_comando', kind: 'execute',
    command: 'python -m pytest -q tests/test_precos.py', status: 'ok', durationMs: 1100,
    saida: { linhas: [['out', 'tests/test_precos.py ...............                                   [100%]'],
      ['out', '15 passed in 0.62s']], cortadas: 0, codigo: 0, resumo: '15 passaram' } },
];

const APAGAR: CommandRun[] = [
  { id: 'v-a1', title: 'Listar os relatórios de 2025', tool: 'executar_comando', kind: 'read',
    command: 'Get-ChildItem .\\exportacoes\\relatorio-2025-*.pdf', status: 'ok', durationMs: 240,
    saida: { linhas: [['out', 'relatorio-2025-01.pdf   1,2 MB'], ['out', 'relatorio-2025-02.pdf   1,1 MB'],
      ['out', 'relatorio-2025-03.pdf   1,4 MB'], ['out', '... e mais 9 arquivos']], cortadas: 0, codigo: 0, resumo: '12 arquivos' } },
  { id: 'v-a2', title: 'Apagar os relatórios de 2025', tool: 'executar_comando', kind: 'delete',
    command: 'Remove-Item .\\exportacoes\\relatorio-2025-*.pdf', status: 'pending' },
];

type LinhaDoDiff = ['+' | '-' | ' ', string, number | null, number | null];

/** Arquivo novo: todas as linhas entram como acrescentadas. */
const arquivoNovo = (arquivo: string, linhas: string[]) => ({
  arquivo, criado: true, adicionadas: linhas.length, removidas: 0, cortado: false,
  trechos: [{ cabecalho: `@@ -0,0 +1,${linhas.length} @@`,
    linhas: linhas.map((texto, i): LinhaDoDiff => ['+', texto, null, i + 1]) }],
});

const CONVERSOR = [
  'import csv',
  'import json',
  'from pathlib import Path',
  '',
  '',
  'def converter(origem: str, destino: str) -> int:',
  '    """Lê um CSV e grava o mesmo conteúdo em JSON. Devolve quantas linhas."""',
  '    with open(origem, newline="", encoding="utf-8") as arquivo:',
  '        linhas = list(csv.DictReader(arquivo))',
  '    Path(destino).write_text(json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8")',
  '    return len(linhas)',
];

const TESTES = [
  'import json',
  '',
  'from conversor.csv_json import converter',
  '',
  '',
  'def test_converte_cada_linha(tmp_path):',
  '    origem = tmp_path / "vendas.csv"',
  '    origem.write_text("loja,total\\nCentro,10\\nNorte,7\\n", encoding="utf-8")',
  '    assert converter(origem, tmp_path / "vendas.json") == 2',
  '',
  '',
  'def test_csv_salvo_pelo_excel(tmp_path):',
  '    origem = tmp_path / "vendas.csv"',
  '    origem.write_bytes("\\ufeffloja,total\\nCentro,10\\n".encode("utf-8"))',
  '    converter(origem, tmp_path / "vendas.json")',
  '    dados = json.loads((tmp_path / "vendas.json").read_text(encoding="utf-8"))',
  '    assert dados[0]["loja"] == "Centro"',
];

/** A sequência de um turno que cria código: escreve, testa, vê falhar, corrige, testa de novo. */
const PASSOS_DE_CRIAR: CommandRun[] = [
  { id: 'v-c1', title: 'Criar o conversor', tool: 'escrever_arquivo', kind: 'edit',
    command: 'conversor/csv_json.py', status: 'ok', durationMs: 90,
    diff: arquivoNovo('conversor/csv_json.py', CONVERSOR) },
  { id: 'v-c2', title: 'Escrever os testes', tool: 'escrever_arquivo', kind: 'edit',
    command: 'tests/test_csv_json.py', status: 'ok', durationMs: 80,
    diff: arquivoNovo('tests/test_csv_json.py', TESTES) },
  { id: 'v-c3', title: 'Rodar os testes', tool: 'executar_comando', kind: 'execute',
    command: 'python -m pytest -q', status: 'ok', durationMs: 1300,
    saida: { linhas: [
      ['out', 'tests/test_csv_json.py .F                                          [100%]'],
      ['out', ''],
      ['err', 'FAILED tests/test_csv_json.py::test_csv_salvo_pelo_excel - KeyError: \'loja\''],
      ['out', '1 failed, 1 passed in 0.21s'],
    ], cortadas: 0, codigo: 1, resumo: '1 falhou, 1 passou' } },
  { id: 'v-c4', title: 'Ler o CSV do Excel sem o marcador invisível', tool: 'editar_arquivo', kind: 'edit',
    command: 'conversor/csv_json.py', status: 'ok', durationMs: 70,
    diff: {
      arquivo: 'conversor/csv_json.py', criado: false, adicionadas: 2, removidas: 1, cortado: false,
      trechos: [{
        cabecalho: '@@ -6,6 +6,7 @@ def converter(origem: str, destino: str) -> int:',
        linhas: [
          [' ', 'def converter(origem: str, destino: str) -> int:', 6, 6],
          [' ', '    """Lê um CSV e grava o mesmo conteúdo em JSON. Devolve quantas linhas."""', 7, 7],
          ['-', '    with open(origem, newline="", encoding="utf-8") as arquivo:', 8, null],
          ['+', '    # O Excel grava um marcador (BOM) no começo; utf-8-sig o descarta.', null, 8],
          ['+', '    with open(origem, newline="", encoding="utf-8-sig") as arquivo:', null, 9],
          [' ', '        linhas = list(csv.DictReader(arquivo))', 9, 10],
        ],
      }],
    } },
  { id: 'v-c5', title: 'Rodar os testes de novo', tool: 'executar_comando', kind: 'execute',
    command: 'python -m pytest -q', status: 'ok', durationMs: 1100,
    saida: { linhas: [['out', 'tests/test_csv_json.py ..                                          [100%]'],
      ['out', '2 passed in 0.18s']], cortadas: 0, codigo: 0, resumo: '2 passaram' } },
];

const RESPOSTA_DE_CRIAR = [
  'Pronto: `conversor/csv_json.py` converte um CSV em JSON, e os 2 testes passam.',
  '',
  'Um dos testes pegou um caso real: o CSV salvo pelo Excel começa com um marcador invisível (BOM) que grudava no nome da primeira coluna, e `loja` virava `\\ufeffloja`. Agora o arquivo é lido com `utf-8-sig`, que descarta o marcador.',
].join('\n');

/** Avança por `vitrine:criando` (0 a 5), para a gravação controlar o ritmo; sem evento, mostra o fim. */
const CenaDeCriar: React.FC = () => {
  const [passo, setPasso] = React.useState(PASSOS_DE_CRIAR.length);
  React.useEffect(() => {
    const ouvir = (evento: Event) => setPasso(Number((evento as CustomEvent).detail) || 0);
    window.addEventListener('vitrine:criando', ouvir);
    return () => window.removeEventListener('vitrine:criando', ouvir);
  }, []);
  const feitos = PASSOS_DE_CRIAR.slice(0, passo);
  const rodando = passo < PASSOS_DE_CRIAR.length
    ? [{ ...PASSOS_DE_CRIAR[passo], status: 'running' as const, saida: undefined, diff: undefined, durationMs: undefined }]
    : [];
  const terminou = passo >= PASSOS_DE_CRIAR.length;
  return (
    <>
      <MessageBubble message={voce('v-criar-p', 'Cria um conversor de CSV para JSON em Python, com testes.', '20:10')} />
      <MessageBubble message={sentury('v-criar', terminou ? RESPOSTA_DE_CRIAR : '', '20:11', {
        status: terminou ? 'complete' : 'streaming',
        commands: [...feitos, ...rodando],
      })} />
    </>
  );
};

export const VitrineAtlas: React.FC = () => (
  <section>
    <Cena nome="hd">
      <MessageBubble message={voce('v-hd-p', 'Como está o meu HD?', '09:12')} />
      <MessageBubble message={sentury('v-hd', respostaDoHd, '09:12')} />
    </Cena>
    <Cena nome="lojas">
      <MessageBubble message={voce('v-lojas-p', 'Como fecharam as lojas em outubro?', '09:15')} />
      <MessageBubble message={sentury('v-lojas', respostaComCores, '09:15')} />
    </Cena>
    <Cena nome="programas">
      <MessageBubble message={voce('v-apps-p', 'O que está pesando no meu PC?', '09:16')} />
      <MessageBubble message={sentury('v-apps', respostaProgramas, '09:16')} />
    </Cena>
    <Cena nome="codigo">
      <MessageBubble message={voce('v-codigo-p', 'Me passa o HTML de um cartão de vendas.', '09:17')} />
      <MessageBubble message={sentury('v-codigo', respostaCodigo, '09:17')} />
    </Cena>
    <Cena nome="trabalhando">
      <CenaDoTurno />
    </Cena>
    <Cena nome="memoria">
      <MessageBubble message={voce('v-mem-p', 'Prefiro os relatórios em PDF. E quando eu pedir revisão de contrato, começa pela cláusula de multa.', '11:40')} />
      <MessageBubble message={sentury('v-mem', 'Combinado: os relatórios saem em PDF, e revisão de contrato começa pela multa.', '11:40', {
        signals: { aprendizados: [
          { tipo: 'memoria', texto: 'Prefere receber relatórios em PDF, não em planilha.' },
          { tipo: 'skill', nome: 'revisao-de-contrato', acao: 'acrescentada' },
        ] },
      })} />
    </Cena>
    <Cena nome="notou">
      <MessageBubble message={voce('v-notou-p', 'Aplica o reajuste de 5% na tabela de preços.', '14:05')} />
      <MessageBubble message={sentury('v-notou', 'Pronto: os 48 itens da tabela estão com o reajuste de 5%.', '14:05', {
        signals: { proactiveInsight: { text: 'Três itens ficaram abaixo do custo mesmo com o reajuste; vale revisar antes de publicar a tabela.' } },
      })} />
    </Cena>

    <Cena nome="rodando">
      <MessageBubble message={voce('v-rod-p', 'Roda os testes e me diz o que quebrou.', '15:20')} />
      <MessageBubble message={sentury('v-rod', 'Dois testes quebraram, os dois no reajuste de preço: o valor sai um centavo diferente do esperado. O resto da suíte passou.', '15:21', {
        commands: RODOU_OS_TESTES,
      })} />
    </Cena>
    <Cena nome="editando">
      <MessageBubble message={voce('v-edit-p', 'Corrige isso.', '15:22')} />
      <MessageBubble message={sentury('v-edit', 'Corrigi: o reajuste arredondava antes de multiplicar. Agora a conta é feita em centavos exatos, e os 15 testes de preço passam.', '15:23', {
        commands: CORRIGIU,
      })} />
    </Cena>
    <Cena nome="criando">
      <CenaDeCriar />
    </Cena>
    <Cena nome="pergunta">
      <MessageBubble message={voce('v-perg-p', 'Monta o relatório de vendas do mês.', '16:02')} />
      <MessageBubble message={sentury('v-perg', '', '16:02', {
        clarification: {
          intro: 'Antes de montar, duas escolhas mudam o resultado:',
          questions: [
            { header: 'Formato', question: 'Em que formato você quer o relatório?', multiSelect: false, options: [
              { label: 'PDF', description: 'Para enviar ou imprimir, com gráficos e resumo.' },
              { label: 'Planilha', description: 'Os dados por loja e por dia, para filtrar.' },
              { label: 'Painel na conversa', description: 'Interativo aqui mesmo, sem arquivo.' },
            ] },
            { header: 'Lojas', question: 'Quais lojas entram?', multiSelect: true, options: [
              { label: 'Centro', description: '' }, { label: 'Shopping Norte', description: '' },
              { label: 'Rodoviária', description: '' }, { label: 'Bairro Sul', description: '' },
            ] },
          ],
        },
      })} />
    </Cena>
    <Cena nome="permissao">
      <MessageBubble message={voce('v-perm-p', 'Apaga os relatórios de 2025 da pasta de exportações.', '16:40')} />
      <MessageBubble message={sentury('v-perm', 'Achei 12 relatórios de 2025. Apagar não dá para desfazer, então preciso do seu ok.', '16:40', {
        commands: APAGAR,
        permissaoId: 'v-a2',
        permissao: { chave: 'Remove-Item', comando: 'Remove-Item .\\exportacoes\\relatorio-2025-*.pdf',
          motivo: 'apaga 12 arquivos, e isso não dá para desfazer', so_desta_vez: true },
      })} />
    </Cena>
    <Cena nome="plano">
      <MessageBubble message={voce('v-plano-p', '@plano Migra o banco de testes para o Postgres 16.', '17:10')} />
      <MessageBubble message={sentury('v-plano', 'Montei o caminho. Nada roda antes do seu ok.', '17:11', {
        plano: {
          plano: 'migrar-banco-de-testes', tipo: 'plano', aprovado: false, faltam: 5, estado: 'aberto',
          contexto: 'Subir o banco de testes do Postgres 13 para o 16 sem perder os dados de exemplo.',
          tarefas: [
            { id: '1', titulo: 'Copiar o banco atual para um arquivo de segurança', feito: false, opcional: false, gate: false, estado: 'pendente' },
            { id: '2', titulo: 'Subir o Postgres 16 num contêiner ao lado', feito: false, opcional: false, gate: false, estado: 'pendente' },
            { id: '3', titulo: 'Restaurar a cópia no 16 e conferir as tabelas', feito: false, opcional: false, gate: true, estado: 'pendente' },
            { id: '4', titulo: 'Rodar a suíte contra o banco novo', feito: false, opcional: false, gate: false, estado: 'pendente' },
            { id: '5', titulo: 'Trocar a configuração dos testes para o 16', feito: false, opcional: false, gate: false, estado: 'pendente' },
          ],
        },
      })} />
    </Cena>
    <Cena nome="navegador">
      <MessageBubble message={voce('v-nav-p', '@navegador Vê o preço do monitor de 27 polegadas no site da loja.', '18:05')} />
      <MessageBubble message={sentury('v-nav', 'O monitor de 27 polegadas está por R$ 1.299 à vista, ou 10 vezes de R$ 139,90. Tem em estoque e o frete para o seu CEP sai grátis.', '18:06', {
        navegador: {
          site: 'loja.exemplo.com.br', status: 'ok', motivo: '', textos: 4, prints: 0, duracao_ms: 9400,
          passos: [
            { acao: 'navegar', rotulo: 'navegar · página inicial da loja', status: 'ok', leitura: 'Página inicial com busca no topo.' },
            { acao: 'digitar', rotulo: 'digitar · “monitor 27” na busca', status: 'ok', leitura: '18 resultados.' },
            { acao: 'clicar', rotulo: 'clicar · primeiro resultado', status: 'ok', leitura: 'Monitor 27" IPS, R$ 1.299.' },
            { acao: 'ler', rotulo: 'ler · estoque e frete', status: 'ok', leitura: 'Em estoque; frete grátis.' },
          ],
        },
      })} />
    </Cena>
    <Cena nome="computador">
      <MessageBubble message={voce('v-comp-p', '@computador Abre a planilha de metas e preenche a coluna de outubro.', '18:30')} />
      <MessageBubble message={sentury('v-comp', 'Preenchi outubro nas quatro lojas e salvei a planilha. Bairro Sul ficou abaixo da meta pelo segundo mês.', '18:32', {
        computador: {
          status: 'pronta', parado: false, prints: 2, leituras: 6, janela: 'metas-2026.xlsx - Excel',
          objetivo: 'Preencher outubro na planilha de metas', turno: 1, limite: 40,
          gestos: [
            { acao: 'abrir', titulo: 'abrir', detalhe: 'Abrir metas-2026.xlsx no Excel', status: 'ok' },
            { acao: 'clicar', titulo: 'clicar', detalhe: 'Selecionar a célula de outubro da loja Centro', status: 'ok' },
            { acao: 'digitar', titulo: 'digitar', detalhe: 'Digitar os quatro valores da coluna', status: 'ok' },
            { acao: 'tecla', titulo: 'apertar', detalhe: 'Salvar com Ctrl+S', status: 'ok', tecla: 'ctrl+s' },
          ],
        },
      })} />
    </Cena>
    <Cena nome="goal">
      <MessageBubble message={voce('v-goal-p', '@goal Deixa a suíte de testes toda verde.', '19:00')} />
      <MessageBubble message={sentury('v-goal', 'Proponho este objetivo. Ele só começa quando você mandar.', '19:00')} />
      <GoalCard sessionId="vitrine-goal" conversando={false} />
    </Cena>
  </section>
);
