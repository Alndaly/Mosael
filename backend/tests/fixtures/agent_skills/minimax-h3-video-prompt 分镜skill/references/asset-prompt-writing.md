# Asset-prompt writing

Use this reference when the task starts from a simple idea or needs image assets before H3 generation. Produce prompts for an image generator; do not pretend they are H3 prompts.

## Asset planning

Create only the assets needed by the storyboard:

- One identity asset for each recurring character.
- One additional asset per visually distinct state only when it changes identity-critical details: transformed form, battle damage, armor, age, creature form, or a unique costume.
- One master establishing asset per reusable location and one state variant only when weather, destruction, time of day, or lighting must change.
- One exact start/end frame asset only when a clip needs I2VA, FL2VA, or L2VA anchoring.

Prefer a small, reusable asset set over redundant “three-view” images. Request front, profile, and back views only when the user needs turnaround design, not for every project.

## Character asset prompt

Write one self-contained prompt per asset in English. Include identity, apparent age range, physique, face/hair, skin tone, wardrobe construction and material, palette, distinctive prop, pose/expression, framing, lighting, background, and the requested render treatment. Keep the background neutral for identity assets. Do not add visible text, logos, watermarks, unrelated accessories, or extra people.

Template:

```text
Full-body character design sheet of [Character ID], [identity and appearance]. Wearing [specific wardrobe and materials], with [palette] and [signature prop]. [Neutral pose / requested state], [expression]. [Render treatment], [lighting], on a clean [neutral background]. Accurate anatomy, consistent facial identity, no text, no logo, no watermark, no extra people.
```

For a state variant, repeat the unchanging identity details and state the precise changed elements. Do not say merely “same character.”

## Scene asset prompt

Write one self-contained prompt per scene asset in English. Include location geometry, foreground/midground/background, time, weather, light direction, palette, material detail, atmosphere, human scale or subject placement only if needed, camera height/angle, and empty space needed for action. Do not include characters unless the scene is a keyframe.

Template:

```text
Cinematic environment concept art of [location]. Foreground: [details]. Midground: [details]. Background: [details]. [Time, weather, and light direction]; [palette and materials]. [Camera height and composition], with clear open action space at [screen area]. [Render treatment], no characters, no text, no logo, no watermark.
```

## Keyframe asset prompt

Use only when the storyboard needs an exact H3 anchor. Specify the target clip ID and whether it is the first frame, final frame, or both. The image prompt must match the planned H3 opening or closing composition: subject placement, pose, orientation, prop state, background, light, camera, and aspect ratio.

## Asset continuity rules

- Give every asset a stable ID, such as `CHAR_RIN_BASE`, `CHAR_RIN_ARMOR`, `SCENE_TEMPLE_NIGHT`, or `KF_03_END`.
- Carry stable IDs into the storyboard and identify the intended use: character identity reference, scene reference, first frame, or last frame.
- If a user supplies an image, preserve it as an existing asset and write only missing asset prompts around it.
- State the recommended image aspect ratio. Use the delivery ratio for keyframes; use a suitable design ratio for asset sheets only when the user does not specify one.
