/**
 * 各平台的页面契约(见 platformContract.ts 的说明)。**这是平台事实的唯一手写处**:
 * 页面词表仍在 selectors 里(CSS/文案),形状怎么落、怎么算成功、哪些浮层要关、每种形状填哪些
 * 字段,在这里。适配器的填表动作只经 `fieldsFor` 取字段。
 */
import { resolvePlatform, type SupportedPlatform } from "./platforms";
import type { PlatformContract, PlatformFields } from "./platformContract";
import type { ContentKind } from "./publishTypes";
import { SELECTORS } from "./selectors";

const xhs = SELECTORS.xiaohongshu;
const douyin = SELECTORS.douyin;

const XIAOHONGSHU: PlatformContract = {
  fields: {
    video: { title: xhs.titleInput, body: xhs.contentEditor, tags: xhs.contentEditor, description: xhs.contentEditor },
    "image-text": { title: xhs.titleInput, body: xhs.contentEditor, tags: xhs.contentEditor, description: xhs.contentEditor },
    article: { title: xhs.articleTitle, body: xhs.articleEditor, tags: xhs.articleEditor, description: xhs.articleEditor },
  },
  entry: {
    video: {
      url: `${resolvePlatform("xiaohongshu").publishUrl}?from=homepage&target=video`,
      steps: [xhs.videoTabText],
      activeTab: xhs.videoTabText,
      acceptExtensions: [".mp4", ".mov"],
      hint: xhs.dropHintByKind.video,
    },
    "image-text": {
      url: `${resolvePlatform("xiaohongshu").publishUrl}?from=homepage&target=image`,
      steps: [xhs.imageTextTabText],
      activeTab: xhs.imageTextTabText,
      acceptExtensions: [".jpg", ".jpeg", ".png", ".webp"],
      hint: xhs.dropHintByKind["image-text"],
    },
    //: 「写长文」是另一套页面:直连 `?target=article` 到列表页,点「新的创作」才进编辑器;
    //: 没有文件上传(封面由平台按正文生成),排版 → 下一步 之后才进普通发布页。
    article: {
      url: `${resolvePlatform("xiaohongshu").publishUrl}?from=homepage&target=article`,
      steps: [xhs.articleNewText],
      acceptExtensions: [],
    },
  },
  fileInput: { video: xhs.fileInput, "image-text": xhs.fileInput },
  submitText: xhs.submitText,
  done: { urls: xhs.publishDoneUrls, texts: xhs.publishDoneTexts },
  overlays: xhs.overlays,
};

const DOUYIN: PlatformContract = {
  fields: {
    video: { title: douyin.titleInput, body: douyin.descEditor, tags: douyin.descEditor, description: douyin.descEditor },
    "image-text": {
      title: douyin.imageTitleInput,
      body: douyin.imageDescEditor,
      tags: douyin.imageDescEditor,
      description: douyin.imageDescEditor,
    },
    article: {
      title: douyin.articleTitleInput,
      body: douyin.articleEditor,
      tags: douyin.articleEditor,
      description: douyin.articleSummaryInput,
    },
  },
  entry: {
    video: { url: resolvePlatform("douyin").publishUrl, acceptExtensions: [".mp4", ".mov"] },
    "image-text": {
      steps: [douyin.imageTextTabText],
      acceptExtensions: [".png", ".jpg", ".jpeg", ".webp"],
    },
    //: 文章是**另一个页面**(标题 / 摘要 / 正文 / 封面上传),不是投稿页上的 tab。
    //: 封面必填,且上传区是"点了才创建 file input" —— 由适配器 `uploadCover` 走文件选择框拦截。
    article: {
      //: 投稿页是 `…/creator-micro/content/upload`,文章页是 `…/creator-micro/content/post/article`。
      url: "https://creator.douyin.com/creator-micro/content/post/article",
      acceptExtensions: [".png", ".jpg", ".jpeg", ".webp"],
    },
  },
  fileInput: {
    //: 两个 input 同时在页面上,**按 accept 区分**:视频那个是 `video/*`,图文那个是图片类型。
    video: "input[type='file'][accept*='video']",
    "image-text": "input[type='file'][accept*='image']",
  },
  submitText: douyin.submitText,
  //: 抖音的落地页判据是**函数**(按地址前缀认,不是一条正则);原语支持函数形式。
  done: { urls: [douyin.isManageUrl], texts: douyin.publishDoneTexts },
  //: 注意:这里是 `RegExp`;函数式的落地页判据由适配器自己 `waitForUrl` 使用(见 adapters/douyin)。
  overlays: douyin.overlays,
};

export const PUBLISH_CONTRACTS: Record<SupportedPlatform, PlatformContract> = {
  xiaohongshu: XIAOHONGSHU,
  douyin: DOUYIN,
  "weixin-channels": {
    fields: {
      video: {
        title: SELECTORS.weixinChannels.descEditor,
        body: SELECTORS.weixinChannels.descEditor,
        tags: SELECTORS.weixinChannels.descEditor,
        description: SELECTORS.weixinChannels.descEditor,
        shortTitle: SELECTORS.weixinChannels.shortTitleInput,
      },
      "image-text": {
        title: SELECTORS.weixinChannels.imageTitleInput,
        body: SELECTORS.weixinChannels.imageDescEditor,
        tags: SELECTORS.weixinChannels.imageDescEditor,
        description: SELECTORS.weixinChannels.imageDescEditor,
      },
    },
    entry: {
      video: { url: resolvePlatform("weixin-channels").publishUrl },
      //: 图文是另一页「发表动态」:表单整个在 `empty.html` 那个 iframe 里(适配器用 inFrame 进去)。
      "image-text": {
        url: SELECTORS.weixinChannels.imageTextUrl,
        acceptExtensions: [".jpg", ".jpeg", ".png", ".webp"],
      },
    },
    fileInput: {
      video: SELECTORS.weixinChannels.fileInput,
      "image-text": SELECTORS.weixinChannels.imageFileInput,
    },
    submitText: SELECTORS.weixinChannels.submitText,
    done: { urls: [], texts: SELECTORS.weixinChannels.publishDoneTexts },
    overlays: [],
  },
  bilibili: {
    fields: {
      video: {
        title: SELECTORS.bilibili.titleInput,
        body: SELECTORS.bilibili.descEditor,
        tags: SELECTORS.bilibili.tagInput,
        description: SELECTORS.bilibili.descEditor,
      },
      article: {
        title: SELECTORS.bilibili.articleTitle,
        body: SELECTORS.bilibili.articleEditor,
        tags: SELECTORS.bilibili.articleEditor,
        description: SELECTORS.bilibili.articleEditor,
      },
    },
    entry: {
      video: { url: resolvePlatform("bilibili").publishUrl },
      //: 专栏:一套独立的编辑器页面(编辑器在 `read-editor` iframe 里,适配器用 inFrame 进去)。
      article: { url: SELECTORS.bilibili.articleUrl },
    },
    //: 文章**没有素材**:封面可以留空(平台自己截正文开头)。
    fileInput: { video: SELECTORS.bilibili.fileInput },
    submitText: SELECTORS.bilibili.submitTexts[0],
    //: B 站发完**不换地址**,原地换成成功页:靠"成功文案 + 编辑表单消失"判定(见 verify.formGone)。
    done: {
      texts: [...SELECTORS.bilibili.publishDoneTexts, ...SELECTORS.bilibili.articleDoneTexts],
      formGone: SELECTORS.bilibili.submitButton,
      //: 明确失败原文:出现即失败(不用等到超时)。
      failTexts: SELECTORS.bilibili.publishFailTexts,
    },
    overlays: [],
  },
  tiktok: {
    fields: {
      video: {
        title: SELECTORS.tiktok.captionEditor,
        body: SELECTORS.tiktok.captionEditor,
        tags: SELECTORS.tiktok.captionEditor,
        description: SELECTORS.tiktok.captionEditor,
      },
      "image-text": {
        title: SELECTORS.tiktok.captionEditor,
        body: SELECTORS.tiktok.captionEditor,
        tags: SELECTORS.tiktok.captionEditor,
        description: SELECTORS.tiktok.captionEditor,
      },
    },
    entry: {
      video: { url: resolvePlatform("tiktok").publishUrl },
      //: 照片档是同一个投稿页的另一个 tab(`?tab=photo`),直连过去最稳。
      "image-text": {
        url: `${resolvePlatform("tiktok").publishUrl}?tab=photo`,
        steps: [SELECTORS.tiktok.photoTabText],
        acceptExtensions: [".jpg", ".jpeg", ".png", ".webp"],
      },
    },
    fileInput: {
      video: SELECTORS.tiktok.fileInput,
      "image-text": "input[type='file'][accept*='image']",
    },
    submitText: SELECTORS.tiktok.postTexts[0],
    //: TikTok 同理:发布按钮不在了才算数(页面导航里本来就有 "Manage your posts" 这种词)。
    done: { urls: [], texts: SELECTORS.tiktok.publishDoneTexts, formGone: SELECTORS.tiktok.postButton },
    overlays: [],
  },
  x: {
    fields: {
      video: {
        title: SELECTORS.x.textEditor,
        body: SELECTORS.x.textEditor,
        tags: SELECTORS.x.textEditor,
        description: SELECTORS.x.textEditor,
      },
      "image-text": {
        title: SELECTORS.x.textEditor,
        body: SELECTORS.x.textEditor,
        tags: SELECTORS.x.textEditor,
        description: SELECTORS.x.textEditor,
      },
      article: {
        title: SELECTORS.x.articleTitle,
        body: SELECTORS.x.articleEditor,
        tags: SELECTORS.x.articleEditor,
        description: SELECTORS.x.articleEditor,
      },
    },
    entry: {
      video: { url: resolvePlatform("x").publishUrl },
      //: 图文和视频是**同一个撰写页、同一个文件框**(X 的文件框图片与视频一起收)。
      "image-text": { url: resolvePlatform("x").publishUrl, acceptExtensions: [".jpg", ".jpeg", ".png", ".webp"] },
      //: 长文(Articles):入口是文章列表页,点「Write」才新建草稿 —— 没有"直连新文章"的地址。
      article: { url: SELECTORS.x.articleListUrl, steps: [SELECTORS.x.articleWriteText] },
    },
    fileInput: { video: SELECTORS.x.fileInput, "image-text": SELECTORS.x.fileInput },
    submitText: SELECTORS.x.postTexts[0],
    //: X 发完把人送回首页:地址 + 撰写组件消失 —— 两道都要(TikTok 那课的同一道闸)。
    //: 长文与帖子不是同一个终态:长文发完停在文章页 / 列表页,编辑页(`…/articles/edit/…`)消失。
    done: {
      urls: [/x\.com\/home/, /\/articles(\?|$)/],
      texts: [...SELECTORS.x.publishDoneTexts, ...SELECTORS.x.articleDoneTexts],
      formGone: SELECTORS.x.textEditor,
    },
    overlays: [],
  },
  mock: {
    fields: { video: { title: "#status", body: "#status", tags: "#status" } },
    entry: { video: { url: "about:blank" } },
    fileInput: { video: "input[type='file']" },
    submitText: SELECTORS.x.postTexts[0],
    //: 测试替身:它的页面是我们自己画的,提交后画一行「发布成功」。
    done: { texts: [SELECTORS.x.publishDoneTexts[0]] },
    overlays: [],
  },
  youtube: {
    fields: {
      video: {
        title: SELECTORS.youtube.titleBox,
        body: SELECTORS.youtube.descBox,
        tags: SELECTORS.youtube.descBox,
        description: SELECTORS.youtube.descBox,
      },
    },
    entry: { video: { url: resolvePlatform("youtube").publishUrl } },
    fileInput: { video: SELECTORS.youtube.fileInput },
    submitText: SELECTORS.youtube.doneButton,
    done: { urls: [], texts: SELECTORS.youtube.publishDoneTexts },
    overlays: [],
  },
};

/** 这个平台的契约。 */
export function contractFor(platform: string): PlatformContract {
  return PUBLISH_CONTRACTS[resolvePlatform(platform).id];
}

/** 某个内容形状的字段 selector。契约缺这一项属于装配错误，必须立即失败而不是猜选择器。 */
export function fieldsFor(contract: PlatformContract, kind: ContentKind): PlatformFields {
  const fields = contract.fields[kind];
  if (!fields) throw new Error(`publish contract fields missing for ${kind}`);
  return fields;
}
