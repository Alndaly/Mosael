# Remotion Animation

Make animated videos with code: lesson explainers, formula walk-throughs, code demos and data charts. Rendering happens on your computer with [Remotion](https://www.remotion.dev) — no video generation model and no per-video cost.

## When to use it

- **Content that has to be exact** (text, formulas, steps, numbers) → use this. Text is real text, formulas are typeset by KaTeX, and code appears line by line.
- **Realistic footage** (people, places, a live-action feel) → use a video generation model (such as Seedance).

## License (please read first)

Remotion is not MIT licensed. Under the [Remotion License](https://www.remotion.dev/license):

- **Free**: individuals; for-profit organizations with no more than 3 employees; non-profit organizations; evaluation. Commercial use is allowed too.
- **A company license must be purchased**: for-profit organizations with 4 or more employees. Buy one at [remotion.pro](https://www.remotion.pro/license) and enter the key you receive in the plugin credential "Remotion license key".

This plugin does not distribute Remotion's code: it installs Remotion from the official registry with npm on your computer. **You are the licensee.**

## Requirements

- **Node.js 18 or newer** (with npm). Install it from [nodejs.org](https://nodejs.org), then restart Mosael.
- About **250 MB** of disk space: Remotion and the browser used for rendering, installed under `plugin-data/dev.mosael.remotion` in the Mosael data directory. Plugin updates do not reinstall it (unless the Remotion version changes); uninstalling the plugin deletes it too.

## Three tools

| Tool | What it does | Time |
| --- | --- | --- |
| Prepare the renderer `remotion_setup` | Installs Remotion and gets the rendering browser ready | Tens of seconds to a few minutes the first time; nearly instant after that |
| Explainer video `remotion_explainer` | Takes a title and each section's points / formulas / code / tips, and renders them with a template | About 20–40 seconds for a 30-second video |
| Custom animation `remotion_animation` | Takes a piece of Remotion component code; draw anything | Depends on the content |

The resulting mp4 goes straight into the asset library. Explainer videos support landscape 16:9, portrait 9:16 and square 1:1, dark / light themes and a custom accent color; the length of each section is calculated from its content.

**The first time, run "Prepare the renderer" once from the plugin page.** The rendering tools do not install the environment on the side: a single agent call waits at most 180 seconds, a first install often takes longer, and being cut off halfway only leaves a half-finished install behind. When the environment is incomplete, the rendering tools say exactly what is missing (not prepared yet, a plugin upgrade changed the Remotion version, Node.js changed architecture); just run "Prepare the renderer" again.

All three tools report progress as they run (the workflow run panel shows "Rendering 40%"); when you cancel from a workflow or task, Node stops together with the browser it started.

## Networks in mainland China

- **npm install stalls**: pick npmmirror in this connection's "npm registry" setting (by default it follows Admin → Download sources), then run "Prepare the renderer" again.
- **The browser won't download**: Remotion's own browser is downloaded from Google's servers. If the download fails, the plugin automatically falls back to a local Chrome / Edge; you can also enter their executable path directly in "Browser path".

## Writing a custom animation

The code is a TSX module that `export default`s a component; the component receives `{ data }` (the `data` passed with the call):

```tsx
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export default function Scene({ data }: { data: { word: string } }) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: "#111", color: "white", justifyContent: "center", alignItems: "center", fontSize: 120 }}>
      <span style={{ opacity: interpolate(frame, [0, 20], [0, 1]) }}>{data.word}</span>
    </AbsoluteFill>
  );
}
```

Only `react`, `remotion` and `katex` can be imported. If bundling or rendering fails, the error (file, line, column) is returned as is; fix it and call again.

## Permissions

- `process:spawn`: starts node / npm.
- `network:npm`: installs dependencies from the npm registry and downloads the rendering browser the first time the environment is prepared. Rendering itself does not go online.
- `filesystem:write`: writes to the plugin's own data directory.

## Versions

Remotion 4.0.526, React 19.3.0, KaTeX 0.18.7, all pinned to exact versions (`tools/project/package.json`). When a plugin upgrade changes the versions, the rendering tools remind you to run "Prepare the renderer" again, which reinstalls the new versions.
