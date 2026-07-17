// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import tailwindcss from "@tailwindcss/vite";

// Mibu 使用文档(Astro Starlight)。一份静态产物两用:App 内本地托管(离线可看)+ 独立部署做 SEO。
// Starlight 自带 Pagefind 本地搜索(构建期生成索引,纯前端离线可用)。
export default defineConfig({
  site: process.env.DOCS_SITE_URL || "https://mibu.studio",
  base: process.env.DOCS_BASE || "/",
  vite: { plugins: [tailwindcss()] },
  integrations: [
    starlight({
      title: "Mibu 使用文档",
      description: "桌面级视频剪辑 + AI 智能体 + 工作流 + 一键社媒分发 · 使用文档",
      logo: { src: "./src/assets/logo.svg", alt: "Mibu" },
      favicon: "/favicon.svg",
      // 自托管字体(打进 dist,离线可用;严禁 CDN)。
      customCss: [
        "./src/styles/tailwind.css",
        "@fontsource-variable/outfit",
        "@fontsource-variable/noto-sans-sc",
        "@fontsource-variable/jetbrains-mono",
        "./src/styles/custom.css",
      ],
      defaultLocale: "root",
      locales: {
        root: { label: "简体中文", lang: "zh-CN" },
      },
      sidebar: [
        { label: "开始", autogenerate: { directory: "start" } },
        { label: "使用指南", autogenerate: { directory: "guides" } },
      ],
    }),
  ],
});
