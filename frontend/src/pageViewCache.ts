import { useEffect, useState } from 'react';

export type PageViewCache = Map<string, unknown>;

export function useCachedView<T>(cache: PageViewCache | undefined, key: string, initial: T) {
  const [value, setValue] = useState<T>(() => (cache?.has(key) ? (cache.get(key) as T) : initial));
  useEffect(() => {
    cache?.set(key, value);
  }, [cache, key, value]);
  return [value, setValue] as const;
}
