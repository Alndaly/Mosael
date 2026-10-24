# ADR 0079 · YouTube 走 Google OAuth,不再指望网页登录

- 状态:Proposed — 2026-10-23
- 相关:ADR 0044(确认卡与措辞)、ADR 0076(发布的内容形状)
- 代码位置:`electron/publish/adapters/youtube.ts`、`backend/app/domain/publish/`、`backend/app/domain/providers/`

## 先修回归(2026-10-23)

维护者说「以前我是可以的」—— 对的。10-22 那批身份改动之前,YouTube 用的是**如实声明的 Electron**
UA,登录能过;`1d56a2ca4`(身份按平台走)把它换成了「干净 Chrome UA」,`eaff42722` 又给 Chrome 身份
加上了 **CDP 对齐**(`Emulation.setUserAgentOverride`,建视图时就要挂 debugger —— 那本身就是
DevTools 特征)。两条叠起来,Google 在输完密码那一刻回 `signin/rejected`。

所以先**回退到能用的那一档**:`CHROME_IDENTITY_EXEMPT += youtube`,YouTube 重新如实声明 Electron
(不洗 UA、不挂 debugger)。下面的 OAuth 是**长期方案**,不是为绕过这次拦截而加的补丁。

## 会话为什么会"没了"(2026-10-23)

维护者:「我之前明明成功登陆过了」。查日志:那几次登录窗口最后都是 `login poll ended (view dismissed)`
—— 窗口被关掉,登录没走完;而更早那次**成功**的会话确实存在过,是**身份档被改掉**之后失效的:
Google 把会话绑在浏览器身份上(UA / client hints),一变就作废那枚 cookie。一天里 YouTube 的身份
来回换过两次(真 Chrome 假象 → 如实 Electron),于是「明明登过」的会话就没了。

所以:改某平台的 identity = **那个平台的所有人重新登录一次**;验证完别再翻烧饼。

## 事实(2026-10-23 真机,Chrome 身份那一档)

用发布账号的浏览器池打开 `accounts.google.com/ServiceLogin?service=youtube`:

- **身份是对的**:`navigator.userAgent` 是干净 Chrome(`Electron/…` 已抹),`navigator.userAgentData.brands`
  是 `Google Chrome 152 / Chromium 152 / Not_A Brand`(CDP `Emulation.setUserAgentOverride` 生效),
  `navigator.webdriver === false`,`window.chrome` 在。也就是说 **UA 与 client hints 自洽**,不是
  「自称 Chrome、信号不像」那种破绽;
- 输完账号密码之后,Google 跳到 `accounts.google.com/v3/signin/rejected`,页面上写
  「**此浏览器或应用可能不安全**」「请尝试使用其他浏览器」。

结论:**这是 Google 的策略,不是我们的指纹问题。** 它不给嵌入式 webview(Electron / CEF 一类)提供
网页端登录;再对齐指纹也只是猜,而且**绕过它等于替用户绕过 Google 的账号安全策略** —— 不做。

## 补记(2026-10-24):登录之外还有一道前提

排查发布能力时实测:这个 Google 账号**还没有 YouTube 频道** —— 访问 `youtube.com/upload` 与
`studio.youtube.com` 都会被送回首页并弹出「创建频道」(`channel_creation_token=…`)。也就是说,
即使登录问题解决了,YouTube 的视频 / 社区帖也发不出去,直到先把这个频道建起来。
这属于账号侧的准备,不是发布的代码问题。

## 决定

### 1. 现在:认出来,说清楚

`checkLogin` 认 `accounts.google.com/…(rejected|denied)` 这条地址,抛 `manual_required` 并给一句人话:
「Google 不允许在应用内浏览器里登录(它的原话是「此浏览器或应用可能不安全」)。YouTube 的网页登录
这条路走不通 —— 需要接 Google 账号授权(OAuth)才能发。」

界面上 `YouTube` 的账号因此显示为「需要处理」而不是「登录失败」——**后者会让人以为是我们坏了**。

### 2. 接下来:YouTube 走 OAuth(YouTube Data API v3)

- 用户在**系统浏览器**里完成 Google 授权(不是我们的内嵌窗口),我们只接回调拿 refresh token;
- 发布改成调 `videos.insert`(视频)/(图文按平台能力另说),不再依赖 Studio 的网页表单;
- 令牌像供应商 OAuth 那样加密落盘(复用 `core/secrets_at_rest` 与 `provider_auth` 的刷新逻辑);
- 需要一枚 Google Cloud OAuth 客户端:要么用户在设置里填自己的 client id/secret(自托管常见),
  要么将来随应用分发一枚(受 Google 的品牌审核约束)。

## 不做的

- **不洗指纹绕过 Google 的登录拦截** —— 那条路即便能通,也是在替用户规避对方的账号安全策略;
- 不导入从系统 Chrome 里抠出来的 Google cookies(易碎、且同样绕策略);
- 不为 YouTube 单独发明一套「网页自动化 + 验证码人工过」的流程(OAuth 之后不再需要)。

## 后果

- YouTube 的发布能力**暂时不可用**,但失败原因明确、可行动(等 OAuth 那一步);
- 其余平台(小红书 / 抖音 / 视频号 / B站 / X / TikTok)不受影响 —— 它们的网页登录没有这层限制;
- 接 OAuth 时,`PublishAdapter` 里 YouTube 那一份会被换成「调用 API」的实现,而不是继续写选择器。
