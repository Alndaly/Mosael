# macOS 签名、公证与 Touch ID

正式 macOS 包使用 Developer ID Application 签名，嵌入对应应用的 Developer ID 描述文件，并在 Apple 公证成功后附加公证票据。发布流程会验证签名、钥匙串权限、票据和 Gatekeeper，再启动完整应用检查数据库升级与渲染器。

## 签名身份

- 应用 ID：`dev.mosael.app`。
- 开发者团队：`27W3D2ZUT9`。
- 发布证书：`Developer ID Application: Qingyong Technology (hangzhou) Co., Ltd (27W3D2ZUT9)`。
- 主应用钥匙串组：`27W3D2ZUT9.dev.mosael.app.webauthn`。

这些标识不是密码。证书私钥、公证密码和描述文件不进入 Git；本地描述文件放在被忽略的 `build/mosael.provisionprofile`。

`build/entitlements.mac.plist` 使用明确的团队前缀。直接调用 codesign 不会替换 Xcode 的 `$(AppIdentifierPrefix)`，所以不能将带占位符的文件直接交给 electron-builder。主应用的应用标识、团队标识和钥匙串组必须同时被描述文件授权；仅配置证书会被 macOS 拒绝启动。Helper 使用单独的 `entitlements.mac.inherit.plist`，不领取主应用的钥匙串组。

更换发布证书时，需要确认描述文件包含新证书。更换团队或应用 ID 时，还必须同步 package.json、主应用权限文件及 `electron/webauthn.cjs` 的应用 ID；此前团队下的设备凭据不能自动转移。

## 本机准备

1. 在 Xcode → Settings → Accounts 登录开发者账号，加入上述团队。
2. 在钥匙串中安装带私钥的 Developer ID Application 证书；用 `security find-identity -v -p codesigning` 检查其有效性。
3. 在 Apple Developer 的 Certificates, Identifiers & Profiles 中为应用 ID 创建 **Developer ID** 发布描述文件，授权钥匙串组并选择发布证书，保存到 `build/mosael.provisionprofile`。也可让 Xcode 自动签名归档同一应用 ID，再以 `developer-id` 方式导出，使用导出应用中的 `Contents/embedded.provisionprofile`。开发调试或 Mac App Store 描述文件不能代替它。
4. 在 Apple 账户页面生成 App 专用密码，然后保存公证凭据：

   ```bash
   xcrun notarytool store-credentials "mosael-release" \
     --apple-id "你的 Apple ID 邮箱" --team-id "27W3D2ZUT9"
   ```

   在终端的密码提示中输入 App 专用密码，不要把密码写进命令、脚本或 Git。
5. 打包并验证：

   ```bash
   APPLE_KEYCHAIN_PROFILE=mosael-release pnpm dist:mac
   node scripts/verify-mac-signing.cjs release/mac-arm64/Mosael.app
   node test/bundle.smoke.mjs
   ```

遇到 Xcode 登录 `-1200` 或签名时间戳服务不可用时，先核对系统代理是否能正确访问 Apple 服务。可以测试 Apple 域名直连；不应通过禁用 TLS 验证或系统安全检查解决。

## GitHub Actions

全自动云端发布需要以下五项 Actions secrets，缺少任一项会在创建发布草稿前失败。本机公证交接模式仅需要前三项：

| 名称 | 内容 |
| --- | --- |
| `CSC_LINK` | 仅包含上述发布身份的加密 PKCS#12 文件，Base64 编码 |
| `CSC_KEY_PASSWORD` | 该 PKCS#12 文件的独立强密码 |
| `MACOS_PROVISION_PROFILE` | 对应 Developer ID 描述文件，Base64 编码 |
| `APPLE_ID` | 有权为团队提交公证的 Apple ID |
| `APPLE_APP_SPECIFIC_PASSWORD` | 该 Apple ID 的 App 专用密码 |

签名与公证凭据仅传给 macOS 打包步骤。Windows 构建不会获得这些凭据。私钥通过加密的 Actions secret 进入临时构建环境；不要将整个登录钥匙串导出到 CI。维护者撤销或更新证书、密码时，同步更新 secrets 和描述文件。

## 使用本机钥匙串公证

已在本机保存公证凭据时，不必将 Apple ID 和密码导出到 GitHub。使用手动构建的本机交接模式：

```bash
gh workflow run release.yml --ref main -f notarization=local
```

此模式先运行完整测试，云端使用证书与描述文件生成带安全时间戳的 macOS 应用，并启动应用验证数据库升级和 WebAuthn 配置；Windows 同时生成安装程序。macOS artifact 中的 `*-mac-signed.zip` 保留应用权限与符号链接。它尚未公证，手动构建不会创建或发布 Release，包括选择 tag 作为构建 ref 的情况。

维护者确认工作流成功、构建 commit 与待发布 tag 一致后，下载产物到本机，解压检查签名并用已保存的钥匙串提交：

```bash
node scripts/verify-mac-signing.cjs /path/to/Mosael.app --signature-only
xcrun notarytool submit /path/to/Mosael-1.2.0-mac-signed.zip \
  --keychain-profile mosael-release --wait
xcrun stapler staple /path/to/Mosael.app
node scripts/verify-mac-signing.cjs /path/to/Mosael.app
```

必须收到 Apple 的 Accepted 结果，完成票据、Gatekeeper 与完整应用验证后，才能将应用封装成最终 DMG 并发布。最终分发容器也应提交公证并附加票据。此流程不使用关闭时间戳的本地 QA 包作为分发产物。

## Touch ID 的运行条件

安装版从自身经过验证的代码签名中读取 Team ID 和 entitlements，三处身份一致才调用 Electron 的 `app.configureWebAuthn`。用户电脑不需要设置 `MOSAEL_TEAM_ID`。未签名开发版、签名无效或权限不匹配时不启用，其他浏览器功能正常工作。

实际可用性还取决于设备的 Secure Enclave、Touch ID 和已录入的指纹。打包冒烟要求 macOS 正式包成功配置认证器，同时报告浏览器的实际可用性；无指纹设备的 CI runner 不强制要求实际可用。

凭据保存在本机并按浏览器档案分区隔离，不通过 iCloud 同步，也不能直接使用手机上已有的 passkey。多凭据请求支持账号选择；跨设备扫码能力仍不可用。

参考：[Electron WebAuthn](https://www.electronjs.org/docs/latest/api/app#appconfigurewebauthnoptions-macos)、[electron-builder 26 macOS 配置](https://www.electron.build/v26/docs/mac/)。
