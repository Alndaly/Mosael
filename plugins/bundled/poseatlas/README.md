# PoseAtlas

Brings the two atlases from [RuiC-PoseAtlas](https://hruiccc.github.io/RuiC-PoseAtlas/) into Mosael's **reference library**
(switch the Assets page to **Reference library** at the right of the filter bar, ADR 0091):

- **Pose atlas** — faceless grey mannequin line art, five camera angles per pose (front, three-quarter, side, high, low);
- **Costume atlas** — complete outfits without a person, by spring / summer / autumn / winter / swimwear / party and more,
  with color, material and item tags.

Browse and search it (Chinese, English and Japanese names and ids all match), then **Use as media** to take the original
image into your workspace as media. **Save as asset** also creates a pose / costume asset you can `@` in a generation —
a pose goes to the model as a *pose reference*, constraining only the body pose and composition.

## Provenance and license

- Images, original names and categories come from POSE-DB-01 / COSTUME-DB-01 by
  [ギア (@giaaibusi)](https://x.com/giaaibusi), curated with English names by RuiC-PoseAtlas. All are AI-generated fictional
  reference material.
- Image copyright belongs to the original author. **For reference and creative use only — redistributing, reposting or
  reselling the images themselves is prohibited.**
- This plugin **ships no images**: browsing shows the site's own thumbnails, and taking one downloads just that image from
  the site into your own workspace. Imported media keeps its provenance (author, site, license note), never goes into a
  Mosael share package and is never synced to MosaelCloud.
- The plugin code is released under the repository's license.

## Adult content

The site has Sexy and Couples series (the latter includes sex positions), two upper-body categories (Bold, Cleavage) and the
Lingerie and Sexy costume categories. The connection setting **Include adult content is off by default**: while off, those
entries never appear; when on, they are marked NSFW and blurred or hidden per your Preview settings (the same setting as the
model library).

## Network and cache

- Needs access to `hruiccc.github.io` (permission `network:github`).
- The two indexes (a few hundred KB of JSON) are cached in the plugin's persistent folder and refreshed daily; if a refresh
  fails, the previous copy is used.
