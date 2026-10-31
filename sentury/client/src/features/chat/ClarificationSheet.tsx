import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, Check, Pencil, X } from 'lucide-react';
import { ClarificationPayload } from '../../contracts/domain/session';
import { useChatStore } from '../../stores/chat-store';
import { montarRespostas, type AnswerState } from '../../domain/clarification';

interface ClarificationSheetProps {
  messageId: string;
  sessionId: string;
  clarification: ClarificationPayload;
}

export const ClarificationSheet: React.FC<ClarificationSheetProps> = ({ sessionId, messageId, clarification }) => {
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({});
  // Uma pergunta por vez: a pessoa decide uma coisa, avança, e o contador
  // no topo diz quanto falta.
  const [etapa, setEtapa] = useState(0);
  const [enviando, setEnviando] = useState(false);
  const sendMessage = useChatStore(state => state.sendMessage);
  const dispensar = useChatStore(state => state.dispensarInterativo);
  const answeredCount = clarification.questions.filter((_, index) => {
    const answer = answers[index];
    return Boolean(answer?.custom.trim() || answer?.selected.length);
  }).length;
  const completo = answeredCount === clarification.questions.length && answeredCount > 0;
  const total = clarification.questions.length;
  const ultima = etapa >= total - 1;
  const respondida = (index: number) => Boolean(answers[index]?.custom.trim() || answers[index]?.selected.length);

  const update = (index: number, next: AnswerState) => setAnswers(existing => ({ ...existing, [index]: next }));
  const submit = async () => {
    if (!ultima) {
      if (respondida(etapa)) setEtapa(etapa + 1);
      return;
    }
    if (!completo || enviando) return;
    setEnviando(true);
    const payload = montarRespostas(clarification, answers);
    dispensar(sessionId, messageId, 'clarification');
    await sendMessage(sessionId, JSON.stringify(payload));
  };
  const chatCanvas = document.getElementById('sentury-main');

  return createPortal(
    <div className={`pointer-events-none ${chatCanvas ? 'absolute' : 'fixed'} inset-0 z-[65]`}>
      <form onSubmit={event => { event.preventDefault(); void submit(); }} aria-label="Perguntas para continuar" className="pointer-events-auto absolute inset-x-0 bottom-0 mx-auto flex max-h-[85%] w-[min(780px,calc(100%-32px))] flex-col animate-[sentury-sheet-up_180ms_ease-out] rounded-t-2xl border border-b-0 border-[#d8cfbd] bg-[#fffdf8] shadow-[0_-18px_48px_rgba(35,31,24,.16)]">
        <header className="flex shrink-0 items-start gap-3 border-b border-stone-200 px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-zinc-950">Antes de continuar</h2>
            {clarification.intro && <p className="mt-1 text-xs leading-5 text-zinc-500">{clarification.intro}</p>}
          </div>
          {total > 1 && <span aria-label={`Pergunta ${etapa + 1} de ${total}`} className="mt-1 shrink-0 rounded-full bg-stone-100 px-2.5 py-1 text-xs font-semibold tabular-nums text-zinc-600">{etapa + 1}/{total}</span>}
          <button type="button" onClick={() => dispensar(sessionId, messageId, 'clarification')} className="rounded-md p-1 text-zinc-400 hover:bg-stone-100 hover:text-zinc-800" aria-label="Fechar e responder no chat"><X className="h-4 w-4" /></button>
        </header>

        <div className="min-h-0 space-y-6 overflow-y-auto overscroll-contain p-5">
          {clarification.questions.map((question, qi) => qi !== etapa ? null : (() => {
            const current = answers[qi] || { selected: [], custom: '' };
            const choose = (label: string) => {
              const selected = question.multiSelect
                ? current.selected.includes(label) ? current.selected.filter(value => value !== label) : [...current.selected, label]
                : [label];
              update(qi, { ...current, selected, custom: question.multiSelect ? current.custom : '' });
            };
            return <fieldset key={qi} className="space-y-2">
              <legend className="mb-2 text-sm font-semibold text-zinc-950">{question.question}</legend>
              <p className="text-xs text-zinc-500">{question.header} · {question.multiSelect ? 'Escolha uma ou mais' : 'Escolha uma'}</p>
              {question.options.map((option, oi) => {
                const active = current.selected.includes(option.label);
                return <button key={oi} type="button" aria-pressed={active} onClick={() => choose(option.label)} className={`flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left transition-colors ${active ? 'border-gold bg-gold-soft' : 'border-stone-200 bg-[#f7f4ec] hover:border-stone-400 hover:bg-white'}`}>
                  <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center ${question.multiSelect ? 'rounded-md' : 'rounded-full'} bg-zinc-800 text-xs text-white`}>{active ? <Check className="h-3.5 w-3.5" /> : oi + 1}</span>
                  <span className="min-w-0"><strong className="block text-sm text-zinc-900">{option.label}</strong>{option.description && <span className="mt-0.5 block text-xs leading-5 text-zinc-500">{option.description}</span>}</span>
                </button>;
              })}
              <label className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
                <Pencil className="mt-1 h-4 w-4 shrink-0 text-zinc-500" />
                <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-zinc-900">Outra resposta</span><input aria-label={`Outra resposta: ${question.question}`} value={current.custom} maxLength={500} onChange={event => update(qi, { selected: question.multiSelect ? current.selected : [], custom: event.target.value })} placeholder="Escreva sua própria resposta" className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold" /></span>
              </label>
            </fieldset>;
          })())}
        </div>

        <footer className="flex shrink-0 items-center gap-3 border-t border-stone-200 px-5 py-3">
          <span className="flex-1">
            {etapa > 0 && <button type="button" onClick={() => setEtapa(etapa - 1)} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-xs font-medium text-zinc-500 hover:bg-stone-100 hover:text-zinc-900"><ArrowLeft className="h-3.5 w-3.5" />Voltar</button>}
          </span>
          {ultima
            ? <button type="submit" disabled={!completo || enviando} className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-35">Enviar respostas<ArrowRight className="h-3.5 w-3.5" /></button>
            : <button type="submit" disabled={!respondida(etapa)} className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-35">Próximo<ArrowRight className="h-3.5 w-3.5" /></button>}
        </footer>
      </form>
    </div>,
    chatCanvas || document.body,
  );
};
