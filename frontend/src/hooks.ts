import { useCallback, useEffect, useRef, useState } from "react";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/** Ejecuta `fn` cada `ms` mientras `active` sea true. */
export function useInterval(fn: () => void, ms: number, active: boolean) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => ref.current(), ms);
    return () => window.clearInterval(id);
  }, [ms, active]);
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(
    (silent = false) => {
      const my = ++seq.current;
      if (!silent) setLoading(true);
      fn()
        .then((d) => {
          if (my === seq.current) {
            setData(d);
            setError(null);
          }
        })
        .catch((e: Error) => {
          if (my === seq.current) setError(e.message);
        })
        .finally(() => {
          if (my === seq.current) setLoading(false);
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    deps,
  );
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}
