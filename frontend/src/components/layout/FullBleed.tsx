import { cn } from "@/lib/utils";

/**
 * Expands a page to the full content column, cancelling AppShell's `main` padding
 * (px-6 py-8) and filling the viewport between the h-14 header and the h-9 status bar.
 *
 * Deliberately column-width, not viewport-width: with a left sidebar, a `w-screen`
 * bleed would sit under the sidebar.
 */
export function FullBleed({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative -mx-6 -my-8 h-[calc(100vh-5.75rem)] overflow-hidden border-y bg-card",
        className
      )}
    >
      {children}
    </div>
  );
}
