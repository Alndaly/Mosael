export function nodeLabels(locale: string) {
  return locale === "en-US"
    ? {
        imageLink: "Image address",
        alt: "Alternative text",
        apply: "Apply image changes",
        cancel: "Cancel image changes",
        invalid:
          "Use an https:// image address or an existing media reference.",
        unavailable: "Image unavailable",
        language: "Code language",
        plain: "Plain text",
        copy: "Copy code",
        copied: "Copied",
        failed: "Could not copy. Select the code and copy it manually.",
      }
    : {
        imageLink: "图片链接",
        alt: "替代文字",
        apply: "应用图片修改",
        cancel: "取消图片修改",
        invalid: "请输入 https:// 图片地址或已有的素材引用。",
        unavailable: "图片无法显示",
        language: "代码语言",
        plain: "纯文本",
        copy: "复制代码",
        copied: "已复制",
        failed: "复制失败，请选中代码手动复制。",
      };
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
