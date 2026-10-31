/* Ditado pelo reconhecimento de fala do navegador. O texto cai no campo e a
   pessoa revisa antes de enviar; nada é enviado sozinho. */

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
};

type RecognitionCtor = new () => Recognition;

function construtor(): RecognitionCtor | null {
  const janela = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return janela.SpeechRecognition || janela.webkitSpeechRecognition || null;
}

export function dictationSupported(): boolean {
  return construtor() !== null;
}

export interface DictationListeners {
  onText: (final: string, interim: string) => void;
  onStart: () => void;
  onEnd: () => void;
  onError: (message: string) => void;
}

export class Dictation {
  private rec: Recognition | null = null;
  private cancelado = false;

  constructor(private readonly listeners: DictationListeners) {}

  start(): void {
    const Ctor = construtor();
    if (!Ctor) { this.listeners.onError('Este navegador não tem reconhecimento de fala.'); return; }
    const rec = new Ctor();
    rec.lang = 'pt-BR';
    rec.continuous = true;
    rec.interimResults = true;
    this.cancelado = false;

    rec.onstart = () => this.listeners.onStart();
    rec.onend = () => { this.rec = null; this.listeners.onEnd(); };
    rec.onerror = event => {
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        this.listeners.onError('Não consegui ouvir. Tente de novo.');
      }
    };
    rec.onresult = event => {
      // `abort()` não dispara onresult, mas um resultado em voo ainda chegaria.
      if (this.cancelado) return;
      let final = '';
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const trecho = event.results[i][0].transcript;
        if (event.results[i].isFinal) final += trecho;
        else interim += trecho;
      }
      this.listeners.onText(final, interim);
    };

    this.rec = rec;
    rec.start();
  }

  stop(): void {
    this.rec?.stop();
  }

  cancel(): void {
    this.cancelado = true;
    this.rec?.abort();
    this.rec = null;
  }

  get running(): boolean {
    return this.rec !== null;
  }
}
