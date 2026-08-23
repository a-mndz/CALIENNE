import { useState, useMemo } from "react";
import { Copy, Check } from "lucide-react";
import { copyTextToClipboard } from "../utils/clipboard.js";

function CodeBlock({ code, language = "CODE", pushToast }) {
  const [copied, setCopied] = useState(false);

  const handleCopyCode = async () => {
    try {
      await copyTextToClipboard(code);
      setCopied(true);
      if (pushToast) pushToast("Copied code to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      if (pushToast) pushToast("Failed to copy code", "error");
    }
  };

  return (
    <div className="fmt-code-card">
      <div className="fmt-code-header">
        <span className="fmt-code-lang">{language.toUpperCase()}</span>
        <button
          type="button"
          className="fmt-code-copy"
          onClick={handleCopyCode}
          aria-label="Copy code block"
        >
          {copied ? (
            <>
              <Check size={12} className="text-ok" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span>Copy code</span>
            </>
          )}
        </button>
      </div>
      <div className="fmt-code-body">
        <pre className="fmt-code-pre">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

function formatJavaOrCCode(rawCode) {
  const trimmed = rawCode.trim();
  if (trimmed.includes("\n") && trimmed.split("\n").length >= 5) {
    return trimmed;
  }
  let indent = 0;
  let out = "";
  let inString = false;
  let stringChar = "";
  let parenDepth = 0;

  for (let i = 0; i < trimmed.length; i++) {
    const c = trimmed[i];

    if (inString) {
      out += c;
      if (c === stringChar && trimmed[i - 1] !== "\\") {
        inString = false;
      }
      continue;
    }

    if (c === '"' || c === "'") {
      inString = true;
      stringChar = c;
      out += c;
      continue;
    }

    if (c === "(") parenDepth++;
    if (c === ")") parenDepth = Math.max(0, parenDepth - 1);

    if (c === "{") {
      indent++;
      out += " {\n" + "    ".repeat(indent);
    } else if (c === "}") {
      indent = Math.max(0, indent - 1);
      out = out.trimEnd() + "\n" + "    ".repeat(indent) + "}\n" + "    ".repeat(indent);
    } else if (c === ";" && parenDepth === 0) {
      out += ";\n" + "    ".repeat(indent);
    } else {
      out += c;
    }
  }

  return out
    .split("\n")
    .map((l) => l.trimRight())
    .filter((l, idx, arr) => l !== "" || idx < arr.length - 1)
    .join("\n")
    .trim();
}

function splitEmbeddedCodeBlocks(str) {
  const segments = [];
  let currentText = str;

  while (currentText.length > 0) {
    const classMatch = /(?:^|\s)(public\s+class|class|interface|enum)\s+([A-Za-z0-9_]+)\s*\{/.exec(currentText);
    if (!classMatch) {
      if (currentText.trim()) {
        segments.push({ type: "text", content: currentText.trim() });
      }
      break;
    }

    const startIdx = classMatch.index + (classMatch[0].startsWith(" ") || classMatch[0].startsWith("\n") ? 1 : 0);
    const textBefore = currentText.slice(0, startIdx).trim();
    if (textBefore) {
      segments.push({ type: "text", content: textBefore });
    }

    const braceStart = currentText.indexOf("{", startIdx);
    if (braceStart === -1) {
      segments.push({ type: "text", content: currentText.slice(startIdx).trim() });
      break;
    }

    let depth = 0;
    let endIdx = -1;
    let inStr = false;
    let strCh = "";

    for (let i = braceStart; i < currentText.length; i++) {
      const ch = currentText[i];
      if (inStr) {
        if (ch === strCh && currentText[i - 1] !== "\\") inStr = false;
        continue;
      }
      if (ch === '"' || ch === "'") {
        inStr = true;
        strCh = ch;
        continue;
      }
      if (ch === "{") depth++;
      if (ch === "}") {
        depth--;
        if (depth === 0) {
          endIdx = i + 1;
          break;
        }
      }
    }

    if (endIdx === -1) {
      const rawSnippet = currentText.slice(startIdx).trim();
      segments.push({ type: "code", code: formatJavaOrCCode(rawSnippet), language: "JAVA" });
      break;
    }

    const rawCode = currentText.slice(startIdx, endIdx).trim();
    segments.push({ type: "code", code: formatJavaOrCCode(rawCode), language: "JAVA" });
    currentText = currentText.slice(endIdx).trim();
  }

  return segments;
}

function renderInlineFormatting(str) {
  if (!str) return null;
  const parts = str.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, idx) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={idx} className="fmt-inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={idx}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function renderTextStructure(textStr, baseKey) {
  let normalized = textStr
    .replace(/(^|\s)(\d+)[.)]\s+(?=[A-Z0-9'"`(])/g, "$1\n$2. ")
    .replace(/(Recommendation|Potential weaknesses|Edge cases|Summary|Analysis|Counter|Synthesis):\s*/gi, "\n\n$1:\n");

  const paragraphsOrSentences = normalized
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  const elements = [];

  paragraphsOrSentences.forEach((block, blockIdx) => {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);

    lines.forEach((line, lineIdx) => {
      const elKey = `${baseKey}-b${blockIdx}-l${lineIdx}`;

      if (/^###\s+/.test(line)) {
        elements.push(
          <div key={elKey} className="fmt-heading">
            {renderInlineFormatting(line.replace(/^###\s+/, ""))}
          </div>
        );
        return;
      }
      if (/^##\s+/.test(line)) {
        elements.push(
          <div key={elKey} className="fmt-heading">
            {renderInlineFormatting(line.replace(/^##\s+/, ""))}
          </div>
        );
        return;
      }
      if (/^#\s+/.test(line)) {
        elements.push(
          <div key={elKey} className="fmt-heading">
            {renderInlineFormatting(line.replace(/^#\s+/, ""))}
          </div>
        );
        return;
      }

      if (/^(Recommendation|Potential weaknesses|Edge cases|Summary|Analysis|Counter|Synthesis):$/i.test(line)) {
        elements.push(
          <div key={elKey} className="fmt-section-label">
            {line}
          </div>
        );
        return;
      }

      const numMatch = line.match(/^(\d+)[.)]\s+(.*)$/);
      if (numMatch) {
        elements.push(
          <div key={elKey} className="fmt-list-item">
            <span className="fmt-list-num">{numMatch[1]}.</span>
            <div className="fmt-list-content">{renderInlineFormatting(numMatch[2])}</div>
          </div>
        );
        return;
      }

      const bulletMatch = line.match(/^[-*]\s+(.*)$/);
      if (bulletMatch) {
        elements.push(
          <div key={elKey} className="fmt-list-item">
            <span className="fmt-list-bullet">•</span>
            <div className="fmt-list-content">{renderInlineFormatting(bulletMatch[1])}</div>
          </div>
        );
        return;
      }

      elements.push(
        <div key={elKey} className="fmt-paragraph">
          {renderInlineFormatting(line)}
        </div>
      );
    });
  });

  return elements;
}

function parseAndRenderTextSegment(str, segIdx, pushToast) {
  const embeddedSegments = splitEmbeddedCodeBlocks(str);
  return embeddedSegments.map((seg, subIdx) => {
    if (seg.type === "code") {
      return (
        <CodeBlock
          key={`code-emb-${segIdx}-${subIdx}`}
          code={seg.code}
          language={seg.language}
          pushToast={pushToast}
        />
      );
    }
    return (
      <div key={`text-emb-${segIdx}-${subIdx}`} className="fmt-structured-text">
        {renderTextStructure(seg.content, `${segIdx}-${subIdx}`)}
      </div>
    );
  });
}

function FormattedMessage({ text, pushToast }) {
  const parsedSegments = useMemo(() => {
    if (typeof text !== "string") return null;

    const regex = /```([a-zA-Z0-9+#-]*)\r?\n?([\s\S]*?)```/g;
    const result = [];
    let lastIdx = 0;
    let match;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIdx) {
        const textSegment = text.slice(lastIdx, match.index);
        const rendered = parseAndRenderTextSegment(textSegment, result.length, pushToast);
        result.push(...rendered);
      }

      const lang = (match[1] || "CODE").trim() || "CODE";
      const codeContent = match[2].trimEnd();
      result.push(
        <CodeBlock
          key={`code-${result.length}`}
          code={codeContent}
          language={lang}
          pushToast={pushToast}
        />
      );

      lastIdx = regex.lastIndex;
    }

    if (lastIdx < text.length) {
      const remainingText = text.slice(lastIdx);
      const rendered = parseAndRenderTextSegment(remainingText, result.length, pushToast);
      result.push(...rendered);
    }

    return result;
  }, [text, pushToast]);

  if (!text) return null;

  return <div className="fmt-message">{parsedSegments}</div>;
}

export default FormattedMessage;
