import type { Locale } from "./config";

/**
 * 全站文案。
 *
 * 中文散文放在 `.ts` 里而不是 JSX 里,是有原因的:JSX 会把源码里的换行 + 缩进折成一个
 * 空格 —— 英文里正好是词间距,中文里就是凭空多出来的空格,而且只在浏览器里看得见。
 * 文案在这里是普通字符串字面量,想怎么折行都行。组件那侧只剩结构。
 *
 * 英文那份由 `Messages` 约束,少一个 key 就编译不过 —— 双语站最常见的坏结果是英文页悄悄
 * 停在半年前,类型是这里唯一拦得住它的东西。
 */
const zh = {
  meta: {
    title: "Open Studio · 让灵感落进时间线",
    description: "本地优先的 AI 视频工作台。剪辑、生成、编排、分发,素材不出本机。",
  },
  nav: {
    download: "下载",
    github: "GitHub",
    theme: "切换主题",
    language: "切换语言",
    skipToContent: "跳到正文",
  },
  home: {
    eyebrow: "本地优先 · 桌面应用",
    title: "让灵感落进时间线",
    lede: "剪辑、AI 生成、工作流编排、一键分发 —— 一个本地工作台完成全部创作。素材留在你自己的机器上。",
    ctaDownload: "下载 App",
    ctaSource: "看看源码",
    platforms: "macOS(Apple Silicon)· Windows 10/11 x64 · 离线可用",
    heroShotAlt: "Open Studio 剪辑页:多轨时间线、双监看器、素材与逐字稿面板",
    heroShotCaption: "剪辑页 —— 多轨时间线、逐字稿驱动剪辑、调色与字幕,导出一步到位。",

    chaptersTitle: "从一段素材到一条发布,中间不用换应用",
    chapters: [
      {
        label: "剪辑",
        title: "时间线是主角",
        body: "多轨道、涟漪编辑、变速、调色曲线与示波器 —— 该有的都在,并且不藏在三层菜单后面。逐字稿和时间线是同一份数据:删掉一句话,画面跟着走。",
        shotAlt: "操作演示:在多轨时间线上裁剪、拖动并预览片段",
      },
      {
        label: "智能体",
        title: "它动手,但先问你",
        body: "对话里的智能体通过工具直接操作工程 —— 找素材、切片、配音、导出。每一次会改动工程的动作都先出一张确认卡,点头才执行。它不替你做决定,只是把「想到」和「做到」之间那段路铺平。",
        shotAlt: "智能体对话面板:工具调用步骤与待确认的改动卡",
      },
      {
        label: "工作流",
        title: "重复的事,画一次就够",
        body: "把检索、生成、转写、拼装、发布串成一张图,手动跑、定时跑、或者由 Webhook 叫醒。画布上能做的事,对话里的智能体也都能做 —— 这一点由测试钉着,不是一句宣传。",
        shotAlt: "可视化工作流画布:检索 → 生成 → 拼装 → 通知 的节点连线",
      },
    ],

    localTitle: "为什么是本地优先",
    localBody: [
      "素材不上传,工程不上传,渲染在本机。模型你自己挑 —— 接自己的 API key,或者干脆用本地跑的 Whisper 和开源权重。哪一步走云、哪一步不走,是你的选择而不是默认值。",
      "全部状态落在 ~/.open-studio 一个目录里,拔掉网线也能剪完一条片子。",
    ],

    moreTitle: "还有",
    more: [
      { title: "知识库", body: "导入文档与网页,本地全文 + 向量 + 图谱混合检索,喂给智能体与工作流。" },
      { title: "发布矩阵", body: "抖音 · 小红书 · 视频号 · B 站,多账号登录态常驻,由桌面端内嵌浏览器完成真实上传。" },
      { title: "插件", body: "本地脚本或现成的 MCP 服务,接进来就是智能体和工作流的工具,权限与凭据逐项授权。" },
    ],

    closingTitle: "开源,免费下载",
    closingBody: "macOS 与 Windows 都有安装包。源码在 GitHub 上,遇到问题可以直接提 issue。",
  },
  footer: {
    tagline: "本地优先的 AI 视频工作台",
    download: "下载",
    github: "GitHub",
    contact: "联系",
    rights: "保留所有权利。",
  },
  notFound: {
    title: "这一页不在了",
    body: "链接可能过期了,或者页面在重建官网时挪了位置。",
    back: "回到首页",
  },
};

export type Messages = typeof zh;

/** 结构必须和 zh 完全一致 —— 类型在这里替我们盯着英文版有没有掉队。 */
const en: Messages = {
  meta: {
    title: "Open Studio · Where ideas land on the timeline",
    description:
      "A local-first AI video workstation. Edit, generate, orchestrate and publish — your footage never leaves your machine.",
  },
  nav: {
    download: "Download",
    github: "GitHub",
    theme: "Toggle theme",
    language: "Change language",
    skipToContent: "Skip to content",
  },
  home: {
    eyebrow: "Local-first · Desktop app",
    title: "Where ideas land on the timeline",
    lede: "Editing, AI generation, workflow orchestration, one-click publishing — one local workstation for the whole thing. Your footage stays on your own machine.",
    ctaDownload: "Download",
    ctaSource: "Read the source",
    platforms: "macOS (Apple Silicon) · Windows 10/11 x64 · Works offline",
    heroShotAlt: "The Open Studio editor: multi-track timeline, dual monitors, media and transcript panels",
    heroShotCaption:
      "The editor — multi-track timeline, transcript-driven cuts, color and subtitles, export in one step.",

    chaptersTitle: "From a raw clip to a published cut, without switching apps",
    chapters: [
      {
        label: "Editing",
        title: "The timeline leads",
        body: "Multiple tracks, ripple edits, speed ramps, color curves and scopes — all there, and none of it buried three menus deep. The transcript and the timeline are the same data: delete a sentence and the picture follows.",
        shotAlt: "Walkthrough: trimming, dragging and previewing clips on a multi-track timeline",
      },
      {
        label: "Agent",
        title: "It acts, but it asks first",
        body: "The agent in the chat panel drives your project through tools — finding footage, cutting, voicing, exporting. Anything that would change the project surfaces a confirmation card first, and runs only once you agree. It doesn't decide for you; it shortens the walk between having an idea and having it done.",
        shotAlt: "The agent chat panel: tool-call steps and a pending change awaiting confirmation",
      },
      {
        label: "Workflows",
        title: "Draw the repetitive part once",
        body: "Chain retrieval, generation, transcription, assembly and publishing into one graph — run it by hand, on a schedule, or wake it with a webhook. Anything you can do on the canvas the agent can do too; that one is pinned down by tests, not by a claim.",
        shotAlt: "The visual workflow canvas: retrieve → generate → assemble → notify, wired as nodes",
      },
    ],

    localTitle: "Why local-first",
    localBody: [
      "Footage isn't uploaded. Projects aren't uploaded. Rendering happens on your machine. You pick the models — bring your own API key, or run Whisper and open weights locally. Which step goes to the cloud is a choice you make, not a default you inherit.",
      "Every bit of state lives in a single ~/.open-studio directory, so you can finish a cut with the network unplugged.",
    ],

    moreTitle: "Also inside",
    more: [
      {
        title: "Knowledge base",
        body: "Import documents and web pages; local full-text, vector and graph retrieval feeds the agent and your workflows.",
      },
      {
        title: "Publishing matrix",
        body: "Douyin · RedNote · WeChat Channels · Bilibili, with persistent multi-account logins and real uploads driven by an embedded browser.",
      },
      {
        title: "Plugins",
        body: "Local scripts or existing MCP servers become tools for the agent and workflows, with permissions and credentials granted one by one.",
      },
    ],

    closingTitle: "Open source, free to download",
    closingBody: "Installers for macOS and Windows. The source lives on GitHub — open an issue if something breaks.",
  },
  footer: {
    tagline: "A local-first AI video workstation",
    download: "Download",
    github: "GitHub",
    contact: "Contact",
    rights: "All rights reserved.",
  },
  notFound: {
    title: "This page is gone",
    body: "The link may have expired, or the page moved while the site was being rebuilt.",
    back: "Back to home",
  },
};

const MESSAGES: Record<Locale, Messages> = { zh, en };

export function getMessages(locale: Locale): Messages {
  return MESSAGES[locale];
}
