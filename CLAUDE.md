# Mosael repository instructions

## Understand current code

When `.codegraph/` exists, use `codegraph explore` (or its MCP equivalent) before text searches to locate or understand code. Recheck the current branch and local changes at the start of work; preserve updates made by other tools.

## Packaging and releases

When the user asks to build or publish a release, read [docs/RELEASING.md](docs/RELEASING.md) and [docs/MACOS_SIGNING.md](docs/MACOS_SIGNING.md) first. They document the actual GitHub Actions and local macOS notarization handoff, including the existing `mosael-release` Keychain profile. Use existing credentials without printing or exporting secrets. A release is complete only when the tested installers are verified and the authorized GitHub Release is published; pushing code or dispatching a workflow alone is not completion.

## 本地开发服务(用户就用它测)

用户在本机 `http://127.0.0.1:3100`(官网)和 `http://127.0.0.1:8000`(MosaelCloud)上测试。**每次任务或提交做完，跑一次 `scripts/dev-services.sh`** 把两个服务重建到当前 HEAD;只改了 `cloud/` 就 `scripts/dev-services.sh cloud`。不重建，用户看到的是上一个提交的行为，会被当成"改了没生效"(踩过)。密钥(126 SMTP、官方号密码)在 `~/.mosael-dev.env`，不进仓库。
