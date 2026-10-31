/* Ligação por voz (WebSocket /sentury/live).
   mic PCM16 16kHz -> servidor -> áudio PCM 24kHz de volta. Barge-in é nativo:
   ao receber `interrupted` a fila de playback é esvaziada na hora. */

export type CallState = 'idle' | 'ringing' | 'connecting' | 'active' | 'error';

export interface TranscriptItem {
  role: 'user' | 'assistant';
  text: string;
}

export interface CallListeners {
  onState: (state: CallState, label: string) => void;
  onCaption: (caption: string) => void;
  onActivity: (kind: 'speaking' | 'thinking' | 'idle') => void;
  onScreenShare: (on: boolean) => void;
  onEnd: (transcript: TranscriptItem[]) => void;
}

const SCREEN_W = 768;
const SCREEN_EVERY_MS = 1500;
const CONNECT_TIMEOUT_MS = 30000;

function b64(bytes: Uint8Array): string {
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunk)) as unknown as number[]);
  }
  return btoa(bin);
}

function unb64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

function floatTo16(f32: Float32Array): Int16Array {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i += 1) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function overlap(previous: string, next: string): number {
  const left = previous.trim();
  const right = next.trim();
  for (let size = Math.min(left.length, right.length); size > 0; size -= 1) {
    if (left.slice(-size).toLowerCase() === right.slice(0, size).toLowerCase()) return size;
  }
  return 0;
}

// Os pedaços chegam sobrepostos; sem isto a transcrição repete sílabas.
function juntar(previous: string, next: string): string {
  const left = previous.trim();
  const right = next.trim();
  if (!left) return right;
  if (!right) return left;
  const comum = overlap(left, right);
  if (comum > 0) return `${left}${right.slice(comum)}`.replace(/\s+/g, ' ').trim();
  const precisaEspaco = !/[\s([{"'/-]$/.test(left) && !/^[\s)\]},".!?:;/-]/.test(right);
  return `${left}${precisaEspaco ? ' ' : ''}${right}`.replace(/\s+/g, ' ').trim();
}

export class LiveCall {
  private ws: WebSocket | null = null;
  private micCtx: AudioContext | null = null;
  private playCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private procNode: ScriptProcessorNode | null = null;
  private srcNode: MediaStreamAudioSourceNode | null = null;
  private playHead = 0;
  private playing = new Set<AudioBufferSourceNode>();
  private ringTimer: number | null = null;
  private ringCtx: AudioContext | null = null;
  private connectTimer: number | null = null;
  private speakingTimer: number | null = null;
  private screenStream: MediaStream | null = null;
  private screenTimer: number | null = null;
  private screenVideo: HTMLVideoElement | null = null;
  private screenCanvas: HTMLCanvasElement | null = null;
  private transcript: TranscriptItem[] = [];

  state: CallState = 'idle';
  muted = false;

  constructor(private readonly url: string, private readonly listeners: CallListeners) {}

  private setState(state: CallState, label: string): void {
    this.state = state;
    this.listeners.onState(state, label);
  }

  private merge(role: 'user' | 'assistant', text: string): void {
    const limpo = text.trim().replace(/\s+/g, ' ');
    if (!limpo) return;
    const ultimo = this.transcript[this.transcript.length - 1];
    if (!ultimo || ultimo.role !== role) {
      this.transcript.push({ role, text: limpo });
      return;
    }
    if (limpo === ultimo.text || ultimo.text.startsWith(limpo)) return;
    if (limpo.startsWith(ultimo.text)) {
      this.transcript[this.transcript.length - 1] = { role, text: limpo };
      return;
    }
    this.transcript[this.transcript.length - 1] = { role, text: juntar(ultimo.text, limpo) };
  }

  private startRing(): void {
    try {
      this.ringCtx = new AudioContext();
      if (this.ringCtx.state === 'suspended') void this.ringCtx.resume();
    } catch {
      return;
    }
    const tocar = () => {
      const ctx = this.ringCtx;
      if (!ctx) return;
      [0, 0.4].forEach((t, i) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = 'sine';
        o.frequency.value = i ? 480 : 440;
        const now = ctx.currentTime + t;
        g.gain.setValueAtTime(0.0001, now);
        g.gain.exponentialRampToValueAtTime(0.12, now + 0.05);
        g.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
        o.connect(g).connect(ctx.destination);
        o.start(now);
        o.stop(now + 0.4);
      });
    };
    tocar();
    this.ringTimer = window.setInterval(tocar, 2000);
  }

  private stopRing(): void {
    if (this.ringTimer) { window.clearInterval(this.ringTimer); this.ringTimer = null; }
    if (this.ringCtx) { try { void this.ringCtx.close(); } catch { /* já fechado */ } this.ringCtx = null; }
  }

  private playPcm(bytes: Uint8Array): void {
    const ctx = this.playCtx;
    if (!ctx) return;
    const i16 = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i += 1) f32[i] = i16[i] / 32768;
    const buf = ctx.createBuffer(1, f32.length, 24000);
    buf.getChannelData(0).set(f32);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const now = ctx.currentTime;
    if (this.playHead < now) this.playHead = now;
    src.start(this.playHead);
    this.playHead += buf.duration;
    this.playing.add(src);
    src.onended = () => this.playing.delete(src);
    this.listeners.onActivity('speaking');
    if (this.speakingTimer) window.clearTimeout(this.speakingTimer);
    this.speakingTimer = window.setTimeout(() => this.listeners.onActivity('idle'), 300);
  }

  private flushPlayback(): void {
    this.playing.forEach(src => { try { src.stop(); } catch { /* já parado */ } });
    this.playing.clear();
    this.playHead = 0;
    this.listeners.onActivity('idle');
  }

  private async startMic(): Promise<void> {
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    this.micCtx = new AudioContext({ sampleRate: 16000 });
    this.srcNode = this.micCtx.createMediaStreamSource(this.micStream);
    this.procNode = this.micCtx.createScriptProcessor(4096, 1, 1);
    this.procNode.onaudioprocess = event => {
      if (this.muted || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const i16 = floatTo16(event.inputBuffer.getChannelData(0));
      this.ws.send(JSON.stringify({ type: 'audio', data: b64(new Uint8Array(i16.buffer)) }));
    };
    this.srcNode.connect(this.procNode);
    this.procNode.connect(this.micCtx.destination);
  }

  async start(): Promise<void> {
    if (this.state !== 'idle') return;
    this.transcript = [];
    this.setState('ringing', 'chamando…');
    this.listeners.onCaption('');
    this.startRing();
    // Sem isto a chamada fica "chamando" para sempre quando o servidor não responde.
    this.connectTimer = window.setTimeout(() => {
      if (this.state === 'ringing' || this.state === 'connecting') {
        this.fail('sem resposta', 'A ligação demorou demais para conectar. Tente de novo.');
      }
    }, CONNECT_TIMEOUT_MS);

    try {
      this.playCtx = new AudioContext({ sampleRate: 24000 });
      if (this.playCtx.state === 'suspended') void this.playCtx.resume();
      this.ws = new WebSocket(this.url);
      // Conectar o WebSocket não é a Sentury atender: o toque só para no `ready`.
      this.ws.onopen = () => { if (this.state === 'ringing') this.setState('connecting', 'chamando…'); };
      this.ws.onmessage = async event => {
        const msg = JSON.parse(String(event.data)) as { type: string; data?: string; text?: string; role?: string; detail?: string };
        if (msg.type === 'ready') {
          if (this.connectTimer) window.clearTimeout(this.connectTimer);
          this.stopRing();
          await this.startMic();
          this.setState('active', 'na escuta');
        } else if (msg.type === 'audio' && msg.data) {
          this.playPcm(unb64(msg.data));
        } else if (msg.type === 'interrupted') {
          this.flushPlayback();
        } else if (msg.type === 'text') {
          const texto = String(msg.text || '').trim();
          if (msg.role === 'sentury') {
            if (texto) { this.merge('assistant', texto); this.listeners.onCaption(texto); }
          } else if (msg.role === 'user') {
            if (texto) this.merge('user', texto);
            this.listeners.onCaption('você falou na chamada');
          }
        } else if (msg.type === 'tool') {
          this.listeners.onActivity('thinking');
          this.listeners.onCaption('consultando dados…');
        } else if (msg.type === 'error') {
          this.fail('indisponível', msg.detail || 'Não foi possível ligar.');
        }
      };
      this.ws.onerror = () => this.fail('erro de conexão', 'Ocorreu um erro de conexão com o servidor.');
      this.ws.onclose = () => {
        if (this.state !== 'idle' && this.state !== 'error') {
          this.fail('desconectado', 'A ligação foi encerrada inesperadamente.');
        }
      };
    } catch (reason) {
      this.fail('sem microfone', reason instanceof Error ? reason.message : String(reason));
    }
  }

  async toggleScreen(): Promise<void> {
    if (this.screenStream) { this.stopScreen(); return; }
    if (this.state !== 'active') return;
    try {
      this.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 }, audio: false });
    } catch {
      return;
    }
    this.screenVideo = document.createElement('video');
    this.screenVideo.srcObject = this.screenStream;
    this.screenVideo.muted = true;
    await this.screenVideo.play().catch(() => undefined);
    this.screenCanvas = document.createElement('canvas');
    this.listeners.onScreenShare(true);
    this.listeners.onCaption('compartilhando a tela…');
    const track = this.screenStream.getVideoTracks()[0];
    if (track) track.onended = () => this.stopScreen();
    this.screenTimer = window.setInterval(() => this.sendScreenFrame(), SCREEN_EVERY_MS);
  }

  private sendScreenFrame(): void {
    const video = this.screenVideo;
    const canvas = this.screenCanvas;
    if (!video || !canvas || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) return;
    const escala = Math.min(1, SCREEN_W / vw);
    canvas.width = Math.round(vw * escala);
    canvas.height = Math.round(vh * escala);
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dados = canvas.toDataURL('image/jpeg', 0.6).split(',')[1];
    if (dados) this.ws.send(JSON.stringify({ type: 'image', data: dados }));
  }

  stopScreen(): void {
    if (this.screenTimer) { window.clearInterval(this.screenTimer); this.screenTimer = null; }
    if (this.screenStream) { this.screenStream.getTracks().forEach(t => t.stop()); this.screenStream = null; }
    this.screenVideo = null;
    this.screenCanvas = null;
    this.listeners.onScreenShare(false);
    if (this.state === 'active') this.listeners.onCaption('');
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.listeners.onState(this.state, muted ? 'mudo' : 'na escuta');
  }

  private teardown(): void {
    if (this.connectTimer) { window.clearTimeout(this.connectTimer); this.connectTimer = null; }
    this.stopRing();
    this.stopScreen();
    this.flushPlayback();
    try { if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: 'end' })); } catch { /* já caiu */ }
    try { this.ws?.close(); } catch { /* já fechado */ }
    this.ws = null;
    try { this.procNode?.disconnect(); } catch { /* já solto */ }
    try { this.srcNode?.disconnect(); } catch { /* já solto */ }
    this.procNode = null;
    this.srcNode = null;
    if (this.micStream) { this.micStream.getTracks().forEach(t => t.stop()); this.micStream = null; }
    try { void this.micCtx?.close(); } catch { /* já fechado */ }
    try { void this.playCtx?.close(); } catch { /* já fechado */ }
    this.micCtx = null;
    this.playCtx = null;
    this.muted = false;
  }

  private fail(label: string, caption: string): void {
    this.teardown();
    this.setState('error', label);
    this.listeners.onCaption(caption);
  }

  hangUp(): void {
    const transcricao = this.transcript.slice();
    this.transcript = [];
    this.teardown();
    this.setState('idle', '');
    this.listeners.onCaption('');
    this.listeners.onEnd(transcricao);
  }
}
