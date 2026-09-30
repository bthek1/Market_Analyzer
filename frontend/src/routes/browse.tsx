import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { AnswerPanel } from "@/components/browser/AnswerPanel";
import { RunHistory } from "@/components/browser/RunHistory";
import { SearchBar } from "@/components/browser/SearchBar";
import { StepTimeline } from "@/components/browser/StepTimeline";
import { useBrowserAgent } from "@/hooks/useBrowserAgent";
import { useLLMSettings } from "@/hooks/useLLMSettings";
import type { BrowserProvider } from "@/types/browser";

/**
 * The browser agent's own page. Deliberately NOT a mode on /agents: that page compares
 * LLM workflows over one query side by side, while a browser run is a single minutes-long,
 * concurrency-capped search whose output is visual (steps, screenshots, sources).
 */
function Disabled({ detail, hint }: { detail: string; hint: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-lg rounded-lg border bg-card p-6 text-center">
        <h2 className="text-base font-semibold">Web search is switched off</h2>
        <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
        {hint && (
          <p className="mt-3 text-xs text-muted-foreground">{hint}</p>
        )}
      </div>
    </div>
  );
}

function BrowsePage() {
  const { data: settings } = useLLMSettings();
  const agent = useBrowserAgent();

  const disabledByServer = agent.disabled;
  const disabledBySettings =
    settings && !settings.browser_enabled && !agent.runId
      ? {
          detail: "The browser agent is disabled.",
          hint: "Enable it under LLM Settings once a Chrome/Chromium binary is installed on the server.",
        }
      : null;
  const disabled = disabledByServer ?? disabledBySettings;

  return (
    <AppShell>
      <div className="flex gap-4">
        <RunHistory activeId={agent.runId} onSelect={agent.loadFromDetail} />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div>
            <h1 className="text-lg font-semibold">Browse</h1>
            <p className="text-xs text-muted-foreground">
              An agent that drives a real browser to answer a question from the live
              web.
            </p>
          </div>

          {disabled ? (
            <Disabled detail={disabled.detail} hint={disabled.hint} />
          ) : (
            <>
              <SearchBar
                query={agent.query}
                onQueryChange={agent.setQuery}
                onRun={(opts) => agent.run(agent.query, opts)}
                onStop={agent.stop}
                isRunning={agent.isRunning}
                defaultProvider={
                  (settings?.browser_provider as BrowserProvider) ?? "ollama"
                }
                defaultMaxSteps={settings?.browser_max_steps ?? 15}
              />

              <AnswerPanel
                output={agent.output}
                sources={agent.sources}
                stopReason={agent.stopReason}
                error={agent.error}
              />

              <StepTimeline
                steps={agent.steps}
                runId={agent.runId}
                maxSteps={agent.maxSteps}
                isRunning={agent.isRunning}
              />
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}

export const Route = createFileRoute("/browse")({
  component: BrowsePage,
});
