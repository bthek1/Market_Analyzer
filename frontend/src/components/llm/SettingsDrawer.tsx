import { cn } from "@/lib/utils";
import { LLMSettingsForm } from "@/components/llm/LLMSettingsForm";

// Right-side drawer reusing the HistoryDrawer pattern from the Agents page:
// fixed panel + translate-x transition + backdrop. Houses the runtime LLM
// settings form so settings live next to the workflows they configure.
export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} />}
      <div
        className={cn(
          "fixed right-0 top-0 z-50 h-full w-[28rem] max-w-full border-l bg-background shadow-xl transition-transform duration-200",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        {open && (
          <>
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h2 className="text-sm font-semibold">Settings</h2>
              <button
                className="text-lg leading-none text-muted-foreground hover:text-foreground"
                onClick={onClose}
                aria-label="Close settings"
              >
                ×
              </button>
            </div>
            <div className="h-[calc(100%-49px)] overflow-y-auto p-4">
              <LLMSettingsForm onSaved={onClose} />
            </div>
          </>
        )}
      </div>
    </>
  );
}
