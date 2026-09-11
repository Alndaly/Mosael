# 发布 Mosael（Claude Code / Codex / 人工维护者共用）

用户要求发布新版本时，按本文完成安装包验证和 GitHub Release；仅推送源码、修改版本号或启动构建，不等于发布完成。运行环境需要可访问 GitHub 的 `gh` 登录、本机 Xcode 命令行工具，以及已配置的公证钥匙串。代理或执行权限不足时，明确请求所需权限。

## 1. 确认源码和版本

- 先检查 `git status --short`、当前分支、远端 main 和近期提交；保留其他工具或用户的改动，不重置工作区。
- 阅读 `CHANGELOG.md`、`package.json` 和 [macOS 签名说明](MACOS_SIGNING.md)。如果版本已准备好，沿用它，不重复升级。
- 比较最新 GitHub Release 与待发布版本，检查相同 tag/草稿是否已存在。公开版本不可覆盖或移动 tag。
- 版本号、变更说明和必要文档同步后，提交并推送用户授权发布的源码。记录待构建的完整 commit SHA。
- 版本号要改的地方不止 `package.json`。官网的测试会逐项核对，漏一处就红在 `'1.3.0' !== '1.3.1'`：
  `website/public/media/capture-manifest.json` 顶层的 `documentedVersion`、每篇
  `website/content/docs/**/*.mdx` frontmatter 的 `version`、中英下载页的「已正式发布」、
  `website/README.md` 的「当前文档对应」，以及 `website/src/lib/release-copy.ts` 里这一版的中英亮点。
- 截图批次的 sourceCommit/capturedAt/**批次内的 version** 是拍摄来源，不因发版而伪造更新。
  它和上面那个 `documentedVersion` 是两回事：前者说「这批是什么时候拍的」，后者说「这份文档对应哪个版本」。
  （这两个曾被读成一个，于是整节都没改，CI 才红的。）
- 「哪些画面尚未补录实拍」那句要**按这一版实际改过的界面重写**，不要沿用上一版的措辞 —— 照抄就是谎报。

```bash
git status --short
git log -8 --oneline
gh release list --limit 5
node -p "require('./package.json').version"
gh secret list
```

## 2. 选择当前可用的构建路径

目前实际使用的是**云端签名 + 本机钥匙串公证交接**：GitHub 已配置 `CSC_LINK`、`CSC_KEY_PASSWORD`、`MACOS_PROVISION_PROFILE`；Apple 凭据存于本机钥匙串 profile **`mosael-release`**。先核对实际配置，不假定凭据永远有效。

不需要向用户索要已有密码，不要导出钥匙串密码到聊天、脚本、日志或仓库。可以这样验证现有配置：

```bash
xcrun notarytool history --keychain-profile mosael-release --output-format json
gh workflow run release.yml --ref main -f notarization=local
gh run list --workflow release.yml --limit 5
```

记录刚触发的 run ID，使用 `gh run view RUN_ID --json headSha,status,conclusion,jobs` 验证 headSha 是待发布提交，然后等待：

```bash
gh run watch RUN_ID --interval 45 --exit-status
```

这个流程会运行完整测试、macOS/Windows 构建、签名和打包启动/数据库升级检查。手动构建不自动创建 Release，macOS artifact 是**尚未公证**的 `Mosael-VERSION-mac-signed.zip`。

若以后配置了全部五项 GitHub secrets（另含 `APPLE_ID` 和 `APPLE_APP_SPECIFIC_PASSWORD`），可按 `release.yml` 的 tag 自动发布路径操作。不要在缺少云端 Apple 凭据时先推 tag 再期待自动发布成功。不要为了让门禁通过关闭签名、时间戳或测试。

## 3. 下载、验证与公证

下面以占位符表示本次 run、版本及路径，实际执行时替换；在仓库外建立专用工作目录，避免把大包纳入 Git。

```bash
gh run download RUN_ID --dir /tmp/mosael-release-VERSION/artifacts
```

核对两个 artifact 均来自成功的同一次构建。使用 `ditto -x -k` 解压 macOS ZIP，保留符号链接和权限：

```bash
ditto -x -k /path/to/Mosael-VERSION-mac-signed.zip /path/to/unpacked
node scripts/verify-mac-signing.cjs /path/to/unpacked/Mosael.app --signature-only
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' /path/to/unpacked/Mosael.app/Contents/Info.plist
xcrun notarytool submit /path/to/Mosael-VERSION-mac-signed.zip \
  --keychain-profile mosael-release --wait --output-format json
```

保存 submission ID。连接中断或等待超时时，先用 `notarytool info ID --keychain-profile mosael-release` 查询原提交，避免盲目重复上传。只有 `Accepted` 才继续；`Invalid` 时读取 `notarytool log` 并解决实际问题。

```bash
xcrun stapler staple /path/to/unpacked/Mosael.app
node scripts/verify-mac-signing.cjs /path/to/unpacked/Mosael.app
node test/bundle.smoke.mjs /path/to/unpacked/Mosael.app/Contents/MacOS/Mosael
```

将验证过的应用复制到独立的 DMG staging 目录，加入指向 `/Applications` 的符号链接。可以使用 electron-builder 的既有 DMG 配置，也可以用系统工具生成容器：

```bash
hdiutil create -volname Mosael -srcfolder /path/to/staging -format UDZO /path/to/Mosael-VERSION-arm64.dmg
codesign --sign 'Developer ID Application: Qingyong Technology (hangzhou) Co., Ltd (27W3D2ZUT9)' \
  --timestamp /path/to/Mosael-VERSION-arm64.dmg
xcrun notarytool submit /path/to/Mosael-VERSION-arm64.dmg \
  --keychain-profile mosael-release --wait --output-format json
xcrun stapler staple /path/to/Mosael-VERSION-arm64.dmg
xcrun stapler validate /path/to/Mosael-VERSION-arm64.dmg
spctl --assess --type open --context context:primary-signature --verbose=2 /path/to/Mosael-VERSION-arm64.dmg
```

只读挂载最终 DMG，再次核对内部应用版本、签名与票据。记录两个公证 ID、安装包 SHA-256 和完整启动检查结果。代理问题参见签名说明；保留 TLS 验证，不修改系统安全策略。若 `codesign` 的时间戳失败但普通 HTTP 探测正常，注意它使用系统网络代理，而终端工具可能使用另一组代理环境变量。本机实际成功的处理是保存当前网络服务的代理例外列表，临时将 Apple 域名加入直连例外、仅为签名命令清除 HTTP/HTTPS/ALL_PROXY 环境变量，并在 finally/trap 中还原例外列表。先确认活跃网络服务名称；不要假定所有设备都叫 Wi-Fi，也不要把临时网络变更永久保留。

## 4. 整理发布附件

- 公证完成的 macOS arm64 `.dmg`。
- 同一构建的 Windows x64 `.exe`（云端已验证启动和数据库升级；不要把它描述为 Windows 代码签名包）。
- `mosael-browser-extension.zip`：从同一源码提交构建 `pnpm build:extension` 后，将 `browser-extension/dist` **内部文件**打成 ZIP。
- `plugins/examples/*` 的五个插件 ZIP：包名取各自 `mosael.plugin.json` 的 `id`，manifest 位于 ZIP 根目录。

不要混用不同 commit 的桌面包或插件。开始打包后 main 如有新提交，用原提交的独立 checkout 打包附件，或完整重建新提交；不要让 tag 指向未被测试的代码。

## 5. 创建草稿并正式发布

安装包验证完成后，以**成功构建的 SHA**为目标创建草稿。没有 tag 时 GitHub 会按 `--target` 创建；若已有 tag，先确认其指向一致。

```bash
gh release create vVERSION --target BUILD_SHA --draft --title 'Mosael vVERSION' \
  --notes-file /path/to/release-notes.md /path/to/assets/*
gh release view vVERSION --json isDraft,assets,targetCommitish,url
```

检查八个附件的文件名、大小和 GitHub API 返回的 SHA-256 digest，与本地 `shasum -a 256` 比较。若仓库事件触发了额外自动构建，先分辨本机交接 run 和自动 run；不得绕过失败的必要验证发布其他产物。

所有检查完成后，执行用户已授权的正式发布：

```bash
gh release edit vVERSION --draft=false --prerelease=false --latest
gh release view vVERSION --json isDraft,isPrerelease,publishedAt,assets,url
```

最终报告版本链接、对应 SHA、测试结果、公证情况和安装包是否齐全。将过程证据写入 `docs/validation/`；证据文档后续提交可以在 main 上，但已经发布的 tag 始终保留在原构建提交。

## 可以直接交给 Claude 的指令

> 请先读取 CLAUDE.md、docs/RELEASING.md 和 docs/MACOS_SIGNING.md，核对本地最新代码，使用已配置的 GitHub 签名 secrets 与本机 mosael-release 公证配置发布新版本。沿用已经准备好的版本号；完成完整测试、双平台安装包、macOS 公证和启动验证后再公开 GitHub Release。你可以执行所需 gh 操作；不要只推代码或启动构建就结束，不要在聊天里索要或输出已有密码。
