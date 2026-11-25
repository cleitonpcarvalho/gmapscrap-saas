# Dependency security review — 19 November 2026

The six npm findings were **six affected package entries**, aggregating 28
individual advisories. A fresh registry audit confirmed one critical, three high
and two moderate package entries before remediation. After a clean `npm ci`,
`npm audit --include=dev --include=optional --json` reports **zero known
vulnerabilities** across production, development and optional dependencies.
This is an npm advisory check, not a claim that the entire application is free of
all vulnerabilities. Versions, advisory URLs/ranges and the refreshed production
preview verification are recorded in [dependency-security-review.json](dependency-security-review.json).

## Affected versions and fixes

| Package | Previously installed | Installed after fix | Severity | Finding |
| --- | --- | --- | --- | --- |
| next | 16.2.10 | 16.4.5 | Critical | Five RCE advisories plus authorization bypass, SSRF, denial of service, cache poisoning and disclosure issues |
| sharp | 0.34.5 | 0.35.5 | High | Vulnerabilities inherited from libvips, libheif and librsvg |
| postcss | 8.5.19 | 8.5.23 | Moderate | Untrusted source-map paths could read arbitrary `.map` files when `from` is unset |
| nanoid | 3.3.16 | 3.3.20 | High | A zero size supplied to custom generators can cause an infinite loop |
| source-map-js | 1.2.1 | 1.2.4 | High | Indexed source-map offsets can block the event loop |
| baseline-browser-mapping | 2.10.43 | 2.11.38 | Moderate | Invalid input could terminate the process |

Next.js is the direct dependency. The other five are transitive dependencies:
Next.js loads Sharp and baseline-browser-mapping; PostCSS is shared by Next.js
and the Vite test tooling, and loads Nano ID and source-map-js.

Next.js **16.4.5** is the first version outside every reported Next.js affected
range in this audit. Updating only to 16.2.11 or 16.4.1 would leave later findings
unresolved. The project stays on Next.js 16, with React/React DOM 19.2.7 unchanged.
The manifest pins Next.js 16.4.5 and the existing PostCSS override is raised to
8.5.23. The lockfile records the compatible transitive patches. Next.js itself
requests Sharp `^0.35.5`, avoiding a forced incompatible override. Next.js and
Sharp both support Node >=20.9; the existing production Dockerfile uses Node 24.
No `npm audit fix --force`, major upgrade or production setting change was used.
The generated Next.js type references include the new root-params declarations.

## Critical Next.js findings and application exposure

The critical package entry includes these maintainer advisories:

- [Windows server RCE](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36), fixed in 16.3.3.
- [AVIF image optimization RCE](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4), fixed in 16.3.3.
- [next/og ImageResponse RCE](https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j), fixed in 16.3.6.
- [SVG image optimization RCE](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw), fixed in 16.4.1 with Sharp >=0.35.5.
- [Typed arrays returned by use-cache functions](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr), fixed in 16.4.1.

Code inspection found no Server Actions (`use server`), Cache Components/
`use cache`, `next/og`, `next/image`, custom rewrites, or SVG image-optimization
configuration in the application. The existing production frontend image uses
Alpine Linux, so the Windows-specific condition does not match, and the SVG
advisory's glibc condition does not match that image. These observations reduce
exposure to specific exploit paths; they do not justify leaving the vulnerable
framework installed. No exploit was attempted against production.

The [16.4.5 security release](https://github.com/vercel/next.js/releases/tag/v16.4.5)
also fixes the [nested-cache leak through 16.4.4](https://github.com/vercel/next.js/security/advisories/GHSA-vc7v-qv4w-wrv8).
Other maintainer references: [Sharp 0.35.5](https://github.com/lovell/sharp/releases/tag/v0.35.5),
[PostCSS 8.5.23](https://github.com/postcss/postcss/releases/tag/8.5.23),
[Nano ID 3.3.18 security patch](https://github.com/ai/nanoid/releases/tag/3.3.18),
[source-map-js 1.2.2](https://github.com/7rulnik/source-map-js/releases/tag/v1.2.2),
and [baseline-browser-mapping 2.11.0](https://github.com/web-platform-dx/baseline-browser-mapping/releases/tag/v2.11.0).

## Validation and remaining build blocker

- Clean `npm ci`: passed; `npm ls` reports a valid dependency tree.
- Full Python/API/desktop/PostgreSQL suite: **185 passed**, no skips/deselections;
  five existing deprecation warnings. PostgreSQL 17 used a newly initialized
  disposable local cluster, with production connection settings disabled.
  Migration/correction execution tests ran only in that disposable database.
- Frontend suite after fixes: **8 passed**.
- Frontend production build with the production API URL: **passed**, including
  TypeScript, standalone output and all 12 static pages, including `/nichos`.
- Generated production-server smoke check: `/`, `/nichos` and a bundled
  JavaScript asset returned HTTP 200 over loopback. No production API requests
  were made; the temporary server was stopped afterward.
- Sharp native PNG encode/decode smoke check: passed with Sharp 0.35.5.
- `git diff --check`: passed.

The first framework build caught two unsupported `exact` options in test
`getByRole` queries. Removing those redundant options preserved exact string
matching and resolved the type errors. A subsequent build encountered local
`ENOSPC`; removing only this task's temporary npm cache, stopped test cluster and
incomplete generated output allowed the frontend production build to pass.

Both **Linux amd64 Docker production-image builds were attempted**, using the
unchanged production Dockerfiles and local-only tags. They did not complete:
Docker's BuildKit metadata database returned `input/output error` after disk
exhaustion. A cleanup attempt targeting only this task's exact temporary cache
ID failed with the same metadata error. Three unrelated local containers are
running; Docker was not restarted, reset or broadly pruned. No images were
pushed and no containers/services were deployed.

The dependency fixes and application tests are ready for review. Deployment
verification remains incomplete until disk capacity/Docker metadata are recovered
and both Linux images build successfully. The successful macOS production bundle
build does not establish Linux image-build success.

## Production import preview

Revalidated on **19 November 2026 at 20:44:08 UTC** (17:44:08 America/Fortaleza)
using PostgreSQL-enforced read-only repeatable-read transactions:

- **761 leads and 40 searches**, with complete row-content fingerprints matching
  the previously approved correction audit.
- **0 registered niches** and **0 case-insensitive registry duplicates**.
- **16 distinct raw labels / 16 valid normalized candidates**, with no duplicate
  candidates or invalid labels. All 16 proposed names match the previous preview.
- Whitespace/case normalization uses the same validation as the existing API.
  Historical searches with no leads remain included.

Exact names and source counts remain in [niche-import-preview.json](niche-import-preview.json).
No import, migration, correction or production write was performed. The existing
production compose configuration, niche migration and correction SQL retain
their previously verified checksums. No new database migration is required.

The **16-name import is ready for explicit approval**, with a final duplicate
recheck immediately before approved authenticated `POST /api/niches` calls.
Import and deployment remain separate actions; neither has been authorized here.
