import { Fragment, type ReactNode } from "react";

/**
 * Ziira's words with the little formatting a model likes to use: **bold** and "* " or "- " list lines. Nothing else is interpreted and nothing is
 * ever written as HTML. A `**` still waiting for its partner (the text is being typed out) shows as plain text until it is closed.
 */
export function formatAnswer(text: string): ReactNode {
  return text.split("\n").map((line, i) => {
    const bullet = /^\s*[*-]\s+/.exec(line);
    const body = bullet ? line.slice(bullet[0].length) : line;
    const parts = body.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
      /^\*\*[^*]+\*\*$/.test(part) ? <strong key={j} className="font-semibold">{part.slice(2, -2)}</strong> : <Fragment key={j}>{part}</Fragment>);
    return <Fragment key={i}>{i > 0 && "\n"}{bullet && "• "}{parts}</Fragment>;
  });
}
