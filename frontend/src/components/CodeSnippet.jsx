import React from "react";

// Shows the lines around the offending import, highlighting the import itself.
// `snippet` lines look like "  12: from x import y" (see backend read_snippet).
export default function CodeSnippet({ snippet, highlightLine }) {
  if (!snippet) return <div className="empty">Source not available.</div>;
  const lines = snippet.split("\n").map((raw) => {
    const m = /^\s*(\d+): ?(.*)$/.exec(raw);
    return m ? { n: Number(m[1]), text: m[2] } : { n: null, text: raw };
  });
  return (
    <pre className="code-snippet" data-testid="code-snippet">
      {lines.map((l, i) => (
        <div key={i} className={`code-line ${l.n === highlightLine ? "hit" : ""}`} data-hit={l.n === highlightLine ? "true" : undefined}>
          <span className="code-no">{l.n ?? ""}</span>
          <span className="code-text">{l.text || " "}</span>
        </div>
      ))}
    </pre>
  );
}
