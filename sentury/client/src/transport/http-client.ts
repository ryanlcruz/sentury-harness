export /** O `detail` do servidor, quando houver: "status 403" sozinho nao explica nada. */
async function motivo(res: Response, verbo: string, path: string): Promise<string> {
  // Sem token a tela inteira falha; dizer onde configurar resolve na hora.
  if (res.status === 401) return 'A API pediu um token e ele está ausente ou errado. Confira em Configurações, no campo Token da API.';
  try {
    const corpo = await res.json() as { detail?: unknown };
    const texto = typeof corpo?.detail === 'string' ? corpo.detail.trim() : '';
    if (texto) return texto;
  } catch {
    // resposta sem JSON: fica a mensagem generica
  }
  return `${verbo} ${path} falhou com status ${res.status}`;
}

class HttpClient {
  private baseUrl: string;

  constructor(baseUrl: string = '') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  public setBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/$/, '');
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  public async get<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const res = await fetch(url, {
      ...options,
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        ...(options?.headers || {}),
      },
    });

    if (!res.ok) throw new Error(await motivo(res, 'GET', path));

    return res.json() as Promise<T>;
  }

  public async post<T>(path: string, body: any, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const res = await fetch(url, {
      ...options,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...(options?.headers || {}),
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) throw new Error(await motivo(res, 'POST', path));

    return res.json() as Promise<T>;
  }

  public async patch<T>(path: string, body: unknown, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const res = await fetch(url, {
      ...options,
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...(options?.headers || {}),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await motivo(res, 'PATCH', path));
    return res.json() as Promise<T>;
  }

  public async put<T>(path: string, body: unknown, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const res = await fetch(url, {
      ...options,
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...(options?.headers || {}),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await motivo(res, 'PUT', path));
    return res.json() as Promise<T>;
  }

  public async delete<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const res = await fetch(url, {
      ...options,
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
        ...(options?.headers || {}),
      },
    });
    if (!res.ok) throw new Error(await motivo(res, 'DELETE', path));
    return res.json() as Promise<T>;
  }
}

export const apiClient = new HttpClient();
