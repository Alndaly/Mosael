# Open Studio Chrome extension

**English** | [简体中文](README.zh-CN.md)

This extension brings Open Studio's video companion into Chrome's native Side Panel. It does not
inject a floating window into the page, and it follows the active video tab.

## Features

- Read YouTube and Bilibili captions as a transcript, or let Open Studio download and transcribe sites such as Pornhub when no structured captions are exposed.
- Open Studio transcripts retain word timestamps, so each word seeks precisely; site captions and legacy data fall back to cue-level seeking.
- Keep source and secondary text together as bilingual subtitles, with search across both lines.
- Prefer a site's second caption or YouTube translation track, then fall back to Open Studio translation.
- Submit the current video URL to the Open Studio media library.
- Extract only the current video frame, excluding HTML playback controls, and import it as a PNG asset.
- Choose a destination workspace and optional project.
- Follow Chrome's UI language automatically, or pin the panel to Simplified Chinese or English.

## Install

### From a Release

Download and unzip `open-studio-browser-extension.zip` from a GitHub Release, then:

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

1. Start Open Studio and make sure its local backend is running at `http://127.0.0.1:8800`.
2. Open a YouTube, Bilibili, or Pornhub video and click the extension icon to open the Side Panel.
3. Reading site captions and a site-provided secondary track does not require an Open Studio connection.
4. The first time you auto-transcribe, use AI translation, import, or capture, open settings in the panel, sign in with your
   Open Studio account, and choose a destination workspace.
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
| Optional `<all_urls>` | Requested on demand the first time “Capture current frame” is used; enables Chrome's screenshot API and is not granted at install time |
| `storage` | Store the Open Studio session and destination workspace |
| YouTube domain family (`youtu.be`, `youtube-nocookie.com`, `googlevideo.com`, and `ytimg.com`) | Cover video pages, short links, embeds, and official media resources |
| Bilibili domain family (`hdslb.com`, `bilivideo.com`, and `bilivideo.cn`) | Cover video pages, caption files, and official media resources; captions are fetched in the extension background to avoid page translation and CORS interference |
| Pornhub page domain | Detect video pages, synchronize and seek the HTML5 player, capture frames, and submit links; fall back to Open Studio when the site exposes no structured captions |
| `127.0.0.1` / `localhost` host access | Call the local Open Studio API |

The extension does not request the `cookies` permission and never exports browser login state to
Open Studio. Captions that the current page can already access may work for members-only content,
but **video import** is downloaded by the Open Studio backend. Import restricted content from the app
with the matching Browser Pool profile instead.

Bilibili caption URLs are short-lived. The extension refreshes the caption listing for the current
`bvid` / `cid` on every entry instead of reusing a possibly stale page URL. Background caption
requests are restricted to the required official API and subtitle paths.

Host permissions cover each supported site's resource-domain family, while the background network
proxy remains restricted to caption APIs and caption-file paths required by the adapters. Pornhub's
current player uses blob media and exposes no structured caption track, so its adapter selects the
real visible, playable video instead of hidden ad or placeholder `<video>` elements and uses the
Open Studio transcription fallback.

## Automatic transcription when captions are missing

When the site returns no captions, the panel offers **Generate transcript with Open Studio**. It
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
job, so no manual migration is required. YouTube share links, Pornhub language subdomains, and common
tracking parameters do not split one video into separate identities.

## Known limitations

- Chrome 116+ with the Manifest V3 Side Panel is supported. Edge may be compatible but is not yet a
  verified target.
- Automatic transcription requires a reachable local backend, a connected account, and a URL the
  backend can download.
- Frame capture first exports decoded `<video>` pixels. If cross-origin media blocks Canvas export,
  it temporarily hides HTML player overlays and crops only the video rectangle; this fallback refuses
  to run when the player is fully off-screen.
- Backend connections are limited to `localhost` / `127.0.0.1`; the cross-origin capture fallback separately requests optional screenshot access on first use.

## Develop and verify

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
```

The panel uses React, Tailwind CSS v4, and extension-owned shadcn/ui components. Feature views do
not directly use native form controls or maintain a legacy hand-written class stylesheet. The build
bundles `src/background.ts`, `src/content.ts`, `src/page-bridge.ts`, and `src/sidepanel.tsx`, compiles
the Tailwind theme from `src/styles.css`, and writes the manifest, `_locales`, HTML, and icon to
`dist/`. The root `package.json` version is injected into the manifest so extension and desktop
releases match.
