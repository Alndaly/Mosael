# Mosael Chrome extension

**English** | [简体中文](README.zh-CN.md)

This extension brings Mosael's video companion into Chrome's native Side Panel. It does not
inject a floating window into the page, and it follows the active video tab.

## Features

- Accept video URLs recognized by the installed yt-dlp build; YouTube and Bilibili prefer native captions, while Mosael can download and transcribe other sites.
- Mosael transcripts retain word timestamps, so each word seeks precisely; site captions and legacy data fall back to cue-level seeking.
- Keep source and secondary text together as bilingual subtitles, with search across both lines.
- Prefer a site's second caption or YouTube translation track, then fall back to Mosael translation.
- Submit the current video URL to the Mosael media library.
- Extract only the current video frame, excluding HTML playback controls, and import it as a PNG asset.
- Choose a destination workspace, optional project, and optional Mosael Browser Pool identity.
- Follow Chrome's UI language automatically, or pin the panel to Simplified Chinese or English.

## Install

### From a Release

Download and unzip `mosael-browser-extension.zip` from a GitHub Release, then:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select the extracted directory.
4. Pin the extension to the toolbar.

### From source

```bash
pnpm install
pnpm build:extension
```

Load `browser-extension/dist/` from `chrome://extensions`.

## Use

1. Start Mosael and make sure its local backend is running at `http://127.0.0.1:8800`.
2. Open a video URL recognized by yt-dlp and click the extension icon to open the Side Panel.
3. Reading site captions and a site-provided secondary track does not require a Mosael connection.
4. The first time you auto-transcribe, use AI translation, import, or capture, open settings in the panel, sign in with your
   Mosael account, and choose a destination workspace. For member-only, private, region-restricted, or bot-protected
   media, optionally choose an identity already signed in and configured with a proxy in Mosael's Browser Pool.
5. The interface follows Chrome by default. Use the same settings view to pin Simplified Chinese or English.

The password is used only to call `/api/auth/login` and is never written to `chrome.storage`. The
extension stores the returned session, backend address, and asset destination. Disconnect at any
time to remove the stored session.

## Permissions

| Permission | Why it is needed |
| --- | --- |
| `sidePanel` | Open Chrome's native side panel |
| `tabs` | Follow the active tab and send seek commands to the current video |
| `activeTab` | Capture the currently visible video frame |
| `<all_urls>` | Discover HTML5 players on any HTTP(S) video page and perform clean video-region fallback capture when Canvas is cross-origin restricted |
| `storage` | Store the Mosael session and destination workspace |
| `127.0.0.1` / `localhost` host access | Call the local Mosael API |

The extension does not request the `cookies` permission and never reads or exports Chrome login state.
The panel can select an identity already managed by Mosael and sends only its ID to the backend;
the download job uses the existing Browser Pool to reuse that identity's cookies and proxy.

Bilibili caption URLs are short-lived. The extension refreshes the caption listing for the current
`bvid` / `cid` on every entry instead of reusing a possibly stale page URL. Background caption
requests are restricted to the required official API and subtitle paths.

The YouTube and Bilibili background network proxy remains restricted to official caption APIs and
caption-file paths; `<all_urls>` does not turn it into an arbitrary fetch proxy. Other pages only use
DOM player discovery, while backend support is determined from the installed yt-dlp extractor registry.
The generic adapter selects the real visible, playable video instead of hidden ad or placeholder
`<video>` elements.

## Automatic transcription when captions are missing

When the site returns no captions, the panel offers **Generate transcript with Mosael**. It
uses the existing backend pipeline: download the URL into the media library, start speech
recognition, poll the background job, and load the timed result back into the panel. Generated
transcripts retain playback following, seeking, search, and bilingual display. The panel preserves
word-level timestamps while grouping tokens into readable rows using sentence boundaries, pauses,
duration, and text length; every displayed word remains an exact seek target. Legacy transcripts
without word timing are split by sentence and use cue-level seeking instead of being shown as
paragraph-sized subtitle blocks. Long videos take as long as the network and selected
transcription engine require.

When the same video is opened again, the extension resolves a completed transcript in the current
workspace by stable video identity before offering another generation. New URL imports retain that
identity in asset metadata; pre-upgrade transcripts are recovered through their historical URL-import
job, so no manual migration is required. Source URLs are normalized by removing common tracking
parameters and fragments so one video is not split into separate identities.

## Known limitations

- Chrome 116+ with the Manifest V3 Side Panel is supported. Edge may be compatible but is not yet a
  verified target.
- Automatic transcription requires a reachable local backend, a connected account, and a URL the
  installed yt-dlp build can download. Login, region, or anti-bot restrictions may require a matching
  Browser Pool identity or proxy; DRM media remains unavailable.
- Import/transcription support and in-page control are separate capabilities. A custom player,
  cross-origin iframe, or DRM player may be recognized by yt-dlp without exposing a usable page
  `<video>`; import and transcription remain available, but seeking and frame capture are disabled.
- Frame capture first exports decoded `<video>` pixels. If cross-origin media blocks Canvas export,
  it temporarily hides HTML player overlays and crops only the video rectangle; this fallback refuses
  to run when the player is fully off-screen.
- Backend connections are limited to `localhost` / `127.0.0.1`.

## Develop and verify

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
cd backend && uv run pytest tests/test_url_import.py
```

The backend test performs a network-free contract check against every canonical HTTP(S) extractor
sample shipped with yt-dlp. Live site sampling is still affected by the test machine's login state,
IP, region, and each site's anti-bot controls; failures must distinguish access restrictions from
adapter regressions.

The panel uses React, Tailwind CSS v4, and extension-owned shadcn/ui components. Feature views do
not directly use native form controls or maintain a legacy hand-written class stylesheet. The build
bundles `src/background.ts`, `src/content.ts`, `src/page-bridge.ts`, and `src/sidepanel.tsx`, compiles
the Tailwind theme from `src/styles.css`, and writes the manifest, `_locales`, HTML, and icon to
`dist/`. The root `package.json` version is injected into the manifest so extension and desktop
releases match.
