# Website and blog qualification

This feature lives on `feature/website-blog-qualification`. It has **not been deployed**. The previous release `9b471c7b5d4ab224b8a8bf5c88d41507ef997eca` was deployed successfully on November 25, 2026 ([Actions run](https://github.com/cleitonpcarvalho/gmapscrap-saas/actions/runs/45641589574)). Both backend/frontend running image labels and service specs match that revision. The deployment's authenticated CRM/API/frontend checks passed. Searches 29, 38 and 40 are still paused; hashes of every original field match their pre-migration values.

## Architecture and data

The existing FastAPI app, SQLAlchemy sessions, saved lead IDs, authentication, lead list, CRM company details and exports are reused. Three additive tables hold derived information and durable work:

* `lead_website_qualifications`: one observation per lead, nullable unavailable fields, original website fingerprint, availability, CMS/platform, WordPress/blog conclusions, blog/article URLs, total exposed published posts, publication date/title, inactivity, priority, validation timestamp, evidence and bounded error codes.
* `website_qualification_jobs`: durable job identity, counts, state and timestamps.
* `website_qualification_items`: original website snapshot and a unique active lead claim. Existing results remain visible during revalidation. If the lead website changes during a check, the result is discarded and the item fails with `website_changed_revalidate`.

No analysis updates `leads`, `search_runs`, CRM, credentials or provider settings. Inactivity and priority are refreshed on reads and filters as observations age. Website edits mark earlier observations stale in details.

The worker uses a single PostgreSQL advisory-lock drainer across backend processes and three HTTP workers. Active work is capped at 1,000 leads, one submission at 500 IDs. Unique active lead claims and a transactional enqueue lock prevent concurrent duplicate checks. Progress survives restart; unfinished read-only HTTP checks resume. A five-second poll covers restart and enqueue races. No search or CRM scheduler is reused for qualification.

## Public-site analysis

WordPress confirmation requires HTML indicators, a public WordPress login form, or a REST namespace/routes signature. A successful status alone never confirms WordPress. The posts request is exactly `wp-json/wp/v2/posts?per_page=1&orderby=date&order=desc&_fields=date,link,title`. `X-WP-Total` is used only when consistent. An empty valid array means no posts exposed by that public endpoint; inaccessible/malformed responses leave totals null.

Fallback discovery follows same-site navigation, likely blog routes, robots sitemap declarations, sitemap indexes (up to four documents/250 URLs each), feeds, JSON-LD Article/BlogPosting/NewsArticle, `article:published_time`, and explicitly published time elements. `dateModified`, generic times and sitemap `lastmod` never become publication dates. Named platforms require generator evidence or a reliable platform asset marker. Latest publication means the latest verified publication observed in the bounded public sources; private articles and undiscovered sources are not enumerated. Multiple discovered blogs contribute to the latest observed date. No browser or webpage JavaScript runs.

Missing-blog conclusions require a small complete sitemap, inspection of all listed/navigation pages within the eight-page exhaustive limit, absence of article/blog evidence, and every guessed route returning 404/410 without blocking or unresolved errors. Otherwise absence stays inconclusive. A guessed 404 alone is insufficient.

Priority first uses a verified publication date: through 30 days LOW, 31–90 MEDIUM, beyond 90 HIGH for confirmed WordPress and MEDIUM otherwise. Without a date, verified absence or zero publicly exposed WordPress posts can qualify HIGH (WordPress) or MEDIUM (other); unavailable/ambiguous results stay INCONCLUSIVE.

## Network boundary

`qualification_http.py` accepts HTTP/HTTPS on their standard ports only, rejects userinfo, control characters, noncanonical numeric hosts, local hostnames, non-public IPv4/IPv6, mapped/transition addresses and metadata targets. All A/AAAA responses must be public. DNS has a bounded lifetime. Connections use a validated numeric address, verify the actual peer and retain the original hostname for verified TLS/SNI. There is no second hostname resolution during connection and environment proxies are never consulted. Every redirect (maximum four hops) repeats validation and robots authorization. Discovery redirects remain same-site after initial canonical redirects.

The crawler checks robots before pages, including redirects and API/login/feed routes. Unavailable robots rules fail closed except a genuine 404/410. Wildcard/end-anchor restrictions supplement the standard parser. Crawl-delay/request-rate apply inside a shared per-host connection lock, including retries. The default minimum delay is 500 ms, one request per host at a time, with three sites globally. A 401/403/429 halts further page requests to that site; no blocking evasion occurs. At most one retry follows transient network/502/503/504 failures, without disabling TLS.

Each analysis allows 28 network attempts, a 75-second budget, six-second socket timeouts, 2 MiB per response and 8 MiB aggregate bodies. Socket reads also enforce the absolute deadline and a wire-size limit, including slow headers. Compressed responses and XML DTD/entities are rejected. Logs and persisted errors use bounded reason codes, never response bodies, raw exceptions or credentials.

## API and UI

All endpoints require the existing session cookie:

* `POST /api/website-qualification/leads/{id}/analyze` starts/revalidates one saved lead.
* `POST /api/website-qualification/jobs` accepts `{ "lead_ids": [1,2], "revalidate": true }` and returns a job ID/counts; active duplicates are skipped.
* `GET /api/website-qualification/jobs/{id}` reports live completed/failed counts.
* `GET /api/website-qualification/leads/{id}` returns prior observation, staleness and active job.
* `GET /api/website-qualification/results` supports `cms`, `blog`, `priority`, `inactive_days`, `limit`, `offset` with stable lead-ID ordering.
* The existing `/api/leads` supports the same filters and bounded server pagination. CSV/XLSX use the same qualification filters and include every requested result field. Unknown values export as empty cells. CSV formula prefixes are escaped; XLSX uses text cells, never formulas.

The saved-lead list has a single-site details/action and bulk action for selected leads, or the loaded filtered leads (up to 500). Scope is visible. CMS/blog/priority/inactivity filters run on the server before the 500-row limit. CRM company details use the same analysis component without changing card drag/drop, sales outcome or company editing behavior. Details display evidence, nulls, last checked status and previous results during revalidation. Bulk progress restores its job ID after page reload.

## Migration and automated rollout — commands for the later release

`migrations/20261125_website_qualification.sql` is additive and changes no original business rows. It requires the effective `postgres` owner; all three tables enable RLS without public policies, revoke table/column API grants and preserve unrelated/default privileges. There are no serial sequences. Startup never silently creates these production tables. The release gate now allows this migration after the two already-recorded November 24 migrations; historical lead-security SQL remains excluded. Recorded checksums, columns/defaults, PK/FK/unique/check constraints, index validity and permissions are checked before deployment. Partial or unrecorded installations stop for review.

Do **not** run these commands as part of feature implementation. A reviewed PR and passing checks come first:

1. Push this dedicated feature branch and create a PR targeting `main`. PR CI runs all backend, PostgreSQL, desktop, CRM and frontend regressions without deploying. Review the migration and constraints; preserve current `main` ancestry. Do not force-push `main` or switch to a divergent local `main`.
2. Once all prerequisites and migration review pass, prepare the exact reviewed revision using the existing workflow:

   ```sh
   gh workflow run docker-images.yml --repo cleitonpcarvalho/gmapscrap-saas --ref feature/website-blog-qualification -f mode=prepare
   gh run list --repo cleitonpcarvalho/gmapscrap-saas --workflow docker-images.yml --branch feature/website-blog-qualification
   gh run watch RUN_ID --repo cleitonpcarvalho/gmapscrap-saas --exit-status
   ```

   Preparation rebuilds/tests that exact commit, uses credentials from the existing live backend without printing them, creates a new private full production archive, validates its checksum/TOC/full decompression, restores the complete public application schema into an isolated temporary PostgreSQL cluster, compares every original row/ACL, rehearses migrations and authenticated backend reads, then applies **only pending** allowlisted SQL atomically to production. It retains backup/evidence under `/var/lib/gmapscrap-deploy/RELEASE-UNIQUE/` with private permissions. It does not update services. Search IDs 29/38/40 need no restart, reclassification or verified-server override; leave the override empty.
3. Review successful preparation evidence. Any failure stops the release. Do not run SQL manually, reapply old security SQL, restore over production, drop a volume or perform a destructive rollback. The current backend is compatible with these additive tables and can continue running during preparation.
4. Merge the reviewed PR into GitHub `main` only after preparation passes. That push runs the existing pipeline again: tests → SHA-tagged image builds → fresh validated backup/restore gate → pending-only migrations → backend → frontend. The resulting **main commit SHA** is the release identity (it can differ from the feature commit after a merge). Services use immutable image digests, stop-first updates and pause-on-failure.
5. Watch that main run to successful completion. Verify `/api/health` reports the exact main SHA, both running service image revisions/digests match it, authenticated lead/qualification/CRM endpoints return 200, anonymous CRM remains 401, frontend `/` and `/crm` return 200, and the original protected search fingerprints/statuses remain unchanged. The updated smoke script includes read-only lead and qualification endpoints; never launch qualification jobs as a production smoke check.

The restore rehearsal tests recovery of the application public schema with original owners/ACLs. It does not claim a complete managed Supabase platform disaster-recovery rehearsal. No unrelated database, Docker service or volume is changed by the process.

## Verification

Final local results on November 25, 2026: **455 backend tests passed, 3 optional environment-dependent tests skipped; 57 frontend tests passed; TypeScript, optimized Next.js build, actionlint and diff whitespace checks passed.** Real PostgreSQL tests used only disposable databases on task-owned loopback PostgreSQL 17 clusters, including a real custom archive restore rehearsal. No feature migration or feature code was applied to production. Release readiness still requires reviewed migration/PR, CI validation of the exact revision, and a fresh successful production preparation gate as described above.

The complete regression suite includes the existing backend, real PostgreSQL/CRM security and drag/drop tests, desktop execution and release backup/restore rehearsal. New tests exercise WordPress/non-WordPress detection, malformed and inaccessible APIs, publication boundaries, sitemap indexes, arbitrary article permalinks, external blog ambiguity, robots, IPv4/IPv6 SSRF, DNS answers, redirects, pinned peer/TLS hostname, actual HTTP parsing and limits, host pacing/retries/serialization, durable duplicate claims, bulk concurrency/progress, pagination/filters, CSV/XLSX injection escaping, original lead/search preservation and pending-only migration from the deployed two-migration state.

Security implementation references: [OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html), [Python HTTP client](https://docs.python.org/3.12/library/http.client.html), [Python robots parser](https://docs.python.org/3.12/library/urllib.robotparser.html). These inform the transport boundary; passing synthetic tests does not prove that every public site exposes enough publication information to qualify conclusively.
