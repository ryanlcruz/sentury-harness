import { useSyncExternalStore } from 'react';

const EVENT = 'sentury:preference-change';

function ler(chave: string, padrao: boolean): boolean {
  try {
    const valor = window.localStorage.getItem(chave);
    return valor === null ? padrao : valor === '1';
  } catch {
    return padrao;
  }
}

function gravar(chave: string, valor: boolean): void {
  try {
    window.localStorage.setItem(chave, valor ? '1' : '0');
  } catch {
    // Mantém o padrão desta página quando o storage não está disponível.
  }
  window.dispatchEvent(new CustomEvent(EVENT));
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  window.addEventListener('storage', listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener('storage', listener);
  };
}

const PROCESS_TRACE_KEY = 'sentury_process_trace';
const VOICE_CALL_KEY = 'sentury_voice_call';

export function getProcessTraceEnabled(): boolean {
  return ler(PROCESS_TRACE_KEY, true);
}

export function setProcessTraceEnabled(enabled: boolean): void {
  gravar(PROCESS_TRACE_KEY, enabled);
}

export function useProcessTraceEnabled(): boolean {
  return useSyncExternalStore(subscribe, getProcessTraceEnabled, () => true);
}

// Ligação por voz é opt-in: mesmo com modelo capaz, só aparece se o usuário ligar.
export function getVoiceCallEnabled(): boolean {
  return ler(VOICE_CALL_KEY, false);
}

export function setVoiceCallEnabled(enabled: boolean): void {
  gravar(VOICE_CALL_KEY, enabled);
}

export function useVoiceCallEnabled(): boolean {
  return useSyncExternalStore(subscribe, getVoiceCallEnabled, () => false);
}
