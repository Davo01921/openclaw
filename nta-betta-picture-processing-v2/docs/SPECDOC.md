# NTA Betta Processing V2.2 — Functional Specification

Version: 2.2 · Repository: `Davo01921/openclaw-skills`

Status legend: **[I]** implemented · **[T]** implemented and tested (offline) ·
**[G]** implemented but gated pending activation · **[D]** deferred.

## 1. Business objective

Convert original labelled Betta photographs into accurate, verified Shopify
listing updates with minimal owner effort. Target experience: drop photographs,
Fred does the rest, finished fish appear on Shopify.

## 2. Production scope

Individual Bettas matched to existing Shopify products; authorised title/date/media
updates and guarded inventory. Excludes product creation, pricing/description
edits, and non-Betta catalogue work.

## 3. User requirements

- UR1 [G] No routine approvals/Discord/Terminal after activation.
- UR2 [I] Owner drops originals into the intake folder.
- UR3 [I] Uncertain fish are quarantined, never published wrongly.
- UR4 [I] Existing Grok/xAI generation is preserved.
- UR5 [I] Discord reports completion and genuine exceptions.

## 4. Functional requirements

- FR1 [T] Detect new originals, wait for settle, dedupe by SHA-256. [I]
- FR2 [T] Allocate a unique batch id and isolated workspace.
- FR3 [T] Identify tank/date; normalise IDs and Australian dates.
- FR4 [T] Invoke the existing Grok generator and hero finishing.
- FR5 [T] Independent QA; quarantine material discrepancies.
- FR6 [T] Exact product matching (one-to-one).
- FR7 [T] Build an immutable manifest bound to its SHA-256.
- FR8 [G] Apply standing policy and write authorised changes.
- FR9 [T] Independent Shopify read-back verification.
- FR10 [T] Record telemetry during execution; export with the archive.
- FR11 [T] Archive originals/heroes/evidence with hash verification.
- FR12 [T] Close the batch registry; report in Discord.
- FR13 [T] Resume/idempotency: never repeat a paid generation or Shopify mutation.

## 5. Nonfunctional requirements

- NFR1 Fail-closed on missing identity, QA failure, authority, or telemetry.
- NFR2 Crash-safe, resumable, restart-persistent.
- NFR3 Batch-independent; no hardcoded tank/date/filename.
- NFR4 No duplicate inventory adjustments; concurrency-safe updates.
- NFR5 Observable via structured telemetry/logs.
- NFR6 Credentials never read/printed/committed.

## 6. Photograph intake requirements

- Formats `.png .jpg .jpeg .tif .tiff .heic .webp .bmp`; top-level intake only.
- Ignore dotfiles, temp/partial files, generated names and archive/batch folders.
- Preserve original bytes; never move/rename/delete originals during processing.

## 7. Identity and metadata requirements

- Tank normalisation `2 BT 14`→`2BT14`; date DD/MM/YYYY (ISO accepted).
- Year provenance: clear (card) or trusted reference; else hold.
- Duplicate/ambiguous tank ids → quarantine all clashes.

## 8. Image generation requirements

- Provider xAI, model `grok-imagine-image-2.0`, approved prompt, black background,
  2048×2048 PNG. **[I] unchanged**.
- Credential via `XAI_API_KEY` or Keychain `nta-betta-xai`.
- Paid generation disabled unless explicitly authorised.

## 9. Image fidelity and QA criteria

Deterministic: dimensions, filenames, label, framing, original-reference hash.
Visual: same identity, body anatomy, scale markings, regional colour, tail/fins
pose, complete framing, realistic texture, hero composition, label, reference
integrity. Material changes never auto-accepted; metadata/date mismatches are not
fidelity passes.

## 10. Shopify integration requirements

- Read-only resolve; exact Product/Variant/InventoryItem/Location.
- Mutations via the existing uploader with `--live` + exact manifest SHA-256.
- Media: hero Image 1, untouched original Image 2; old media removed only after
  replacements are READY and verified.

## 11. Stock and inventory requirements

- Resolve item+location; read current; require tracked + DENY; configured
  transition (default 0→1); compare-and-set + idempotency key; verify.
- Unexpected values hold; never adjust twice per intake.

## 12. Standing-authorisation boundaries

Permitted: approved title, verified arrival date, hero+original media/order,
guarded inventory. Protected: description, price, cost, vendor, product type,
handle, status, IDs, metafields, tracking, DENY. Authorisation bound to the exact
manifest SHA-256; disabled by default.

## 13. Telemetry requirements

Per call as it occurs: batch, tank, stage, provider/model, attempt, timestamp,
duration, outcome, tokens (when reported), cost + source, error. No invented usage.
Exports archived automatically.

## 14. Archive and cleanup requirements

`Archived Bettas/YYYY-MM-DD/{Betta Processing,Betta Processed,Audit}` with
batch-specific names; collision isolation; destination SHA-256 verified before
removing working copies; never delete unrelated files/credentials/state.

## 15. Discord notification requirements

Report batch id, received/published/quarantined counts, verification results,
generation cost, archive status, genuine errors. No routine approval requests.

## 16. Error and recovery requirements

Resumable state; reconcile uncertain Shopify writes by read before retry;
per-fish quarantine; partial success reported accurately.

## 17. Security requirements

No secrets in repo/manifests/logs; least-privilege standing scope; read-only
resolve; live writes require explicit authority and digest.

## 18. Performance and cost controls

Global external-op concurrency 4; telemetry informs concurrency changes;
per-fish/per-batch generation ceilings and retry policy enforced by policy.

## 19. Acceptance criteria

- [I] Fresh batch allocated from new originals; dedupe prevents reprocessing.
- [T] Orchestrator completes intake→archive offline with mocks; resume repeats no
  writes/generation.
- [I] Material discrepancies quarantine; accepted exceptions recorded distinctly.
- [I] Archive destination hashes verified; historical batches immutable.
- [ ] A supervised live orchestrator run (pending owner-authorised activation).

## 20. Out-of-scope capabilities

Product creation; price/cost/description changes; non-Betta catalogue; batch-size
assumptions; unlimited spending. Deferred: full QA-exception auto-classification,
multi-date archive UI, Discord slash commands.

## 21. Change-control requirements

Changes to prompt/model/limits require owner approval and a new policy version.
Safeguards are not weakened to pass preflight.

## 22. BAU operational responsibilities

Owner: drop photos; decide genuine exceptions. Fred: run automatically; report.
Operators: emergency stop/rollback/credential checks. See SOP §19–21.

## Implemented vs deferred summary

Implemented + tested (offline): orchestrator, adapters/bindings, watcher, batch
lifecycle, policy, uploader safeguards, archive batch-scoping, telemetry.
Gated pending activation: watcher, standing Shopify authority, paid unattended
generation. Deferred: supervised live orchestrator acceptance run and explicit
production budget/retry ceilings.
