import snapshot from "../../content/releases.json";
import { publishedReleases } from "./release-data";

export async function listReleases() {
  try {
    const response = await fetch("https://api.github.com/repos/Alndaly/Mosael/releases?per_page=30", {
      // A new published-release snapshot gets a fresh fetch-cache key on deployment.
      // Otherwise Vercel can keep the previous release list for the full revalidation hour.
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": `Mosael-Website/${Date.parse(snapshot.fetchedAt)}`,
      },
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error(`Release API returned ${response.status}`);
    const releases = publishedReleases(await response.json());
    if (!releases.length) throw new Error("No published releases returned");
    return { releases, offline: false, snapshotDate: snapshot.fetchedAt };
  } catch {
    return { releases: publishedReleases(snapshot.releases), offline: true, snapshotDate: snapshot.fetchedAt };
  }
}
