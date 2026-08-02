import type { Locale } from "./config";

/**
 * 全站文案。
 *
 * 中文散文放在 `.ts` 里而不是 JSX 里，是有原因的：JSX 会把源码里的换行 + 缩进折成一个
 * 空格 —— 英文里正好是词间距，中文里就是凭空多出来的空格，而且只在浏览器里看得见。
 * 文案在这里是普通字符串字面量，想怎么折行都行。组件那侧只剩结构。
 *
 * 英文那份由 `Messages` 约束，少一个 key 就编译不过 —— 双语站最常见的坏结果是英文页悄悄
 * 停在半年前，类型是这里唯一拦得住它的东西。
 */
const zh = {
  meta: {
    title: "Open Studio · 让灵感落进时间线",
    description: "本地优先的 AI 视频工作台。剪辑、生成、编排、分发，素材不出本机。",
  },
  nav: {
    docs: "文档",
    plugins: "插件",
    workflows: "工作流",
    download: "下载",
    github: "GitHub",
    theme: "切换主题",
    language: "切换语言",
    skipToContent: "跳到正文",
    menu: "目录",
  },
  docs: {
    title: "文档",
    sections: { start: "开始", guides: "使用指南", about: "关于" },
    prev: "上一篇",
    next: "下一篇",
    editOnGitHub: "在 GitHub 上编辑此页",
    onThisPage: "本页目录",
    anchor: "链接到本节",
    search: "搜索文档",
    searchPlaceholder: "搜索文档…",
    searchEmpty: "没有匹配的内容",
    searchHint: "输入关键词开始搜索",
    searchClose: "关闭",
  },
  home: {
    eyebrow: "本地优先 · 桌面应用",
    title: "让灵感落进时间线",
    /** 标题拆成两截，后半截上品牌色 —— 整行变紫会廉价，一句里挑三个字刚好。 */
    titleLead: "让灵感落进",
    titleAccent: "时间线",
    lede: "剪辑、AI 生成、工作流编排、一键分发 —— 一个本地工作台完成全部创作。素材留在你自己的机器上。",
    ctaDownload: "下载 App",
    ctaSource: "看看源码",
    platforms: "macOS(Apple Silicon)· Windows 10/11 x64 · 离线可用",
    heroShotAlt: "Open Studio 剪辑页：多轨时间线、双监看器、素材与逐字稿面板",
    heroShotCaption: "剪辑页 —— 多轨时间线、逐字稿驱动剪辑、调色与字幕，导出一步到位。",

    /** 走马灯色带。是一句话拆成的词，不是导航，所以整条对读屏软件隐藏。 */
    marquee: ["多轨时间线", "逐字稿驱动剪辑", "AI 智能体", "可视化工作流", "知识库", "一键分发", "本地优先", "开源"],

    chaptersTitle: "从一段素材到一条发布，中间不用换应用",
    chapters: [
      {
        label: "剪辑",
        title: "时间线是主角",
        body: "多轨道、涟漪编辑、变速、调色曲线与示波器 —— 该有的都在，并且不藏在三层菜单后面。逐字稿和时间线是同一份数据：删掉一句话，画面跟着走。",
        shotAlt: "操作演示：在多轨时间线上裁剪、拖动并预览片段",
      },
      {
        label: "智能体",
        title: "它动手，但先问你",
        body: "对话里的智能体通过工具直接操作工程 —— 找素材、切片、配音、导出。每一次会改动工程的动作都先出一张确认卡，点头才执行。它不替你做决定，只是把「想到」和「做到」之间那段路铺平。",
        shotAlt: "智能体对话面板：工具调用步骤与待确认的改动卡",
      },
      {
        label: "工作流",
        title: "重复的事，画一次就够",
        body: "把检索、生成、转写、拼装、发布串成一张图，手动跑、定时跑、或者由 Webhook 叫醒。画布上能做的事，对话里的智能体也都能做 —— 这一点由测试钉着，不是一句宣传。",
        shotAlt: "可视化工作流画布：检索 → 生成 → 拼装 → 通知 的节点连线",
      },
    ],

    localTitle: "为什么是本地优先",
    localBody: [
      "素材不上传，工程不上传，渲染在本机。模型你自己挑 —— 接自己的 API key，或者干脆用本地跑的 Whisper 和开源权重。哪一步走云、哪一步不走，是你的选择而不是默认值。",
      "全部状态落在 ~/.open-studio 一个目录里，拔掉网线也能剪完一条片子。",
    ],

    moreTitle: "还有",
    more: [
      {
        title: "知识库",
        body: "导入文档与网页，本地全文 + 向量 + 图谱混合检索，喂给智能体与工作流。",
      },
      {
        title: "发布矩阵",
        body: "抖音 · 小红书 · 视频号 · B 站，多账号登录态常驻，由桌面端内嵌浏览器完成真实上传。",
      },
      {
        title: "插件",
        body: "本地脚本或现成的 MCP 服务，接进来就是智能体和工作流的工具，权限与凭据逐项授权。",
      },
    ],

    communityTitle: "找个人说话",
    communityBody: "用着别扭、想要什么功能、或者只是想看看别人怎么剪 —— 群里说比提 issue 快。",
    communityGroup: "影像交流群",
    communityGroupHint: "微信扫码进群",
    communityAuthor: "作者微信",
    communityAuthorHint: "商业授权、深度合作直接找我",

    closingTitle: "开源，免费下载",
    closingBody: "macOS 与 Windows 都有安装包。源码在 GitHub 上，遇到问题可以直接提 issue。",
  },
  plugins: {
    title: "插件",
    lede: "插件把外面的能力接进来 —— 一段本地脚本，或者一个现成的 MCP 服务。装上之后它就是智能体和工作流的工具，和内置能力站在同一排。",
    howTitle: "两种写法",
    how: [
      {
        title: "本地脚本",
        body: "一个入口文件加一份 manifest，工具的入参出参用 JSON Schema 描述。纯计算类的工具连权限都不用要。",
      },
      {
        title: "接现成的 MCP",
        body: "越来越多平台自己就发 MCP server。那种情况下插件里一行代码都没有，只声明「去连这个服务」，工具清单由对方提供。",
      },
    ],
    permissionsTitle: "权限是逐项给的",
    permissionsBody: "manifest 里声明要什么，安装时你逐项点头；凭据只注入到那一个连接，拿不到应用的其它密钥。",
    officialTitle: "官方范例",
    officialBody: "下面这几个就在仓库里，可以直接照着改。",
    kindScript: "本地脚本",
    kindMcp: "MCP 服务",
    noPermissions: "无需权限",
    viewSource: "看源码",
    manifestLink: "manifest 字段说明",
    guideLink: "插件指南",
  },
  workflows: {
    title: "工作流",
    lede: "把检索、生成、转写、拼装、发布串成一张有向无环图，手动跑、定时跑，或者由 Webhook 叫醒。画布上能做的事，对话里的智能体也都能做。",
    shotAlt: "可视化工作流画布：检索 → 生成 → 拼装 → 通知 的节点连线",
    shotCaption: "工作流画布 —— 节点分组、连线、就绪检查都在一张图上。",
    galleryTitle: "社区工作流",
    galleryEmptyTitle: "还没有收录的工作流",
    galleryEmptyBody:
      "条目形状已经定好了 —— 名称、简介、节点数、需要先配好哪些能力，以及一份可以直接导入的图。第一条投稿之后这里就会变成一个画廊。",
    contribute: "投一条上来",
    guideLink: "工作流指南",
    fieldsTitle: "一条工作流要交什么",
    fields: [
      { name: "名称 / 简介", body: "一句话说清它替人省掉了哪段重复劳动。" },
      { name: "节点数", body: "一眼看出复杂度,决定要不要现在打开。" },
      {
        name: "需要的能力",
        body: "跑起来得先在设置里配好哪些供应商 —— 缺哪一样，导入前就知道。",
      },
      {
        name: "可导入的图",
        body: "就是 /api/workflows 那份 JSON，存下来直接导入。",
      },
    ],
  },
  footer: {
    tagline: "本地优先的 AI 视频工作台",
    community: "社区",
    project: "项目",
    download: "下载",
    github: "GitHub",
    contact: "联系",
    issues: "反馈问题",
    rights: "保留所有权利。",
  },
  notFound: {
    title: "这一页不在了",
    body: "链接可能过期了，或者页面在重建官网时挪了位置。",
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
    docs: "Docs",
    plugins: "Plugins",
    workflows: "Workflows",
    download: "Download",
    github: "GitHub",
    theme: "Toggle theme",
    language: "Change language",
    skipToContent: "Skip to content",
    menu: "Contents",
  },
  docs: {
    title: "Docs",
    sections: { start: "Get started", guides: "Guides", about: "About" },
    prev: "Previous",
    next: "Next",
    editOnGitHub: "Edit this page on GitHub",
    onThisPage: "On this page",
    anchor: "Link to this section",
    search: "Search docs",
    searchPlaceholder: "Search the docs…",
    searchEmpty: "Nothing matched",
    searchHint: "Type to search",
    searchClose: "Close",
  },
  home: {
    eyebrow: "Local-first · Desktop app",
    title: "Where ideas land on the timeline",
    titleLead: "Where ideas land on the",
    titleAccent: "timeline",
    lede: "Editing, AI generation, workflow orchestration, one-click publishing — one local workstation for the whole thing. Your footage stays on your own machine.",
    ctaDownload: "Download",
    ctaSource: "Read the source",
    platforms: "macOS (Apple Silicon) · Windows 10/11 x64 · Works offline",
    heroShotAlt: "The Open Studio editor: multi-track timeline, dual monitors, media and transcript panels",
    heroShotCaption:
      "The editor — multi-track timeline, transcript-driven cuts, color and subtitles, export in one step.",

    marquee: [
      "Multi-track timeline",
      "Transcript-driven cuts",
      "AI agent",
      "Visual workflows",
      "Knowledge base",
      "One-click publishing",
      "Local-first",
      "Open source",
    ],

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

    communityTitle: "Talk to someone",
    communityBody:
      "Something feels off, a feature you want, or just curious how other people cut — the group is faster than an issue.",
    communityGroup: "WeChat group",
    communityGroupHint: "Scan to join",
    communityAuthor: "The author",
    communityAuthorHint: "Commercial licensing and partnerships — reach me directly",

    closingTitle: "Open source, free to download",
    closingBody: "Installers for macOS and Windows. The source lives on GitHub — open an issue if something breaks.",
  },
  plugins: {
    title: "Plugins",
    lede: "Plugins bring outside capabilities in — a local script, or an MCP server that already exists. Once installed, a plugin is a tool for the agent and for workflows, standing in the same row as everything built in.",
    howTitle: "Two ways to write one",
    how: [
      {
        title: "A local script",
        body: "One entry file plus a manifest, with tool inputs and outputs described in JSON Schema. Pure-computation tools need no permissions at all.",
      },
      {
        title: "Wrap an existing MCP server",
        body: "More and more platforms ship an MCP server themselves. In that case the plugin contains no code — it just declares which service to connect to, and the tool list comes from the other side.",
      },
    ],
    permissionsTitle: "Permissions are granted one by one",
    permissionsBody:
      "The manifest declares what it wants and you approve each item at install time; credentials are injected into that one connection and cannot reach the app's other secrets.",
    officialTitle: "Official examples",
    officialBody: "These live in the repository — copy one and start from there.",
    kindScript: "Local script",
    kindMcp: "MCP server",
    noPermissions: "No permissions",
    viewSource: "Source",
    manifestLink: "Manifest reference",
    guideLink: "Plugin guide",
  },
  workflows: {
    title: "Workflows",
    lede: "Chain retrieval, generation, transcription, assembly and publishing into one directed acyclic graph — run it by hand, on a schedule, or wake it with a webhook. Anything you can do on the canvas the agent can do too.",
    shotAlt: "The visual workflow canvas: retrieve → generate → assemble → notify, wired as nodes",
    shotCaption: "The workflow canvas — node groups, edges and readiness checks all on one graph.",
    galleryTitle: "Community workflows",
    galleryEmptyTitle: "No workflows collected yet",
    galleryEmptyBody:
      "The entry shape is settled — name, summary, node count, which capabilities must be configured first, and a graph you can import as-is. This turns into a gallery with the first submission.",
    contribute: "Submit one",
    guideLink: "Workflow guide",
    fieldsTitle: "What a workflow entry carries",
    fields: [
      {
        name: "Name / summary",
        body: "One sentence on which piece of repetitive work it removes.",
      },
      {
        name: "Node count",
        body: "Complexity at a glance — enough to decide whether to open it now.",
      },
      {
        name: "Required capabilities",
        body: "Which providers must be configured before it runs, so a missing one shows up before the import, not after.",
      },
      {
        name: "Importable graph",
        body: "The same JSON /api/workflows speaks; save it and import directly.",
      },
    ],
  },
  footer: {
    tagline: "A local-first AI video workstation",
    community: "Community",
    project: "Project",
    download: "Download",
    github: "GitHub",
    contact: "Contact",
    issues: "Report an issue",
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
