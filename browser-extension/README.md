# Open Studio Chrome extension

**English** | [简体中文](README.zh-CN.md)

This extension brings Open Studio's video companion into Chrome's native Side Panel. It does not
inject a floating window into the page, and it follows the active video tab.

## Features

- Read YouTube and Bilibili captions as a transcript, or let Open Studio download and transcribe a video when the site has none.
- Click any cue to seek to its timestamp; playback highlights and follows the active cue.
- Keep source and secondary text together as bilingual subtitles, with search across both lines.
- Prefer a site's second caption or YouTube translation track, then fall back to Open Studio translation.
- Submit the current video URL to the Open Studio media library.
- Capture the currently visible player frame and import it as a PNG asset.
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
2. Open a YouTube or Bilibili video and click the extension icon to open the Side Panel.
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
| `storage` | Store the Open Studio session and destination workspace |
| YouTube / Bilibili host access | Read the current video's public player and caption data |
| `127.0.0.1` / `localhost` host access | Call the local Open Studio API |

The extension does not request the `cookies` permission and never exports browser login state to
Open Studio. Captions that the current page can already access may work for members-only content,
but **video import** is downloaded by the Open Studio backend. Import restricted content from the app
with the matching Browser Pool profile instead.

## Automatic transcription when captions are missing

When the site returns no captions, the panel offers **Generate transcript with Open Studio**. It
uses the existing backend pipeline: download the URL into the media library, start speech
recognition, poll the background job, and load the timed result back into the panel. Generated
transcripts retain playback following, seeking, search, and bilingual display. Long videos take as
long as the network and selected transcription engine require.

## Known limitations

- Chrome 116+ with the Manifest V3 Side Panel is supported. Edge may be compatible but is not yet a
  verified target.
- Automatic transcription requires a reachable local backend, a connected account, and a URL the
  backend can download.
- Frame capture crops the visible player area and refuses to run if the player is fully off-screen.
- Connections are limited to `localhost` / `127.0.0.1` so the extension does not request broad web access.

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
