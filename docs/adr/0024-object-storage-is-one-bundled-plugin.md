# ADR 0024: Object storage is one bundled plugin; the provider is a connection setting

## Status

Accepted — 2026-09-26. Builds on ADR 0020 (plugins can serve the host: `provides`) and the `public_url`
capability described in [PLUGIN_MANIFEST.md](../PLUGIN_MANIFEST.md).

## Context

The host needs *some* object store for one of its own features: a generation input that only accepts links
(Seedance's reference video) gets a local asset uploaded first (`domain/generation/public_links.py`), and
**Settings → Asset links** picks which connection does it. That capability was served by four market plugins —
`aliyun-oss`, `aws-s3`, `tencent-cos`, `volcengine-tos` — whose `tools/storage.py` (all four) and `tools/sigv4.py`
(three of them) were byte-identical copies, pinned by a ratchet so they would not drift. `main.py` differed by
~20 lines: env-var names, the default endpoint, the dialect. Every fix had to be copied four times, and a
provider difference that the shared core did not model simply broke: Volcengine TOS's native API speaks JSON,
so its `tos_list` crashed on an XML `ParseError`.

The one legitimate difference between the four is a small table: signing dialect, default endpoint, presign
ceiling, addressing style, body format.

## Decision

1. **One plugin, `dev.mosael.object-storage` («对象存储»), five options.** The provider is an enum in the
   connection's config (`STORAGE_PROVIDER`: Alibaba Cloud OSS / Tencent Cloud COS / Volcengine TOS / Amazon
   S3 / S3-compatible), the same shape as TikHub's platform. The differences live in `tools/providers.py`;
   `tools/storage.py` never branches on which provider it is (a ratchet checks that). Signing stays hand-written
   and is checked against each vendor's official SDK, including the four multipart requests.
2. **It ships with the app** (`plugins/bundled/`), like ComfyUI. The host's own settings page and generation
   path depend on it, so "go to the market first" is the wrong first step; and the migration below can only be
   robust if the new package is on disk without a network round-trip. It cannot be uninstalled; a user with no
   connection simply has none.
3. **The old four are migrated in place** (`merge-object-storage-plugins`, after `install-bundled-plugins`).
   Connection ids do not change, so the asset-link default (`plugin_capability_defaults`), the link cache
   (`plugin_public_links`) and every `instance_id` stored in workflows and boards stay valid. Config keys are
   rewritten, credential rows are renamed without decrypting, `network:oss|s3|cos|tos` grants become
   `network:object-storage`, `oss_upload` → `storage_upload` (toggles, call logs, session auto-allow names,
   confirmation cards, workflow nodes with a new revision, board tool cells), the old package rows and their
   folders are removed. An old S3 connection with a non-AWS endpoint becomes «S3-compatible» (path-style).
4. The market lists one bundled entry instead of four downloadable ones; the website redirects the old plugin
   pages to the new one.

## Consequences

- Adding a provider is a row in `providers.py` plus signing vectors, not a new package.
- Everyone gets the plugin in their plugin list, with zero connections until they create one.
- A third-party plugin can still declare `provides: ["public_url"]`; the host does not special-case ours.
