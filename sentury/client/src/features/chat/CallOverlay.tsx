import React, { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, MonitorUp, PhoneOff } from 'lucide-react';
import { getRuntimeConfig } from '../../runtime/config';
import { CallState, LiveCall, TranscriptItem } from '../../runtime/live-call';

interface CallOverlayProps {
  onEnd: (transcript: TranscriptItem[]) => void;
  onClose: () => void;
}

function wsUrl(): string {
  const base = (getRuntimeConfig().apiUrl || window.location.origin).replace(/^http/, 'ws');
  return `${base.replace(/\/+$/, '')}/sentury/live`;
}

export const CallOverlay: React.FC<CallOverlayProps> = ({ onEnd, onClose }) => {
  const [estado, setEstado] = useState<CallState>('ringing');
  const [rotulo, setRotulo] = useState('chamando…');
  const [legenda, setLegenda] = useState('');
  const [atividade, setAtividade] = useState<'speaking' | 'thinking' | 'idle'>('idle');
  const [mudo, setMudo] = useState(false);
  const [tela, setTela] = useState(false);
  const chamadaRef = useRef<LiveCall | null>(null);

  useEffect(() => {
    const chamada = new LiveCall(wsUrl(), {
      onState: (proximo, label) => { setEstado(proximo); if (label) setRotulo(label); },
      onCaption: setLegenda,
      onActivity: setAtividade,
      onScreenShare: setTela,
      onEnd: transcript => { onEnd(transcript); onClose(); },
    });
    chamadaRef.current = chamada;
    void chamada.start();
    return () => { chamada.hangUp(); };
    // Uma instância por abertura do overlay; religar é fechar e abrir de novo.
  }, []);

  const desligar = () => chamadaRef.current?.hangUp();

  const alternarMudo = () => {
    const proximo = !mudo;
    setMudo(proximo);
    chamadaRef.current?.setMuted(proximo);
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-zinc-950/80 backdrop-blur-sm">
      <div className="w-[min(22rem,calc(100vw-2rem))] rounded-3xl border border-white/10 bg-zinc-900/95 p-8 text-center text-white shadow-2xl">
        <div className="relative mx-auto h-24 w-24">
          <span className={`absolute inset-0 rounded-full ${atividade === 'speaking' ? 'animate-ping bg-gold/30' : ''}`} />
          <span className={`absolute inset-0 rounded-full border-2 ${atividade === 'thinking' ? 'animate-spin border-gold border-t-transparent' : 'border-white/10'}`} />
          <div className="absolute inset-2 overflow-hidden rounded-full bg-zinc-800">
            <img src="/sentury-intelligence.webp" alt="" className="h-full w-full object-cover" />
          </div>
        </div>

        <p className="mt-5 text-base font-semibold">Sentury</p>
        <p className="mt-1 text-xs uppercase tracking-[0.16em] text-gold">{rotulo}</p>
        {legenda ? <p className="mt-4 min-h-8 text-xs leading-5 text-zinc-300">{legenda}</p> : <p className="mt-4 min-h-8" />}

        {estado === 'error' ? (
          <div className="mt-5 flex justify-center gap-2">
            <button type="button" onClick={onClose} className="rounded-lg border border-white/20 px-4 py-2 text-xs font-semibold text-white/80 hover:bg-white/10">
              Sair
            </button>
          </div>
        ) : (
          <div className="mt-6 flex items-center justify-center gap-3">
            <button
              type="button"
              onClick={alternarMudo}
              title={mudo ? 'Reativar microfone' : 'Mudo'}
              aria-label={mudo ? 'Reativar microfone' : 'Mudo'}
              className={`rounded-full p-3.5 transition-colors ${mudo ? 'bg-white text-zinc-900' : 'bg-white/10 text-white hover:bg-white/20'}`}
            >
              {mudo ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={() => void chamadaRef.current?.toggleScreen()}
              title="Compartilhar tela"
              aria-label="Compartilhar tela"
              className={`rounded-full p-3.5 transition-colors ${tela ? 'bg-gold text-zinc-900' : 'bg-white/10 text-white hover:bg-white/20'}`}
            >
              <MonitorUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={desligar}
              title="Desligar"
              aria-label="Desligar"
              className="rounded-full bg-red-600 p-3.5 text-white hover:bg-red-700"
            >
              <PhoneOff className="h-4 w-4" />
            </button>
          </div>
        )}

        <p className="mt-6 text-[10px] leading-4 text-zinc-500">
          Fale por cima para interromper.
        </p>
      </div>
    </div>
  );
};
