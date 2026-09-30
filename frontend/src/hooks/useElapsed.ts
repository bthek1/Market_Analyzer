import { useEffect, useRef, useState } from "react";

/**
 * Tracks wall-clock elapsed time for an async operation.
 *
 * Starts a timer on the rising edge of `isRunning`, freezes the final value on
 * the falling edge, and clears back to `null` whenever a new run begins. Used by
 * the chain/route compare columns, which have no built-in timer.
 */
export function useElapsed(isRunning: boolean): number | null {
  const [elapsed, setElapsed] = useState<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (isRunning) {
      startRef.current = Date.now();
      // eslint-disable-next-line react-hooks/set-state-in-effect -- edge-triggered timer reset
      setElapsed(null);
    } else if (startRef.current !== null) {
       
      setElapsed(Date.now() - startRef.current);
      startRef.current = null;
    }
  }, [isRunning]);

  return elapsed;
}
