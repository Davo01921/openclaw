# Grok Imagine 2.0 Betta hero experiment

Status: **experimental / no automatic Shopify promotion**

## Purpose

Evaluate `grok-imagine-image-2.0` as a lower-cost image-editing backend for NTA Betta catalogue heroes while preserving the existing identity and Shopify safety contract.

The generative model creates the clean fish hero only. Exact tank/date labels must be rendered deterministically after generation. The original source remains Image 2 unchanged.

## Renderer

Use:

```bash
XAI_API_KEY=... python scripts/grok_hero.py \
  --source /path/to/source.jpg \
  --output /path/to/2BT31-grok.png \
  --quality low
```

Default model: `grok-imagine-image-2.0`

The renderer:
- submits the exact source as the image-edit reference;
- requests a square near-black catalogue presentation;
- explicitly forbids generic-fish substitution and invented identity traits;
- normalizes the returned candidate to 2048 × 2048 PNG;
- records source/output SHA-256, provider/model/quality, timestamp and provider usage;
- does **not** mark the image PASS.

## Required QA

Every Grok candidate must run through the existing independent `vision_review.py --mode qa` path against:
1. the saved source;
2. the Grok hero candidate;
3. the unchanged original reference.

All mandatory identity assertions in `image-standard.md` must PASS before the candidate can enter the normal media/write path. A model-generated image never self-approves.

During the experiment, Grok candidate failures should be retained with their evidence rather than overwritten so we can measure failure modes.

## Test protocol

Start with 10 previously completed Bettas with known-good source/hero pairs.

For each source:
1. Generate one Grok 2.0 low-quality 2K candidate.
2. Run independent vision QA.
3. If it fails, generate at most one medium-quality retry.
4. Run independent vision QA again.
5. Record PASS/FAIL and reasons.
6. Do not update Shopify during benchmark mode.

Score:
- same individual identity;
- body/anatomy fidelity;
- scale/marking fidelity;
- regional colour fidelity;
- tail/fin fidelity;
- complete framing;
- realistic texture;
- catalogue composition;
- generation cost;
- retry rate.

## Promotion gate

Do not make Grok the default renderer from a handful of attractive examples. Promote it only after a representative historical test set shows acceptable identity fidelity and a materially better cost/reliability profile than the incumbent path.

Suggested first gate: at least 30 historical Bettas, with zero accepted wrong-identity candidates and a documented review of every QA failure.
