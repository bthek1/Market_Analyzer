import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";
import { deleteChatSession, fetchChatSessions, renameChatSession } from "@/api/chat";
import { queryKeys } from "@/api/queryKeys";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ChatSessionSummary } from "@/types/chat";

/** The first message, when the title task has not landed (or failed - blank is supported). */
function label(session: ChatSessionSummary): string {
  return session.title || "Untitled conversation";
}

function Row({
  session,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  session: ChatSessionSummary;
  active: boolean;
  onOpen: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.title);

  if (editing) {
    return (
      <div className="flex items-center gap-1 rounded-md border bg-background p-1">
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              onRename(draft);
              setEditing(false);
            }
            if (e.key === "Escape") setEditing(false);
          }}
          className="min-w-0 flex-1 bg-transparent px-1 text-xs focus:outline-none"
          aria-label="Conversation title"
        />
        <button
          onClick={() => {
            onRename(draft);
            setEditing(false);
          }}
          aria-label="Save title"
          className="text-muted-foreground hover:text-foreground"
        >
          <Check className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => setEditing(false)}
          aria-label="Cancel rename"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group flex items-center gap-1 rounded-md px-2 py-1.5 text-xs",
        active ? "bg-accent text-accent-foreground" : "hover:bg-muted/60",
      )}
    >
      <button onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-2 text-left">
        <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate">{label(session)}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground">
          {session.turn_count}
        </span>
      </button>
      <button
        onClick={() => {
          setDraft(session.title);
          setEditing(true);
        }}
        aria-label={`Rename ${label(session)}`}
        className="opacity-0 transition-opacity group-hover:opacity-100 text-muted-foreground hover:text-foreground"
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={onDelete}
        aria-label={`Delete ${label(session)}`}
        className="opacity-0 transition-opacity group-hover:opacity-100 text-muted-foreground hover:text-destructive"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/**
 * The conversation list. Ordered by the server (`-updated_at`), so a session jumps to the
 * top when it gets a new turn - the sidebar's ordering is activity, not creation.
 */
export function SessionSidebar({
  activeId,
  onOpen,
  onNew,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: sessions = [], isLoading } = useQuery({
    queryKey: queryKeys.chat.sessions(),
    queryFn: fetchChatSessions,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      renameChatSession(id, title),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: deleteChatSession,
    onSuccess: (_data, id) => {
      // Deleting the open conversation cascades its turns, so the transcript on screen no
      // longer exists - start a fresh one rather than leaving it showing deleted rows.
      if (id === activeId) onNew();
      invalidate();
    },
  });

  return (
    <aside className="flex w-60 shrink-0 flex-col gap-2 rounded-lg border bg-card p-2">
      <Button size="sm" variant="outline" onClick={onNew} className="justify-start gap-2">
        <Plus className="h-3.5 w-3.5" />
        New chat
      </Button>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">Loading…</p>
        ) : sessions.length === 0 ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">
            No conversations yet.
          </p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {sessions.map((session) => (
              <Row
                key={session.id}
                session={session}
                active={session.id === activeId}
                onOpen={() => onOpen(session.id)}
                onRename={(title) => rename.mutate({ id: session.id, title })}
                onDelete={() => remove.mutate(session.id)}
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
