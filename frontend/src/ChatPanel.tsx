import React, { useState } from "react";

/** Minimal markdown → HTML for LLM responses (bold, italic, lists, line breaks). */
function renderMarkdown(text: string): string {
  return text
    // Escape HTML entities first to prevent XSS
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    // Bold and italic
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    // Inline code
    .replace(/`([^`]+)`/g, "<code style='background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:12px'>$1</code>")
    // Numbered lists: collect consecutive lines starting with "N. "
    .replace(/((?:^\d+\. .+\n?)+)/gm, (block) => {
      const items = block.trim().split("\n").map(l => `<li>${l.replace(/^\d+\. /, "")}</li>`).join("");
      return `<ol style='margin:4px 0;padding-left:18px'>${items}</ol>`;
    })
    // Bullet lists
    .replace(/((?:^[-*] .+\n?)+)/gm, (block) => {
      const items = block.trim().split("\n").map(l => `<li>${l.replace(/^[-*] /, "")}</li>`).join("");
      return `<ul style='margin:4px 0;padding-left:18px'>${items}</ul>`;
    })
    // Line breaks
    .replace(/\n/g, "<br/>");
}

interface ChatPanelProps {
  /** Superset dataset ID to scope the conversation. Passed by Explore view. */
  datasetId?: number;
  /** Superset dashboard ID to scope the conversation. Passed by Dashboard view. */
  dashboardId?: number;
}

interface ChartAction {
  type: "explore_link" | "chart_created" | "dashboard_created";
  explore_url?: string;
  chart_url?: string;
  dashboard_url?: string;
  chart_name?: string;
  dashboard_title?: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  actions?: ChartAction[];
}

const API_BASE = "/api/v1/nl_explorer";

/**
 * Floating collapsible chat panel injected into Explore and Dashboard views
 * via the Superset extension contribution API.
 */
export default function ChatPanel({ datasetId, dashboardId }: ChatPanelProps) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [conversation, setConversation] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const message = input;
    const priorConversation = conversation;
    const userMsg: Message = { role: "user", content: message };
    const nextConversation = [...priorConversation, userMsg];
    setConversation(nextConversation);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          message,
          conversation: priorConversation,
          dataset_id: datasetId ?? null,
          dashboard_id: dashboardId ?? null,
          stream: false,
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      setConversation([
        ...nextConversation,
        {
          role: "assistant",
          content: data.message || "",
          actions: data.actions || [],
        },
      ]);
    } catch (err) {
      setConversation([
        ...nextConversation,
        {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : String(err)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div style={styles.container}>
      {/* Toggle button */}
      <button style={styles.toggle} onClick={() => setOpen((o) => !o)} title="Ask Data">
        💬 Ask Data
      </button>

      {open && (
        <div style={styles.panel}>
          <div style={styles.panelHeader}>
            <span style={{ fontWeight: "bold" }}>Ask Data</span>
            <button style={styles.close} onClick={() => setOpen(false)}>
              ✕
            </button>
          </div>

          <div style={styles.messages}>
            {conversation.length === 0 && (
              <p style={styles.placeholder}>
                {datasetId
                  ? "Ask a question about this dataset…"
                  : "Ask a question about your data…"}
              </p>
            )}
            {conversation.map((msg, idx) => (
              <div
                key={idx}
                style={msg.role === "user" ? styles.userMsg : styles.assistantMsg}
              >
                {msg.role === "assistant" ? (
                  <span dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
                ) : (
                  msg.content
                )}
                {msg.actions?.map((action, aIdx) => (
                  <div key={aIdx} style={styles.actionCard}>
                    {action.type === "explore_link" && action.explore_url && (
                      <a href={action.explore_url} target="_blank" rel="noreferrer" style={styles.link}>
                        🔍 Open in Explore
                      </a>
                    )}
                    {action.type === "chart_created" && action.chart_url && (
                      <a href={action.chart_url} target="_blank" rel="noreferrer" style={styles.link}>
                        📊 View Chart: {action.chart_name}
                      </a>
                    )}
                    {action.type === "dashboard_created" && action.dashboard_url && (
                      <a href={action.dashboard_url} target="_blank" rel="noreferrer" style={styles.link}>
                        📋 View Dashboard: {action.dashboard_title}
                      </a>
                    )}
                  </div>
                ))}
              </div>
            ))}
            {loading && <div style={styles.assistantMsg}><em>Thinking…</em></div>}
          </div>

          <div style={styles.inputRow}>
            <input
              style={styles.input}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask…"
              disabled={loading}
            />
            <button
              style={styles.sendBtn}
              onClick={sendMessage}
              disabled={loading || !input.trim()}
            >
              ➤
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    position: "fixed",
    bottom: 24,
    right: 24,
    zIndex: 1000,
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    gap: 8,
    fontFamily: "sans-serif",
  },
  toggle: {
    padding: "10px 16px",
    borderRadius: 24,
    border: "none",
    background: "#1677ff",
    color: "#fff",
    fontWeight: "bold",
    cursor: "pointer",
    boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
    fontSize: 14,
  },
  panel: {
    width: 340,
    height: 460,
    background: "#fff",
    borderRadius: 12,
    boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  panelHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "12px 14px",
    borderBottom: "1px solid #eee",
    background: "#fafafa",
  },
  close: {
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: 14,
    color: "#888",
  },
  messages: {
    flex: 1,
    overflowY: "auto",
    padding: 12,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  placeholder: { color: "#aaa", fontSize: 13, textAlign: "center", margin: "auto" },
  userMsg: {
    alignSelf: "flex-end",
    background: "#e8f0fe",
    borderRadius: 10,
    padding: "8px 12px",
    fontSize: 13,
    maxWidth: "80%",
  },
  assistantMsg: {
    alignSelf: "flex-start",
    background: "#f0f0f0",
    borderRadius: 10,
    padding: "8px 12px",
    fontSize: 13,
    maxWidth: "85%",
  },
  actionCard: {
    marginTop: 6,
    padding: "6px 10px",
    background: "#fff",
    borderRadius: 6,
    border: "1px solid #ddd",
    fontSize: 12,
  },
  link: { color: "#1677ff", textDecoration: "none" },
  inputRow: {
    display: "flex",
    gap: 6,
    padding: "10px 12px",
    borderTop: "1px solid #eee",
  },
  input: {
    flex: 1,
    padding: "8px 10px",
    borderRadius: 8,
    border: "1px solid #ccc",
    fontSize: 13,
  },
  sendBtn: {
    padding: "0 12px",
    borderRadius: 8,
    border: "none",
    background: "#1677ff",
    color: "#fff",
    cursor: "pointer",
    fontSize: 16,
  },
};
