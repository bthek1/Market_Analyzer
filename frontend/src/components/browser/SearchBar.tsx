import { useState } from "react";
import { Globe, Loader2, Search, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { BrowserProvider } from "@/types/browser";

const selectClass =
  "h-8 rounded-md border bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

interface SearchBarProps {
  query: string;
  onQueryChange: (value: string) => void;
  onRun: (opts: { provider?: BrowserProvider; maxSteps?: number }) => void;
  onStop: () => void;
  isRunning: boolean;
  defaultProvider: BrowserProvider;
  defaultMaxSteps: number;
}

/**
 * The page's anchor: one search box, type and press enter. Everything tunable hides
 * behind Options so the default path stays a search field and nothing else.
 */
export function SearchBar({
  query,
  onQueryChange,
  onRun,
  onStop,
  isRunning,
  defaultProvider,
  defaultMaxSteps,
}: SearchBarProps) {
  const [showOptions, setShowOptions] = useState(false);
  const [provider, setProvider] = useState<BrowserProvider>(defaultProvider);
  const [maxSteps, setMaxSteps] = useState(defaultMaxSteps);

  const submit = () => {
    if (!query.trim() || isRunning) return;
    onRun({ provider, maxSteps });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search the web"
            autoFocus
            className="h-11 pl-9 text-base"
            placeholder="Search the web..."
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
        </div>
        {isRunning ? (
          <Button variant="destructive" className="h-11 gap-2" onClick={onStop}>
            <Square className="size-4" /> Stop
          </Button>
        ) : (
          <Button
            className="h-11 gap-2"
            onClick={submit}
            disabled={!query.trim()}
          >
            <Globe className="size-4" /> Run
          </Button>
        )}
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <button
          type="button"
          className="underline-offset-2 hover:underline"
          onClick={() => setShowOptions((v) => !v)}
        >
          Options {showOptions ? "▴" : "▾"}
        </button>
        {isRunning && (
          <span className="flex items-center gap-1">
            <Loader2 className="size-3 animate-spin" /> browsing...
          </span>
        )}
      </div>

      {showOptions && (
        <div className="flex flex-wrap items-end gap-4 rounded-lg border bg-card p-3">
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground" htmlFor="provider">
              Model
            </Label>
            <select
              id="provider"
              className={selectClass}
              value={provider}
              onChange={(e) => setProvider(e.target.value as BrowserProvider)}
            >
              <option value="ollama">Ollama (local, free)</option>
              <option value="anthropic">Anthropic (needs API key)</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground" htmlFor="max-steps">
              Max steps
            </Label>
            <Input
              id="max-steps"
              type="number"
              min={1}
              max={40}
              className="h-8 w-24"
              value={maxSteps}
              onChange={(e) => setMaxSteps(Number(e.target.value))}
            />
          </div>
          <p className="max-w-md text-xs text-muted-foreground">
            The agent reads live web pages. Treat what it finds as untrusted input,
            and keep the domain allow-list in LLM Settings tight.
          </p>
        </div>
      )}
    </div>
  );
}
