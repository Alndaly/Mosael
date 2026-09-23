/** 站外地址集中一处 —— 仓库改名、换域名时不用在十个组件里搜 URL。 */
export const SITE = {
  url: "https://mosael.com",
  repo: "https://github.com/Alndaly/Mosael",
  releases: "https://github.com/Alndaly/Mosael/releases/latest",
  /**
   * 国内下载:百度网盘上一个**文件夹**的永久分享(里面按版本号一个子文件夹,和本地 dist/<版本>/ 同构)。
   * 分享的是文件夹而不是每个安装包,所以发新版只要往里传,这条链接不用换(见 docs/RELEASING.md)。
   * url 留空 = 国内渠道还没开:各处下载入口一律走 GitHub,不显示国内选项(见 lib/download-channel)。
   */
  baiduPan: { url: "https://pan.baidu.com/s/5n5TXJoBkkF61BOyzFqgnjg", code: "" },
  authorX: "https://x.com/KindaHuaX",
  email: "mailto:1142704468@qq.com",
} as const;
