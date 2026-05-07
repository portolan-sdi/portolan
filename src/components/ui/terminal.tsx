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
    <div className="bg-[#0e1230] rounded-[var(--p-r-lg)] border border-[#1c2452] shadow-[var(--p-shadow-md)] overflow-hidden font-mono text-[13px]">
      <div className="bg-[#161c44] px-4 py-2.5 flex items-center gap-2 border-b border-[#1c2452]">
        <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]" />
        <span className="ml-3 text-[#8d96bd] text-xs">{title}</span>
      </div>
      <div className="px-4 py-4 text-[#c5cce8] leading-relaxed">
        {lines.map((line, i) => {
          if (typeof line === "string") {
            return <div key={i}>{line}</div>;
          }
          return (
            <div key={i} style={{ color: line.color || "#c5cce8" }}>
              {line.text}
            </div>
          );
        })}
      </div>
    </div>
  );
}
