# Open Studio Chrome extension

**English** | [简体中文](README.zh-CN.md)

This extension brings Open Studio's video companion into Chrome's native Side Panel. It does not
inject a floating window into the page, and it follows the active video tab.

## Features

- Read existing YouTube and Bilibili captions as a transcript.
- Click any cue to seek to its timestamp; the current cue is highlighted during playback.
- Search the transcript and translate it into Chinese, English, Japanese, Korean, French, German, or Spanish.
- Submit the current video URL to the Open Studio media library.
- Capture the currently visible player frame and import it as a PNG asset.
- Choose a destination workspace and optional project.

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
3. Reading and seeking through the transcript does not require an Open Studio connection.
4. The first time you translate, import, or capture, open settings in the panel, sign in with your
   Open Studio account, and choose a destination workspace.

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

## Known limitations

- Chrome 116+ with the Manifest V3 Side Panel is supported. Edge may be compatible but is not yet a
  verified target.
- Transcripts depend on captions supplied by the site. Import videos without captions and run speech
  transcription in Open Studio.
- Frame capture crops the visible player area and refuses to run if the player is fully off-screen.
- Connections are limited to `localhost` / `127.0.0.1` so the extension does not request broad web access.

## Develop and verify

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
```

The build bundles `src/background.ts`, `src/content.ts`, `src/page-bridge.ts`, and
`src/sidepanel.ts`, then copies the manifest, CSS, HTML, and icon into `dist/`. The root
`package.json` version is injected into the manifest so the extension and desktop release match.
