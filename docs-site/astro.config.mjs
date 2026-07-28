// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import tailwindcss from "@tailwindcss/vite";

// Open Studio 使用文档(Astro Starlight)。静态产物可独立部署做 SEO,也可日后由 App 内托管离线查看。
// Starlight 自带 Pagefind 本地搜索(构建期生成索引,纯前端离线可用)。
export default defineConfig({
  site: process.env.DOCS_SITE_URL || "https://openstudio.team",
  base: process.env.DOCS_BASE || "/",
  vite: { plugins: [tailwindcss()] },
  integrations: [
    starlight({
      title: {
        "zh-CN": "Open Studio 使用文档",
        en: "Open Studio Docs",
      },
      description: "桌面级视频剪辑 + AI 智能体 + 工作流 + 一键社媒分发 · 使用文档",
      logo: { src: "./src/assets/logo.svg", alt: "Open Studio" },
      favicon: "/favicon.svg",
      social: [
        { icon: "github", label: "GitHub", href: "https://github.com/Alndaly/OpenStudio" },
        { icon: "email", label: "邮件联系", href: "mailto:1142704468@qq.com" },
      ],
      // 字体策略:正文字体自托管(打进 dist,离线可用);展示层的霞鹜文楷是唯一例外——
      // 它有上百个中文子集文件,打包会显著增肥 dist,故走 CDN,离线/CDN 不可达时
      // 按 --openstudio-font-display 字体链回退到 Outfit/Noto,不影响可读性。
      head: [
        { tag: "link", attrs: { rel: "preconnect", href: "https://cdn.jsdelivr.net", crossorigin: true } },
        {
          tag: "link",
          attrs: {
            rel: "stylesheet",
            href: "https://cdn.jsdelivr.net/npm/lxgw-wenkai-screen-webfont@1.7.0/lxgwwenkaigbscreen.css",
          },
        },
      ],
      customCss: [
        "./src/styles/tailwind.css",
        "@fontsource-variable/outfit",
        "@fontsource-variable/noto-sans-sc",
        "@fontsource-variable/jetbrains-mono",
        "@fontsource-variable/fraunces",
        "./src/styles/custom.css",
      ],
      defaultLocale: "root",
      locales: {
        root: { label: "简体中文", lang: "zh-CN" },
        en: { label: "English", lang: "en" },
      },
      sidebar: [
        {
          label: "开始",
          translations: { en: "Get started" },
          autogenerate: { directory: "start" },
        },
        {
          label: "使用指南",
          translations: { en: "Guides" },
          autogenerate: { directory: "guides" },
        },
        {
          label: "关于",
          translations: { en: "About" },
          autogenerate: { directory: "about" },
        },
      ],
    }),
  ],
});
