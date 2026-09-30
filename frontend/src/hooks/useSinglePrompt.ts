import { useCallback, useState } from "react";
import { postChat } from "@/api/llm";

export interface UseSinglePromptReturn {
  result: string | null;
  isRunning: boolean;
  elapsedMs: number | null;
  error: string | null;
  run: (query: string, model?: string) => void;
  reset: () => void;
}

export function useSinglePrompt(): UseSinglePromptReturn {
  const [result, setResult] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback((query: string, model?: string) => {
    setResult(null);
    setElapsedMs(null);
    setError(null);
    setIsRunning(true);
    const start = Date.now();

    postChat({ messages: [{ role: "user", content: query }], model: model ?? null })
      .then((res) => {
        setResult(res.content);
        setElapsedMs(Date.now() - start);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Request failed");
        setElapsedMs(Date.now() - start);
      })
      .finally(() => {
        setIsRunning(false);
      });
  }, []);

  const reset = useCallback(() => {
    setResult(null);
    setElapsedMs(null);
    setError(null);
    setIsRunning(false);
  }, []);

  return { result, isRunning, elapsedMs, error, run, reset };
}
