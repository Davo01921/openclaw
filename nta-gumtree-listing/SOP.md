# Gumtree BAU operation

Use the production workflow in [SKILL.md](SKILL.md). Current installation and registry: `/Users/davidlo/openclaw-skills-v3/nta-gumtree-listing`; the main-agent workshop skill is a mirror.

1. Read current Shopify facts, all twelve Gumtree fields and the existing registry. Missing activation fields mean HOLD, even if the cached registry previously said CONFIGURED.
2. Before registry maintenance, run the documented SQLite backup utility. Check the backup with `PRAGMA integrity_check`; preserve a dated copy outside Git.
3. Run `scripts/gumtree_queue_runner.py` against the normalized current records. It prepares at most three packages on Thursday–Saturday in Sydney. It never interacts with Gumtree.
4. Review updates, stock-zero pause/archive requests, duplicate/conflicting identities and unknown existing listings separately. They require manual Gumtree action; do not turn a review outcome into a new advertisement.
5. After manual posting, record the exact supplied listing ID/URL, then explicitly verify before marking VERIFIED. Do not infer success from a queue entry or a reminder.
6. Retain local input, queue and operator evidence. Repeating preparation against the same frozen inputs is safe. Failed or ambiguous work stays held.

Recovery: stop registry maintenance, retain the current DB and evidence, restore a verified SQLite backup while writers are stopped, then reconcile current Shopify and operator-supplied listing references. A registry restore cannot undo a Gumtree account action. Never replay posting from a restored queue without checking the existing listing.

The six scheduled product reminders use manual-post instructions; they do not authorize browser automation. Review stock and configuration on the scheduled day.
