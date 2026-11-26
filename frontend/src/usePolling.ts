import { useEffect, useRef } from 'react';

type Polling = {
  load: (signal: AbortSignal) => Promise<void>;
  active: boolean;
  interval: number;
  refreshKey: string | number;
  enabled?: boolean;
};

export function usePolling({ load, active, interval, refreshKey, enabled = true }: Polling) {
  const latest = useRef(load);
  const trigger = useRef<() => void>(() => {});
  useEffect(() => {
    latest.current = load;
  }, [load]);

  useEffect(() => {
    if (!enabled) return;
    let inFlight: AbortController | undefined;

    function stop() {
      inFlight?.abort();
      inFlight = undefined;
    }

    function refresh() {
      if (globalThis.document?.visibilityState === 'hidden' || inFlight) return;
      const request = new AbortController();
      inFlight = request;
      void latest.current(request.signal).finally(() => {
        if (inFlight === request) inFlight = undefined;
      });
    }

    function visibilityChanged() {
      if (globalThis.document?.visibilityState === 'hidden') stop();
      else refresh();
    }

    trigger.current = refresh;
    globalThis.document?.addEventListener('visibilitychange', visibilityChanged);
    globalThis.window?.addEventListener?.('focus', refresh);
    refresh();
    return () => {
      trigger.current = () => {};
      stop();
      globalThis.document?.removeEventListener('visibilitychange', visibilityChanged);
      globalThis.window?.removeEventListener?.('focus', refresh);
    };
  }, [enabled, refreshKey]);

  useEffect(() => {
    if (!enabled || !active || typeof window === 'undefined') return;
    const timer = window.setInterval(() => trigger.current(), interval);
    return () => window.clearInterval(timer);
  }, [enabled, active, interval, refreshKey]);
}
