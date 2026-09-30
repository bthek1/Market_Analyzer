import { useState } from "react";
import { Button } from "@/components/ui/button";

export function Composer({
  isRunning,
  onSend,
  onStop,
}: {
  isRunning: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
}) {
  const [input, setInput] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || isRunning) return;
    onSend(input);
    setInput("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(e as unknown as React.FormEvent);
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 flex gap-2">
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask anything… (Enter to send, Shift+Enter for newline)"
        rows={2}
        aria-label="Message"
        className="flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:ring-2 focus:ring-ring focus:outline-none"
      />
      {isRunning ? (
        // Stop stays enabled while a reply is being written - it is the control a chat user
        // reaches for most, and the backend has the run id from the `started` event.
        <Button type="button" variant="outline" onClick={onStop} className="self-end">
          Stop
        </Button>
      ) : (
        <Button type="submit" disabled={!input.trim()} className="self-end">
          Send
        </Button>
      )}
    </form>
  );
}
