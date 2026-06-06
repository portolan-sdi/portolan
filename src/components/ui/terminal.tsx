interface TerminalLine {
  text: string;
  color?: string;
}

interface TerminalProps {
  lines?: (string | TerminalLine)[];
  title?: string;
}

export function Terminal({ lines = [], title = "portolan" }: TerminalProps) {
  return (
    <div className="bg-[var(--term-bg)] rounded-[var(--p-r-lg)] border border-[var(--term-border)] shadow-[var(--p-shadow-md)] overflow-hidden font-mono text-eyebrow sm:text-small">
      <div className="bg-[var(--term-header)] px-4 py-2.5 flex items-center gap-2 border-b border-[var(--term-border)]">
        <span className="w-2.5 h-2.5 rounded-full bg-[var(--term-dot-red)]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[var(--term-dot-yellow)]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[var(--term-dot-green)]" />
        <span className="ml-3 text-[var(--term-title)] text-eyebrow">{title}</span>
      </div>
      <div className="px-4 py-4 text-[var(--term-text)] leading-relaxed overflow-x-auto">
        {lines.map((line, i) => {
          if (typeof line === "string") {
            return (
              <div key={i} className="whitespace-pre">
                {line}
              </div>
            );
          }
          return (
            <div
              key={i}
              className="whitespace-pre"
              style={{ color: line.color || "var(--term-text)" }}
            >
              {line.text}
            </div>
          );
        })}
      </div>
    </div>
  );
}
