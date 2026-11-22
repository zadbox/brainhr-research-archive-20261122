/**
 * SSE Manager - Singleton global pour gérer les connexions EventSource
 *
 * Garantit qu'il n'y a jamais plus d'une connexion SSE par URL.
 * Compatible avec HMR de Vite (fermeture automatique lors du hot reload).
 */

type SSEHandlers = {
  message?: (ev: MessageEvent) => void;
  open?: (ev: Event) => void;
  error?: (ev: Event) => void;
  doneEvents?: string[]; // ex: ['done', 'error'] pour auto-close
};

class SSEManager {
  private sources = new Map<string, EventSource>();
  private listeners = new Map<string, Set<[string, EventListener]>>();

  /**
   * Ouvre une connexion SSE pour l'URL donnée.
   * Si une connexion existe déjà, la retourne.
   */
  open(url: string): EventSource {
    const existing = this.sources.get(url);
    if (existing && existing.readyState !== EventSource.CLOSED) {
      console.log(`[SSEManager] Connexion existante réutilisée: ${url}`);
      return existing;
    }

    console.log(`[SSEManager] Nouvelle connexion SSE: ${url}`);
    const es = new EventSource(url, { withCredentials: true });
    this.sources.set(url, es);
    this.listeners.set(url, new Set());
    return es;
  }

  /**
   * Attache des handlers à une connexion SSE.
   * Retourne une fonction de nettoyage.
   */
  attach(url: string, h: SSEHandlers): () => void {
    const es = this.open(url);
    const listenerSet = this.listeners.get(url)!;

    const add = (type: string, fn: EventListener) => {
      es.addEventListener(type, fn);
      listenerSet.add([type, fn]);
    };

    if (h.message) add('message', h.message as EventListener);
    if (h.open) add('open', h.open as EventListener);
    if (h.error) add('error', h.error as EventListener);

    // Auto-close sur événements finaux (ex: 'done', 'error')
    for (const eventType of h.doneEvents ?? []) {
      const autoCloseHandler = () => {
        console.log(`[SSEManager] Auto-close sur événement: ${eventType}`);
        window.setTimeout(() => this.close(url), 0);
      };
      add(eventType, autoCloseHandler);
    }

    // Retourne une fonction de nettoyage
    return () => this.detach(url);
  }

  /**
   * Détache tous les handlers d'une URL
   */
  detach(url: string) {
    const es = this.sources.get(url);
    if (!es) return;

    const listenerSet = this.listeners.get(url);
    if (!listenerSet) return;

    for (const [type, fn] of Array.from(listenerSet.values())) {
      es.removeEventListener(type, fn);
    }
    listenerSet.clear();
  }

  /**
   * Ferme proprement une connexion SSE
   */
  close(url: string) {
    const es = this.sources.get(url);
    if (es) {
      console.log(`[SSEManager] Fermeture connexion: ${url}`);
      es.close(); // readyState passe à CLOSED
      this.detach(url);
      this.sources.delete(url);
      this.listeners.delete(url);
    }
  }

  /**
   * Ferme toutes les connexions SSE actives
   */
  closeAll() {
    console.log(`[SSEManager] Fermeture de toutes les connexions (${this.sources.size})`);
    for (const url of Array.from(this.sources.keys())) {
      this.close(url);
    }
  }

  /**
   * Retourne le nombre de connexions actives
   */
  getActiveCount(): number {
    return this.sources.size;
  }
}

export const sseManager = new SSEManager();

// 🔥 HMR Cleanup: Fermeture forcée à chaque remplacement à chaud
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    console.log('[SSEManager] HMR dispose: fermeture de toutes les connexions');
    sseManager.closeAll();
  });
}
