const STORAGE_KEYS = {
  apiUrl: 'sentury_api_url',
  userId: 'sentury_user_id',
  token: 'sentury_api_token',
  mode: 'sentury_intel_mode',
  effort: 'sentury_effort_default',
  userIdManual: 'sentury_user_id_manual',
} as const;

export type SenturyMode = 'router' | 'ultra' | 'ultra_max';
export type SenturyEffort = 'auto' | 'low' | 'medium' | 'high';

function read(key: string): string {
  try {
    return window.localStorage.getItem(key) || '';
  } catch {
    return '';
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A configuração continua válida apenas para o estado React desta página.
  }
}

function createUserId(): string {
  const id = `local-${crypto.randomUUID()}`;
  try {
    window.localStorage.setItem(STORAGE_KEYS.userId, id);
  } catch {
    // Stateless browser contexts can still use the ID for this page lifetime.
  }
  return id;
}

/** Adota a identidade que o servidor mantem para esta maquina.
 *
 * `localStorage` e por origem, entao um id nascido aqui muda a cada porta.
 * Id escolhido na tela de conexao continua valendo.
 */
export async function adotarIdentidadeDaMaquina(): Promise<string> {
  const atual = read(STORAGE_KEYS.userId);
  if (read(STORAGE_KEYS.userIdManual) === '1') return atual || createUserId();
  try {
    const base = read(STORAGE_KEYS.apiUrl).replace(/\/+$/, '');
    const resposta = await fetch(`${base}/sentury/identidade`, { headers: authHeaders() });
    if (!resposta.ok) return atual || createUserId();
    const dados = await resposta.json() as { user_id?: string };
    const doServidor = String(dados?.user_id || '').trim();
    if (!doServidor) return atual || createUserId();
    if (doServidor !== atual) write(STORAGE_KEYS.userId, doServidor);
    return doServidor;
  } catch {
    // Servidor fora do ar: segue com o que ja existe.
    return atual || createUserId();
  }
}

export function getRuntimeConfig() {
  const storedMode = read(STORAGE_KEYS.mode);
  const mode: SenturyMode = storedMode === 'ultra' || storedMode === 'ultra_max'
    ? storedMode
    : 'router';
  const storedEffort = read(STORAGE_KEYS.effort);
  const effort: SenturyEffort = ['low', 'medium', 'high'].includes(storedEffort)
    ? storedEffort as SenturyEffort
    : 'auto';

  return {
    apiUrl: read(STORAGE_KEYS.apiUrl).replace(/\/+$/, ''),
    userId: read(STORAGE_KEYS.userId) || createUserId(),
    token: read(STORAGE_KEYS.token),
    mode,
    effort,
  };
}

export function authHeaders(): Record<string, string> {
  const token = getRuntimeConfig().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function setRuntimeMode(mode: SenturyMode): void {
  write(STORAGE_KEYS.mode, mode);
}

export function setRuntimeEffort(effort: SenturyEffort): void {
  write(STORAGE_KEYS.effort, effort);
}

export function setRuntimeConnection(values: { apiUrl: string; userId: string; token: string }): void {
  write(STORAGE_KEYS.apiUrl, values.apiUrl.trim().replace(/\/+$/, ''));
  write(STORAGE_KEYS.userId, values.userId.trim());
  // Id digitado e escolha: o servidor para de sobrescrever.
  write(STORAGE_KEYS.userIdManual, values.userId.trim() ? '1' : '');
  write(STORAGE_KEYS.token, values.token.trim().replace(/^Bearer\s+/i, ''));
}
