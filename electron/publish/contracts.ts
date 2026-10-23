/**
 * 各平台的页面契约(见 contract.ts 的说明)。**这是平台事实的唯一手写处**:
 * 页面词表仍在 selectors 里(CSS/文案),形状怎么落、怎么算成功、哪些浮层要关,在这里。
 */
import { resolvePlatform, type SupportedPlatform } from "./platforms";
import type { PlatformContract } from "./contract";
import { SELECTORS } from "./selectors";

const xhs = SELECTORS.xiaohongshu;
const douyin = SELECTORS.douyin;

const XIAOHONGSHU: PlatformContract = {
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
    //: 「写长文」是另一套页面(要再点一次「新的创作」,而且编辑器没有文件上传),还没接。
  },
  fileInput: { video: xhs.fileInput, "image-text": xhs.fileInput },
  submitText: xhs.submitText,
  done: { urls: xhs.publishDoneUrls, texts: xhs.publishDoneTexts },
  overlays: xhs.overlays,
};

const DOUYIN: PlatformContract = {
  entry: {
    video: { url: resolvePlatform("douyin").publishUrl, acceptExtensions: [".mp4", ".mov"] },
    "image-text": {
      steps: [douyin.imageTextTabText],
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
    entry: { video: { url: resolvePlatform("weixin-channels").publishUrl } },
    fileInput: { video: SELECTORS.weixinChannels.fileInput },
    submitText: SELECTORS.weixinChannels.submitText,
    done: { urls: [], texts: SELECTORS.weixinChannels.publishDoneTexts },
    overlays: [],
  },
  bilibili: {
    entry: { video: { url: resolvePlatform("bilibili").publishUrl } },
    fileInput: { video: SELECTORS.bilibili.fileInput },
    submitText: SELECTORS.bilibili.submitTexts[0],
    //: B 站发完**不换地址**,原地换成成功页:靠"成功文案 + 编辑表单消失"判定(见 verify.formGone)。
    done: {
      texts: SELECTORS.bilibili.publishDoneTexts,
      formGone: SELECTORS.bilibili.submitButton,
      //: 明确失败原文:出现即失败(不用等到超时)。
      failTexts: SELECTORS.bilibili.publishFailTexts,
    },
    overlays: [],
  },
  tiktok: {
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
    entry: {
      video: { url: resolvePlatform("x").publishUrl },
      //: 图文和视频是**同一个撰写页、同一个文件框**(X 的文件框图片与视频一起收)。
      "image-text": { url: resolvePlatform("x").publishUrl, acceptExtensions: [".jpg", ".jpeg", ".png", ".webp"] },
    },
    fileInput: { video: SELECTORS.x.fileInput, "image-text": SELECTORS.x.fileInput },
    submitText: SELECTORS.x.postTexts[0],
    //: X 发完把人送回首页:地址 + 撰写组件消失 —— 两道都要(TikTok 那课的同一道闸)。
    done: { urls: [/x\.com\/home/], texts: SELECTORS.x.publishDoneTexts, formGone: SELECTORS.x.textEditor },
    overlays: [],
  },
  mock: {
    entry: { video: { url: "about:blank" } },
    fileInput: { video: "input[type='file']" },
    submitText: SELECTORS.x.postTexts[0],
    //: 测试替身:它的页面是我们自己画的,提交后画一行「发布成功」。
    done: { texts: [SELECTORS.x.publishDoneTexts[0]] },
    overlays: [],
  },
  youtube: {
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
