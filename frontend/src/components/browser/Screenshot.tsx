import { useEffect, useState } from "react";
import { fetchScreenshot } from "@/api/browser";
import { cn } from "@/lib/utils";

interface ScreenshotProps {
  runId: string | null;
  order: number;
  alt: string;
  className?: string;
  onClick?: () => void;
}

/**
 * Screenshots are served by an owner-checked endpoint, so a plain `<img src>` (which
 * sends no Authorization header) would 401. Fetch the bytes through the authenticated
 * client, render the object URL, and revoke it on unmount.
 */
export function Screenshot({
  runId,
  order,
  alt,
  className,
  onClick,
}: ScreenshotProps) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let objectUrl: string | null = null;
    let cancelled = false;

    fetchScreenshot(runId, order)
      .then((next) => {
        if (cancelled) {
          URL.revokeObjectURL(next);
          return;
        }
        objectUrl = next;
        setUrl(next);
      })
      .catch(() => setUrl(null));

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [runId, order]);

  if (!url) {
    return (
      <div
        className={cn(
          "shrink-0 rounded border bg-muted/40",
          className ?? "h-16 w-28",
        )}
        aria-hidden
      />
    );
  }

  return (
    <img
      src={url}
      alt={alt}
      onClick={onClick}
      className={cn(
        "shrink-0 rounded border object-cover object-top",
        onClick && "cursor-zoom-in",
        className ?? "h-16 w-28",
      )}
    />
  );
}
