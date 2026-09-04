# Betta image standard

## Hero target

The approved visual reference is a premium square catalogue portrait: one large, clearly readable Betta on a clean near-black background with a compact bottom-left tank/date label.

Produce a 2048 × 2048 PNG with:

- the fish occupying most of the useful canvas while leaving room around every fin;
- a natural side-profile catalogue presentation;
- clean subject separation and no tank borders, neighbouring tanks, physical cards, glare bands, reflections, or avoidable debris;
- balanced exposure, realistic clarity, strong but believable colour, and natural texture;
- one dark label block at bottom-left with the normalized tank ID and `PHOTO DATE: D/M/YYYY`;
- no duplicated, clipped, ghosted, malformed, or overlapping label text.

Controlled image editing may isolate the fish, improve presentation, enlarge it, and produce a plausible display posture or fin spread. The output is a catalogue representation, not a claim that the source captured the identical pose.

## Identity boundary

Preserve the source fish's stable identifying characteristics:

- head/body relationship and credible body proportions;
- distinctive scale layout and unique markings;
- colour distribution by body region;
- apparent tail type and fin attachment points;
- visible damage or unusual traits when identity-relevant.

Reject a candidate that substitutes a generic fish, changes the tail type, invents identity-defining markings, moves major colour regions, creates implausible anatomy, removes an identity-relevant trait, or presents hallucinated micro-detail as documentary evidence.

Pose, fin spread, crop, lighting, background, and display scale may differ when the edited result remains anatomically plausible and recognizably the same individual.

## Original reference

Use the complete original attachment as Shopify Image 2. Preserve its exact bytes, dimensions, orientation, framing, aquarium context, tank/date card, metadata, and SHA-256. Do not crop, straighten, resize, pad, recompress, colour-correct, sharpen, relabel, convert, or otherwise derive a replacement reference. The archive copy may be renamed after verified Shopify read-back, but its bytes and hash must remain unchanged.

## QA evidence

Compare source, hero, and reference at useful/full resolution. Record PASS/FAIL for:

- same individual identity;
- stable body proportions and anatomical integrity;
- stable scale-pattern and unique markings;
- faithful regional colour distribution;
- plausible tail type, fins, pose, and fin spread;
- complete framing;
- realistic texture without severe blur, halos, plastic texture, noise amplification, or deceptive invented detail;
- clean professional hero composition;
- correct single-rendered label;
- exact byte/hash identity between the source and Image 2 reference record.

Any uncertainty about identity receives one focused cheap retry, then the configured reasoning review. Unresolved identity is `BLOCKED_IMAGE_IDENTITY`.
