import { cn } from "@/lib/utils";

interface Props {
  label: string;
  ok: boolean;
}

export function StatusIndicator({ label, ok }: Props) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border bg-background/80 px-2 py-0.5 text-xs font-medium backdrop-blur">
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          ok ? "bg-green-500" : "bg-red-500"
        )}
      />
      {label}
    </span>
  );
}
