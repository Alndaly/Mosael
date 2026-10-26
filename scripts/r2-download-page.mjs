/** R2 没有目录索引;给人工下载入口生成一个只含本次真实产物的静态页。 */

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

export function renderDownloadPage(files, tag) {
  const artifacts = [
    {
      file: files.find((name) => /^Mosael-.*-arm64\.dmg$/.test(name)),
      title: "macOS",
      detail: "Apple Silicon · DMG",
    },
    {
      file: files.find((name) => /^Mosael Setup .*\.exe$/i.test(name)),
      title: "Windows",
      detail: "x64 · EXE",
    },
    {
      file: files.includes("mosael-browser-extension.zip") ? "mosael-browser-extension.zip" : undefined,
      title: "Chrome 扩展",
      detail: "Chrome / Edge · ZIP",
    },
  ].filter((artifact) => artifact.file);
  const version = escapeHtml(tag.replace(/^v/, ""));
  const links = artifacts.map(({ file, title, detail }) => `      <li>
        <a href="${encodeURIComponent(file)}"><strong>${title}</strong><span>${detail}</span></a>
      </li>`).join("\n");
  const checksums = files.includes("SHA256SUMS")
    ? '      <p class="meta"><a href="SHA256SUMS">SHA-256 校验和 / Checksums</a></p>'
    : "";
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Mosael ${version} 下载</title>
  <style>
    :root { color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { max-width: 680px; margin: 0 auto; padding: 64px 24px; background: Canvas; color: CanvasText; }
    h1 { margin: 0; font-size: 32px; letter-spacing: -0.03em; }
    h1 span { font-weight: 400; color: GrayText; }
    p { line-height: 1.6; }
    ul { list-style: none; margin: 32px 0 24px; padding: 0; }
    li + li { border-top: 1px solid color-mix(in srgb, GrayText 35%, transparent); }
    li a { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 0; color: inherit; text-decoration: none; }
    li a:hover strong { color: LinkText; }
    li span, .meta { color: GrayText; font-size: 14px; }
    .meta a { color: LinkText; }
    @media (max-width: 480px) { body { padding-top: 40px; } li a { align-items: flex-start; flex-direction: column; gap: 4px; } }
  </style>
</head>
<body>
  <main>
    <h1>Mosael <span>${version}</span></h1>
    <p>选择你的平台开始下载。<br>Choose your platform to download.</p>
    <ul>
${links}
    </ul>
${checksums}
    <p class="meta"><a href="https://github.com/Alndaly/Mosael/releases/latest">其他版本与备用下载 / Other releases</a></p>
  </main>
</body>
</html>
`;
}
