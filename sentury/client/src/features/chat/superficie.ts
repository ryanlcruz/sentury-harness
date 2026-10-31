import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

export type Superficie = 'navegador' | 'computador';

async function chamar<T>(superficie: Superficie, acao: 'estado' | 'encerrar' | 'assumir' | 'devolver', sessionId: string): Promise<T> {
  apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
  return apiClient.post<T>(`/sentury/${superficie}/${acao}`, { session_id: sessionId }, { headers: authHeaders() });
}

export async function superficieAberta(superficie: Superficie, sessionId: string): Promise<boolean> {
  const resposta = await chamar<{ aberta: boolean }>(superficie, 'estado', sessionId);
  return Boolean(resposta.aberta);
}

export async function encerrarSuperficie(superficie: Superficie, sessionId: string): Promise<void> {
  await chamar(superficie, 'encerrar', sessionId);
}

export interface VezNoServidor {
  com: string;
  motivo: string;
}

/** O computador: a sessão desta conversa e de quem é a vez agora. */
export async function estadoDoComputador(sessionId: string): Promise<{ aberta: boolean; vez: VezNoServidor | null }> {
  const resposta = await chamar<{ aberta: boolean; vez?: VezNoServidor }>('computador', 'estado', sessionId);
  return { aberta: Boolean(resposta.aberta), vez: resposta.vez || null };
}

export async function assumirComputador(sessionId: string): Promise<VezNoServidor> {
  return (await chamar<{ vez: VezNoServidor }>('computador', 'assumir', sessionId)).vez;
}

export async function devolverComputador(sessionId: string): Promise<VezNoServidor> {
  return (await chamar<{ vez: VezNoServidor }>('computador', 'devolver', sessionId)).vez;
}
