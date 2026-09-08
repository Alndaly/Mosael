# Homepage: 3D introduction and live feature windows

The Chinese and English homepages now introduce 3D scenes immediately after the infinite canvas, covering camera/object keyframes, global camera paths with a shot inset, image/video reference handoff and Blender exchange. The hero combines three freshly captured app windows: a light handwritten canvas, a dark serif editor and a dark geometric-sans 3D studio.

The screenshots retain actual UI and supported appearance preferences; English captures preserve the few 3D controls that the app still renders in Chinese. The capture script, media provenance and footage attribution are documented in `docs/media/README.md`.

## Validation

- `pnpm --dir website test`: 8 tests passed. The existing provenance check now includes `media/homepage/` and verifies all six source image hashes.
- `pnpm --dir website build`: production compilation, TypeScript and static page generation passed.
- Playwright against the production build: Chinese/English × light/dark × 1440×1000/390×844, eight combinations passed. Verified image loading, single active feature selector, mouse and Enter-key switching, correct localized documentation links, no horizontal overflow and no browser page errors. Reduced-motion mode was included; normal-motion desktop switching was also inspected during visual review.
- Desktop/light/dark and mobile layouts were visually reviewed. Desktop windows overlap with the selected window fully in front; phones retain a complete single screenshot and all three selectors. The new chapter uses the freshly captured 3D image.
- `git diff --check`: passed.
- Website ESLint could not start: the existing `typescript-eslint@8.69.0` dependency rejects the repository's TypeScript 7.0.2. This pre-existing tooling incompatibility is separate from the successful production TypeScript check; no lint success is claimed.

No provider calls, generated results or external messages were used. Demo captures used isolated local backends; personal app projects and credentials were not changed.
