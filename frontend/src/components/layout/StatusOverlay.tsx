import { useSystemStatus } from "@/hooks/useSystemStatus";
import { StatusIndicator } from "@/components/layout/StatusIndicator";

export function StatusBar() {
  const { version, backendOk, dbOk, redisOk, celeryOk, beatOk, ollamaOk } = useSystemStatus();

  return (
    <footer className="border-t bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-9 max-w-7xl items-center gap-3 px-6">
        <span className="text-xs font-medium text-muted-foreground">{version}</span>
        <div className="flex items-center gap-1.5">
          <StatusIndicator label="API" ok={backendOk} />
          <StatusIndicator label="DB" ok={dbOk} />
          <StatusIndicator label="Redis" ok={redisOk} />
          <StatusIndicator label="Celery" ok={celeryOk} />
          <StatusIndicator label="Beat" ok={beatOk} />
          <StatusIndicator label="Ollama" ok={ollamaOk} />
        </div>
      </div>
    </footer>
  );
}

/** @deprecated use StatusBar inside AppShell */
export function StatusOverlay() {
  return <StatusBar />;
}
