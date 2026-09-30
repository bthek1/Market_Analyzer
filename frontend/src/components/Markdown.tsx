import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown renderer with GitHub-Flavored Markdown enabled (tables, strikethrough,
 * task lists, autolinks). Plain `react-markdown` only parses CommonMark, so LLM
 * output containing tables would otherwise render as raw text.
 */
export function Markdown({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>;
}
