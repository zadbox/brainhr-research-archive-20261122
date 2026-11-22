import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { sseManager } from '../utils/sseManager';

/**
 * Hook utilitaire pour créer des callbacks stables sans figer les deps.
 * Pattern "useEvent" officiel React (RFC).
 */
function useEvent<T extends (...args: any[]) => any>(fn?: T): T | undefined {
  const ref = useRef(fn);
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: any[]) => ref.current?.(...args), []) as T | undefined;
}

export interface SSEMessage {
  type: string;
  data: any;
}

export interface SSEOptions {
  url: string;
  onMessage: (message: SSEMessage) => void;
  onError?: (error: Error) => void;
  onOpen?: () => void;
  enabled?: boolean;
  closeOn?: string[]; // Auto-close sur ces événements (ex: ['done', 'error'])
  forceSingle?: boolean; // Si true: ferme toutes les autres connexions avant d'ouvrir
}

/**
 * Hook SSE blindé avec:
 * - Callbacks stables (pas de re-render inutiles)
 * - Singleton global (1 seule connexion par URL)
 * - Support HMR Vite (cleanup automatique)
 * - Idempotence (readyState check)
 * - Auto-close sur événements finaux
 */
export const useSSE = ({
  url,
  onMessage,
  onError,
  onOpen,
  enabled = true,
  closeOn = [],
  forceSingle = true,
}: SSEOptions) => {
  // Stabiliser les callbacks pour éviter de recréer l'effet
  const onMessageStable = useEvent(onMessage);
  const onErrorStable = useEvent(onError);
  const onOpenStable = useEvent(onOpen);

  const closeRef = useRef<() => void>(() => {});
  const close = useCallback(() => closeRef.current(), []);

  // Track previous URL to avoid reconnecting on every render
  const prevUrlRef = useRef<string>('');

  // Stabiliser closeOn avec JSON pour éviter re-renders
  const closeOnKey = JSON.stringify(closeOn);

  useEffect(() => {
    // Si désactivé ou URL vide → fermer et sortir
    if (!enabled || !url) {
      // Reset prev URL when disabled
      prevUrlRef.current = '';
      return;
    }

    // Si l'URL n'a pas changé, ne rien faire
    if (prevUrlRef.current === url) {
      console.log('[useSSE] URL inchangée, skip reconnection');
      return;
    }

    // Sauvegarder la nouvelle URL
    prevUrlRef.current = url;

    // Option: garantir une seule connexion (toutes URLs confondues)
    if (forceSingle) {
      console.log('[useSSE] forceSingle: fermeture de toutes les connexions existantes');
      sseManager.closeAll();
    }

    console.log(`[useSSE] Activation pour: ${url}`);

    // Wrapper pour parser les événements SSE
    const handleMessage = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        onMessageStable?.({ type: 'message', data });
      } catch (err) {
        console.error('[useSSE] Failed to parse message:', err, ev.data);
      }
    };

    const handleOpen = () => {
      console.log('[useSSE] Connexion ouverte');
      onOpenStable?.();
    };

    const handleError = (ev: Event) => {
      console.error('[useSSE] Erreur de connexion:', ev);
      onErrorStable?.(new Error('SSE connection error'));
    };

    // Handlers pour événements custom (progress, result, error, done)
    const customEventHandlers = new Map<string, (ev: MessageEvent) => void>();
    for (const eventType of ['progress', 'result', 'error', 'done']) {
      const handler = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data);
          onMessageStable?.({ type: eventType, data });
        } catch (err) {
          console.error(`[useSSE] Failed to parse ${eventType}:`, err, ev.data);
        }
      };
      customEventHandlers.set(eventType, handler);
    }

    // Attacher tous les handlers via le manager
    const disconnect = sseManager.attach(url, {
      message: handleMessage,
      open: handleOpen,
      error: handleError,
      doneEvents: closeOn,
    });

    // Ajouter les handlers pour événements custom
    const es = sseManager.open(url);
    for (const [eventType, handler] of customEventHandlers.entries()) {
      es.addEventListener(eventType, handler as EventListener);
    }

    // Exposer la fermeture courante
    closeRef.current = () => {
      console.log('[useSSE] Cleanup: fermeture connexion');
      // Retirer les handlers custom
      for (const [eventType, handler] of customEventHandlers.entries()) {
        es.removeEventListener(eventType, handler as EventListener);
      }
      disconnect();
      sseManager.close(url);
    };

    // Cleanup à l'unmount
    return () => {
      closeRef.current();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, url, forceSingle, closeOnKey, onMessageStable, onErrorStable, onOpenStable]);

  return {
    close,
    isConnected: true, // Pourrait être amélioré avec un state réel
  };
};
