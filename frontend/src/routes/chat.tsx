import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { WorkspaceSwitch } from "@/components/layout/WorkspaceSwitch";
import { Composer } from "@/components/chat/Composer";
import { SessionSidebar } from "@/components/chat/SessionSidebar";
import { Transcript } from "@/components/chat/Transcript";
import { useChatAgent } from "@/hooks/useChatAgent";

/**
 * The chat agent's own page (issue #8).
 *
 * Standalone, like /browse, and for the same reason: /agents compares one-shot workflows
 * over a single query side by side, and a conversation is not comparable to a one-shot run.
 * It is absent from COMPARABLE_TYPES and from fetchAllRuns() on purpose.
 */
function ChatPage() {
  const chat = useChatAgent();

  return (
    <AppShell>
      <div className="flex gap-4">
        <SessionSidebar
          activeId={chat.sessionId}
          onOpen={chat.openSession}
          onNew={chat.newSession}
        />

        <div className="flex h-[calc(100vh-10rem)] min-w-0 flex-1 flex-col">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <WorkspaceSwitch active="/chat" />
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold">
                {chat.title || "Chat"}
              </h1>
              <p className="text-xs text-muted-foreground">
                A conversational agent that can read this application's own market data.
              </p>
            </div>
          </div>

          {chat.error && (
            <div className="mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {chat.error}
            </div>
          )}

          <Transcript
            turns={chat.turns}
            summary={chat.summary}
            isRunning={chat.isRunning}
          />

          <Composer
            isRunning={chat.isRunning}
            onSend={chat.send}
            onStop={chat.stop}
          />
        </div>
      </div>
    </AppShell>
  );
}

export const Route = createFileRoute("/chat")({
  component: ChatPage,
});
