# Label recognition evidence — incident photo (dual-read evaluation)

Real live evaluation of the label pipeline on the incident photograph, run on
2026-10-15 (UTC timestamps 2026-10-14T23:12Z / 23:14Z) from the worktree
`/Users/davidlo/openclaw-skills-incident-repair`, branch
`codex/betta-identity-incident-20261015`. Two live calls were made (budget ≤ 6;
2 used, 4 unspent).

- Source photo: `tests/fixtures/incident_2bt23/incident-photo.png`
  (1512×2688 PNG), SHA-256
  `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9`
- Expected (documented truth for this photo): tank `2BT23`, date `2026-10-14`
  (card reads 14/10/2026), price `35`.

## Exact commands

```sh
cd /Users/davidlo/openclaw-skills-incident-repair/nta-betta-picture-processing-v2

# 1) full-image (catalogue) read — 1 live call
/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python -B \
  scripts/vision_review.py --mode catalogue \
  --file tests/fixtures/incident_2bt23/incident-photo.png \
  > docs/incident/label_recognition_evidence/full-read.json

# 2) focused label crop (deterministic helper, no model call)
#    betta_prepare.label_crop(source, docs/incident/label_recognition_evidence/label-crop.png)
#    lineage recorded in label-crop.json

# 3) focused label read on the crop — 1 live call
/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python -B \
  scripts/vision_review.py --mode label \
  --file docs/incident/label_recognition_evidence/label-crop.png \
  > docs/incident/label_recognition_evidence/label-read.json
```

## Label crop parameters (deterministic, `betta_prepare.label_crop`)

| field | value |
|---|---|
| method | `card-band` (confident; not the fallback band) |
| rect_px | `[0, 0, 1512, 477]` (full width, top 17.7% of the frame) |
| source_sha256 | `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9` |
| output_sha256 | `b6cbc02721b2071d01fe7e16f48cea2b043842bec7478d45ac8b5f80f12107f1` |
| output_dimensions | `[1512, 477]` |

The detected card band ends at sample row 88/568 (≈ row 416 px) plus the 2%
safety pad; the previous adapter crop was the full-width top 30% band
(0–806 px), which included far more tank/glare. The new crop contains the whole
card (`TANK ID 2 BT 23`, `DATE PHOTO TAKEN 14/10/2026`, `$35`) and was visually
verified against `label-crop.png`.

## Observed results (verbatim recorded JSON: `full-read.json`, `label-read.json`)

Both calls attested `openai / gpt-5.6-sol` (`execution_attested: true`,
`fallback_used: false`; `routing.actual_provider = openai`,
`routing.actual_model = gpt-5.6-sol`).

### Full-image catalogue read (`full-read.json`)

| field | returned value |
|---|---|
| tank_id | `2BT23` (tank_confidence 0.93) |
| photo_date | `2026-04-10` (date_confidence **0.76**) |
| one_fish_visible | true |
| fish_name / tail_type / sex | `Pastel Pink` / `Halfmoon` / `Male` |
| uncertainty_reasons | handwritten date slightly ambiguous; tail not fully flared; sex not confidently supported |

**Observed model limitation:** the full-frame read got the tank right
(`2BT23`, 0.93) but misread the handwritten date `14/10/2026` as `2026-04-10`
(0.76). Its date confidence is below the pipeline's 0.90 gate, so this read
would be flagged uncertain — but the value itself is wrong and must never be
trusted alone.

### Focused label-crop read (`label-read.json`, improved contract)

| field | returned value |
|---|---|
| tank_id | `2BT23` (tank_confidence **0.99**) |
| photo_date | `14/10/2026` (date_confidence **0.96**) → normalised `2026-10-14` |
| visible_price | `35` (new strict contract field; model reasons: "Price is clearly written as $35 on the physical card.") |
| reasons | tank clearly 2 BT 23; AU day/month/year date 14/10/2026; price $35 |

## Assessment against the pinned comparator

- Focused read: confident, correct — tank `2BT23`, date `2026-10-14`, price `35`
  (matches the documented expectation exactly).
- Full read: confident on tank (0.93) but **not** confident on date (0.76 < 0.90
  gate). Feeding the pipeline's gated reads to
  `label_identity.compare_reads(...)` therefore yields `INCOMPLETE` ("full read
  is not confident"), i.e. quarantine/one bounded re-evaluation — never an
  accepted wrong date. If the low date confidence were ignored (both sides
  treated as confident), the comparator yields `DISAGREE` with
  `date mismatch: full=2026-04-10 label-crop=2026-10-14`, again with no
  accepted identity (`tank` and `date` are `None` for anything but `AGREE`).
- Critically, the incident's failure mode (accepting a hallucinated `5BT43`)
  cannot pass this contract: a wrong high-confidence tank on either side makes
  the comparator `DISAGREE` (see `test_wrong_high_confidence_full_read_disagrees_and_never_picks_a_side`).

## Caveats

- Single-sample evaluation (n=1 photo, 1 call per mode); no test-retest
  statistics were collected to stay inside the cost budget.
- The model sees the crop only; the crop is deterministic for this fixture but
  its detection thresholds were tuned on available frames (see
  `betta_prepare.LABEL_*` constants and the fallback band).
- `usage` reports no token counts for these calls (`token_usage_reported: false`).
