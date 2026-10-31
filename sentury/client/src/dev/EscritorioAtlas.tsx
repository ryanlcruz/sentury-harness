import { useEffect, useRef, useState } from 'react';
import { Escritorio, MAXIMO_NA_SALA, type ResidenteNaCena } from '../features/residentes/escritorio/escritorio';
import { EventosDaSala } from '../features/residentes/escritorio/eventosDaSala';
import { MedidorDaSala } from '../features/residentes/escritorio/medicao';
import type { Evento } from '../features/residentes/api';
import { QUADRO_DO_ESCRITORIO } from '../features/residentes/escritorio/estilo';

const RESIDENTES: ResidenteNaCena[] = [
  { nome: 'atlas', rotulo: 'Atlas', familia: 'atendimento', pose: 'parado',
    cores: { penas: '#3f72b3', asas: '#2d588f', barriga: '#b4cff0', olho: '#5ab0ff' }, acessorios: { rosto: 'oculos', asa: 'prancheta' } },
  { nome: 'iris', rotulo: 'Iris', familia: 'dados', pose: 'parado',
    cores: { penas: '#bd6aa0', asas: '#934f80', barriga: '#f3cbe2', olho: '#c58cff' }, acessorios: { ouvidos: 'fone', asa: 'notebook' } },
  { nome: 'forge', rotulo: 'Forge', familia: 'codigo', pose: 'parado',
    cores: { penas: '#c97a40', asas: '#a35e2f', barriga: '#f4cfa3', olho: '#ffb15c' }, acessorios: { cabeca: 'capacete', asa: 'chave' } },
  { nome: 'nox', rotulo: 'Nox', familia: 'pesquisa', pose: 'dormindo',
    cores: { penas: '#2e2b38', asas: '#221f2b', barriga: '#5d5673', olho: '#a68bff' }, acessorios: { asa: 'lupa' } },
  ...['lina', 'caio', 'vera', 'rui', 'bia'].map((nome, i): ResidenteNaCena => ({
    nome, rotulo: nome.charAt(0).toUpperCase() + nome.slice(1), familia: 'geral', pose: 'parado',
    cores: [
      { penas: '#668b68', asas: '#416545', barriga: '#d7e6bd', olho: '#b6db87' },
      { penas: '#9d695f', asas: '#75493d', barriga: '#eccfba', olho: '#eda479' },
      { penas: '#7e7ca6', asas: '#555377', barriga: '#dad9ea', olho: '#bcb7ee' },
      { penas: '#498d96', asas: '#316370', barriga: '#bde3de', olho: '#75d1cc' },
      { penas: '#9c8145', asas: '#766030', barriga: '#eee0ba', olho: '#edd187' },
    ][i], acessorios: [{ rosto: 'monoculo' }, { pescoco: 'gravata' }, { asa: 'caneca' }, { cabeca: 'gorro' }, { pescoco: 'cracha' }][i],
  })),
];

export default function EscritorioAtlas() {
  const host = useRef<HTMLDivElement>(null);
  const motor = useRef<Escritorio | null>(null);
  const [nome, selecionar] = useState('atlas');
  const [medicao, medir] = useState('Aguardando quadros');
  const [retratos, guardarRetrato] = useState<Record<string, string>>({});
  const [geracao, recriar] = useState(0);
  const [quantidade, lotacao] = useState(4);
  const [faltam, preparar] = useState<number | null>(null);
  const [mesa, mostrarMesa] = useState('Sem reunião de demonstração.');
  const visiveis = RESIDENTES.slice(0, quantidade);
  const lista = useRef(visiveis);
  lista.current = visiveis;
  const trilha = useRef(new EventosDaSala());
  const estados = useRef<Record<string, ResidenteNaCena['pose']>>({});
  const timers = useRef(new Set<number>());
  useEffect(() => {
    if (!host.current) return;
    preparar(null);
    const medidor = new MedidorDaSala();
    const sala = new Escritorio(host.current, {
      progressivo: true, aoPreparacao: preparar,
      aoSelecionar: n => { if (n) selecionar(n); },
      aoAtividade: ativa => {
        medidor.reiniciar();
        medir(ativa ? 'Medindo tempo ativo…' : 'Cena pausada: fora de vista ou aba oculta.');
        if (ativa) trilha.current.reconciliar(motor.current);
      },
      aoQuadro: m => {
        const a = medidor.receber(m);
        if (!a) return;
        medir(`${a.fps.toFixed(1)} quadros/s · CPU ${a.cpu.toFixed(2)} ms/quadro (máx. ${a.cpuMax.toFixed(2)}) · ` +
          `intervalo p95 ${a.intervalo95.toFixed(1)} ms (máx. ${a.intervaloMax.toFixed(1)}) · ` +
          `${a.atrasados} quadros atrasados em ${(a.duracao / 1000).toFixed(1)} s · ${a.chamadas} chamadas · ${a.triangulos} triângulos`);
      },
    });
    motor.current = sala;
    sala.sincronizar(lista.current);
    estados.current = {};
    trilha.current = new EventosDaSala();
    mostrarMesa('Sem reunião de demonstração.');
    return () => {
      timers.current.forEach(t => window.clearTimeout(t)); timers.current.clear();
      sala.destruir(); motor.current = null;
    };
  }, [geracao]);
  useEffect(() => { motor.current?.sincronizar(lista.current); }, [quantidade]);
  useEffect(() => { motor.current?.selecionar(nome); }, [nome, geracao]);
  const pose = (p: ResidenteNaCena['pose']) => {
    estados.current[nome] = p;
    motor.current?.sincronizar(visiveis.map(r => ({ ...r, pose: estados.current[r.nome] ?? r.pose })));
  };
  const nomes = visiveis.map(r => r.nome);
  const reunir = (participantes: string[], animar = false) => {
    if (animar) trilha.current.receber([{
      em: Date.now() / 1000, tipo: participantes.length ? 'mesa_aberta' : 'mesa_fechada',
      agente: 'pessoa', tarefa: '', pedido: '', origem: '', motivo: '', pendente: '',
      aguardando: [], por: '', negado: '', assunto: 'demonstracao', para: '', texto: '',
      participantes, iniciativa: false,
    }], true, motor.current, () => ({ fala: '' }));
    else trilha.current.restaurarMesas(
      participantes.length ? [{ id: 'demonstracao', estado: 'aberto', participantes }] : [], motor.current);
    mostrarMesa(participantes.length ? `Reunião de demonstração: ${participantes.length} participantes.` : 'Sem reunião de demonstração.');
  };
  const depois = (fn: () => void) => {
    const id = window.setTimeout(() => { timers.current.delete(id); fn(); }, 3000);
    timers.current.add(id);
  };
  const evento = (tipo: string) => {
    const e = { em: Date.now() / 1000, tipo, agente: nome, tarefa: `atlas-${nome}`, pedido: 'Conferir os dados',
      origem: 'tela', motivo: '', pendente: '', aguardando: [], por: '', negado: '',
      assunto: '', para: '', texto: '', participantes: [], iniciativa: false } satisfies Evento;
    trilha.current.receber([e, e], true, motor.current, dado => ({ fala: dado.tipo === 'enfileirada' ? '' : 'Conferindo os dados.' }));
  };
  const botao = 'rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm hover:border-gold';
  return <section className="space-y-4">
    <h2 className="text-xl font-semibold">Escritório</h2>
    <p className="text-sm text-zinc-600">Demonstração isolada. O cenário permanece fixo; os {quantidade} residentes não executam tarefas reais.</p>
    <div className="flex flex-wrap gap-2">
      <button className={botao} type="button" aria-pressed={quantidade === MAXIMO_NA_SALA} onClick={() => {
        preparar(null);
        lotacao(q => q === 4 ? MAXIMO_NA_SALA : 4); selecionar('atlas'); estados.current = {};
      }}>{quantidade === 4 ? 'Testar nove residentes' : 'Voltar para quatro'}</button>
      {visiveis.map(r => <button key={r.nome} className={botao} type="button" aria-pressed={nome === r.nome}
        onClick={() => selecionar(r.nome)}>{r.rotulo}</button>)}
    </div>
    <div style={QUADRO_DO_ESCRITORIO} className="rounded-2xl bg-[#0f1420]" ref={host} />
    <p aria-live="polite" className="text-xs text-zinc-500">{faltam === null ? 'Preparando a sala…' : faltam ? `Preparando os residentes: ${faltam} restantes…` : 'Sala pronta.'}</p>
    <p aria-live="polite" className="text-xs text-zinc-500">{mesa}</p>
    <p role="status" className="font-mono text-xs text-zinc-600">{medicao}</p>
    <p className="text-xs text-zinc-500">Meta: 30 quadros/s, um a cada 33,3 ms. Pausas não entram na amostra. O p95 indica o limite de 95% dos intervalos; acima de 50 ms sinaliza atraso. CPU mede atualização e envio, não GPU nem apresentação na tela.</p>
    <div className="flex flex-wrap gap-2">
      <button type="button" className={botao} onClick={() => motor.current?.pedidoChegou(nome)}>Andar até a caixa</button>
      <button type="button" className={botao} onClick={() => reunir(nomes, true)}>Reunir na Mesa</button>
      <button type="button" className={botao} onClick={() => reunir([], true)}>Voltar aos postos</button>
      <button type="button" className={botao} onClick={() => depois(() => reunir(nomes))}>Reunir em 3 s</button>
      <button type="button" className={botao} onClick={() => depois(() => reunir([]))}>Encerrar reunião em 3 s</button>
      <button type="button" className={botao} onClick={() => pose('trabalhando')}>Trabalhando</button>
      <button type="button" className={botao} onClick={() => pose('esperando')}>Esperando</button>
      <button type="button" className={botao} onClick={() => pose('dormindo')}>Dormindo</button>
      <button type="button" className={botao} onClick={() => pose('parado')}>Parado</button>
      <button type="button" className={botao} onClick={() => pose('pausado')}>Pausado</button>
      <button type="button" className={botao} onClick={() => motor.current?.sincronizar(visiveis.map(r => ({ ...r, pose: estados.current[r.nome] ?? r.pose })))}>Repetir leitura da HQ</button>
      <button type="button" className={botao} onClick={() => evento('enfileirada')}>Evento duplicado da HQ</button>
      <button type="button" className={botao} onClick={() => motor.current?.falar(nome, 'Conferindo os dados.', 'você')}>Mostrar balão</button>
      <button type="button" className={botao} onClick={() => {
        const retrato = motor.current?.retrato(nome);
        if (retrato) guardarRetrato(atual => ({ ...atual, [nome]: retrato }));
      }}>Capturar retrato</button>
      <button type="button" className={botao} onClick={() => { preparar(null); recriar(n => n + 1); }}>Recriar sala</button>
    </div>
    {Object.entries(retratos).map(([n, src]) => <img key={n} src={src} alt={`Retrato de ${n}`} className="inline-block h-24 w-24 rounded-xl bg-[#0f1420] object-contain" />)}
    <div className="h-screen rounded-xl border border-dashed border-stone-300 p-5 text-sm text-zinc-600">Área para conferir o scroll. Ao subir, os móveis e as corujas continuam alinhados. Fora da tela, a cena pausa e a medição reinicia ao voltar.</div>
  </section>;
}
