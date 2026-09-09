# Current interface captures

Documentation targets **1.2.0**. Changed 3D, note and annotation views are freshly captured from the running app; unchanged views retain their earlier captures, not reconstructed UI or generated mockups. The canonical files live in [`website/public/media`](../../website/public/media). Historical design-review attachments elsewhere in `docs` are not current product documentation.

## Source and credit

Sample footage and extracted frames: **Big Buck Bunny**, © 2008 Blender Foundation / www.bigbuckbunny.org, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). [Film and license](https://peach.blender.org/about/); [source trailer](https://media.w3.org/2010/05/bunny/trailer.mp4). Excerpts are trimmed, resized and rearranged in the demo timeline. Narration was synthesized with the macOS Samantha voice; subtitle cues are manually prepared editing exercises.

The demo backend is isolated from personal projects and credentials. Empty AI and publishing pages show the actual unconfigured state. No AI responses, tool successes, login successes or platform posts are fabricated. The Chinese and English interface recordings use the same bilingual sample project.

## Inventory

- `screens/`: full-resolution native screenshots (2880 × 1800).
- `gifs/`: actual browser recordings converted to looping 960 × 600 GIFs.
- `videos/`: the same interactions as user-controlled 1280 × 800 MP4 recordings.
- Chinese light files are at each directory root; `dark/` contains Chinese dark; `en/` and `en/dark/` contain English light and dark.
- `capture-manifest.json` records per-file source commit, capture version/time, scene, locale, theme, byte count and SHA-256. The batch documentedVersion is not a claim that every file was recaptured.
- `mosael-promo.mp4` is a concatenation of the current Home, media preview, timeline, board and workflow screen recordings, with no simulated product output.

Scenes: 3D camera views and object keys; note editing/reading/Markdown; document dragging and marker modes; Home and project navigation; import and media previews; timeline selection/playback; subtitle dubbing and Transcript; AI Chat/Trace/Generate; workflow node catalog and parameters; board forms and `@` media picker; plugin connections; publishing form and browser accounts; scheduled tasks; provider/ASR settings; interface fonts; sign-in.

The previous handcrafted promo, obsolete GIF aliases and unused website hero images were retired rather than left beside current captures.

## Re-record

Run the current frontend on `http://127.0.0.1:5173` and an **isolated demo backend** on a loopback port. Import appropriately licensed sample media, prepare a project with video/audio/subtitle tracks, a board, the official speech-cleanup workflow, a scheduled task and sample plugin connections. Do not use a personal backend for public recordings.

Prepare a private JSON-string token file and a fixture JSON containing `project`, `sequence`, `board`, `workflow` IDs and an `assets` map with `forest`, `narration` and `forest-frame` IDs. The recording script names its expected demo cards explicitly; keep those titles aligned when updating the fixture. Never commit either authentication tokens or the demo database.

```bash
backend/.venv/bin/python scripts/record-doc-media.py \
  --api http://127.0.0.1:8812 \
  --token-file /tmp/demo-token.json \
  --fixture /tmp/demo-capture.json
```

Requires Playwright Chromium and ffmpeg. Use `--locale zh|en`, `--theme light|dark`, or `--only scene,scene` to retry a scene. A failed selector stops capture instead of substituting an old image. The script performs real clicks and records real browser video; it does not replace UI text or DOM content.

After recording, review screenshots and moving frames, update the related bilingual guide and its version, run `pnpm --dir website test` and `pnpm --dir website build`, and check both themes on desktop and narrow screens. The media tests reject stale/untracked public captures, incorrect-language references and missing light/dark pairs.

## README showcase

`readme-showcase.zh.png` and `readme-showcase.en.png` are composed by `scripts/compose-readme-showcase.py` from the same three unaltered 1.2.0 homepage captures the website uses (`website/public/media/homepage/{zh,en}/{boards,editor,scenes}.png`). The script reproduces the homepage's own layout — boards behind left at -2°, the editor behind right at +2°, the 3D scene in front — reading the percentages from `website/src/components/home-showcase.tsx`. Only rounded corners, a hairline border and a drop shadow are added; the screenshots themselves are untouched. Regenerate with `python3 scripts/compose-readme-showcase.py` after re-capturing the homepage images.

The previous composite was assembled by hand from a separate `readme-shots/` directory. That made it a dead file: when the captures were refreshed nothing pointed at it, while the caption underneath still claimed it showed the current interface. Both it and `readme-shots/` were retired.

The manifest records `documentedVersion: 1.2.0`. Each file keeps its own capture version and source commit. Some unchanged views still originate from 1.0.0-beta5; fresh files are tagged 1.2.0. The 3D scene and bilingual gallery brief are manually prepared demonstration content, not generated results. Some 3D controls currently remain Chinese in English mode; recordings preserve the real interface.

For the new scenes, use `--only scenes,notes,annotations`. The fixture needs `scene`, `note` and `board` IDs for the gallery example, gallery brief and story board; titles are declared in the capture script. No provider calls, publication or external messages are performed.

## Homepage feature windows (1.2.0)

`website/public/media/homepage/{zh,en}/` contains six fresh, unaltered 2× browser captures taken on 2026-09-09 from the running app at commit `54ecfda1`. Each uses a 1440×940 viewport and an isolated demo workspace:

- `boards.png`: the connected story-study board; light WenKai (Chinese) / Caveat (English).
- `editor.png`: the working Big Buck Bunny picture, audio and subtitle timeline; dark Newsreader.
- `scenes.png`: the gallery scene with global camera path, shot inset and object/camera keyframes; dark Space Grotesk.

The homepage composes these original screenshots as overlapping windows in HTML. Its feature selectors bring one complete window forward; phones show one complete window at a time. The surrounding site follows its own light/dark theme while the captures deliberately retain different supported app appearances. The 3D feature chapter uses the same fresh scene capture. No app controls, content or generation results were fabricated. The footage attribution above also applies to these images.

Re-capture with the existing Python Playwright environment and prepared local demo fixtures (tokens are JSON strings in private local files):

```sh
backend/.venv/bin/python scripts/capture-homepage.py \
  --scene-api http://127.0.0.1:8813 --scene-token /private/path/scene-token.json \
  --editor-api http://127.0.0.1:8812 --editor-token /private/path/editor-token.json \
  --editor-fixture /private/path/editor-fixture.json
```

The scene demo contains “三间展厅 · Camera study”; the editor demo contains “镜头与灵感 · Story study” and a fixture with its `project` ID. The script records source commit, version, language, theme, font, timestamp, dimensions and SHA-256 in `capture-manifest.json`. Website media tests verify the homepage captures alongside documentation screenshots and recordings.
