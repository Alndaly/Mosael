import { noteStrings } from "./strings";

/** 编辑器节点视图(图片、代码块)用的文案,和笔记其余文案同在 strings.ts 那张中英表里。 */
export function nodeLabels(locale: string) {
  return noteStrings(locale).node;
}
export function nodeIcon(name: "copy" | "check" | "close" | "link") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute(
    "d",
    {
      copy: "M9 9h11v11H9z M15 5V3H3v12h2",
      check: "m5 12 4 4L19 6",
      close: "m6 6 12 12M6 18 18 6",
      link: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
    }[name],
  );
  svg.append(path);
  return svg;
}
export function nodeButton(
  label: string,
  icon: Parameters<typeof nodeIcon>[0],
) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "note-node-button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(nodeIcon(icon));
  return button;
}
