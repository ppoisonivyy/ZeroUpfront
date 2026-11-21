import { useEffect, useState } from "react";
import { api } from "./api";

export function useResource<T>(url: string, epoch: number) {
  const [result, set] = useState<{ key: string; data?: T; error?: string }>({
    key: "",
  });
  const key = url + ":" + epoch;
  useEffect(() => {
    const controller = new AbortController();
    api(url, { signal: controller.signal })
      .then((r) => r.json())
      .then((data) => {
        if (!controller.signal.aborted) set({ key, data });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          set({
            key,
            error:
              error instanceof Error
                ? error.message
                : "The case could not be loaded.",
          });
      });
    return () => controller.abort();
  }, [url, key]);
  return key === result.key ? result : { key };
}
