/**
 * Wrapper fetch avec traces complètes pour debugging
 * Génère un request ID et log toutes les étapes
 */

import { createClientId } from './uuid';

interface FetchWithTraceResult<T = unknown> {
  requestId: string;
  response: Response;
  data: T;
  duration: number;
}

export async function fetchWithTrace<T = unknown>(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<FetchWithTraceResult<T>> {
  // Générer request ID
  const requestId = createClientId();

  // Extraire URL
  const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : (input as Request).url;

  // Timer
  const startTime = performance.now();

  // Log requête (groupe collapsed)
  console.groupCollapsed(`[REQ ${requestId.slice(0, 8)}] ${init.method ?? 'GET'} ${url}`);
  console.log('📤 Request ID:', requestId);
  console.log('🔗 URL:', url);
  console.log('⚙️  Init:', init);

  // Ajouter request ID aux headers
  const headersInit = init.headers instanceof Headers
    ? Object.fromEntries(init.headers.entries())
    : Array.isArray(init.headers)
      ? Object.fromEntries(init.headers)
      : (init.headers as Record<string, string> | undefined);

  const headers = {
    ...headersInit,
    'x-request-id': requestId,
  };

  try {
    // Exécuter fetch
    const response = await fetch(input, { ...init, headers });

    // Durée
    const duration = Math.round(performance.now() - startTime);

    // Log réponse
    const statusEmoji = response.ok ? '✅' : '❌';
    console.log(`${statusEmoji} Status:`, response.status, response.statusText);
    console.log('⏱️  Duration:', `${duration}ms`);
    console.log('📥 Headers:', Object.fromEntries(response.headers.entries()));

    // Parser réponse
    const contentType = response.headers.get('content-type');
    let data: T;

    if (contentType?.includes('application/json')) {
      data = (await response.json()) as T;
      console.log('📦 Data:', data);
    } else {
      const text = await response.text();
      console.log('📝 Text:', text.slice(0, 200) + (text.length > 200 ? '...' : ''));
      data = text as unknown as T;
    }

    console.groupEnd();

    return {
      requestId,
      response,
      data,
      duration,
    };
  } catch (error) {
    const duration = Math.round(performance.now() - startTime);

    console.error('❌ Error:', error);
    console.log('⏱️  Duration:', `${duration}ms`);
    console.groupEnd();

    throw error;
  }
}

/**
 * Wrapper EventSource avec traces pour SSE
 */
export class EventSourceWithTrace extends EventSource {
  private connectionId: string;
  private connectionStart: number;

  constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
    super(url, eventSourceInitDict);

    this.connectionId = createClientId();
    this.connectionStart = performance.now();

    console.log(`[SSE ${this.connectionId.slice(0, 8)}] 🔌 Opening connection to ${url}`);

    // Log events
    this.addEventListener('open', () => {
      const duration = Math.round(performance.now() - this.connectionStart);
      console.log(`[SSE ${this.connectionId.slice(0, 8)}] ✅ Connected (${duration}ms)`);
    });

    this.addEventListener('error', (event) => {
      const duration = Math.round(performance.now() - this.connectionStart);
      console.error(`[SSE ${this.connectionId.slice(0, 8)}] ❌ Error (${duration}ms)`, event);
    });

    // Wrapper close pour logger
    const originalClose = this.close.bind(this);
    this.close = () => {
      const duration = Math.round(performance.now() - this.connectionStart);
      console.log(`[SSE ${this.connectionId.slice(0, 8)}] 🔌 Connection closed (${duration}ms)`);
      originalClose();
    };
  }

  /**
   * Log un message reçu
   */
  logMessage(event: string, data: unknown) {
    console.log(`[SSE ${this.connectionId.slice(0, 8)}] 📨 ${event}:`, data);
  }
}
