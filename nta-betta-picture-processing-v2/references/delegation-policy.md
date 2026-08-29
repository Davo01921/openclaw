# Delegation policy

This reference defines the model-routing contract for `betta-picture-processing`.

## Routing hierarchy

| Task | Default route | Escalation |
|---|---|---|
| Discord/file collection | deterministic | none |
| Hashing/ledger | deterministic | none |
| Tank/date OCR-like interpretation | cheap vision | cheap retry → Sol → human |
| Fish description/title | cheap vision | cheap retry if low confidence |
| Sex suggestion | cheap vision | cheap retry → Sol only if needed → human |
| CSV generation/validation | deterministic | none |
| Basic image crop/resize/colour correction | deterministic | image editor only if required |
| Fish/source identity comparison | cheap vision if needed | Sol on unresolved conflict |
| Shopify search/read | deterministic API | Sol only to diagnose conflict |
| Shopify mutation | deterministic API | stop on anomaly |
| Read-back/assertions | deterministic API/code | Sol only to diagnose contradiction |
| Archive | deterministic | none |
| Discord summary | template/utility | none normally |

## Cheap-model prompt discipline

Cheap visual calls must receive the smallest useful context:
- image(s);
- source ID;
- requested schema;
- NTA naming constraints;
- no unrelated conversation history.

Ask for structured JSON only.

Do not ask the cheap model to call Shopify, modify files, decide whether API errors are acceptable, or choose destructive mutations.

## Sol escalation packet

When escalation is required, do not send the whole batch blindly. Build a minimal evidence packet containing:
- batch ID;
- affected source/tank IDs;
- relevant image(s);
- first-pass and retry outputs;
- exact conflicting deterministic facts/API responses;
- allowed decisions;
- prohibited actions.

Sol should answer with:
- diagnosis;
- confidence;
- recommended deterministic next action;
- or `BLOCKED_HUMAN_REQUIRED`.

Sol is an adjudicator, not the routine executor.

## Human escalation

Ask David only when:
- tank/date cannot be established safely;
- two products remain plausible;
- sex is required in title but remains uncertain;
- image identity remains unresolved;
- the correction would require changing a preserved field not previously authorised;
- evidence indicates a potentially destructive mismatch.

## Cost policy

A second cheap pass should normally be cheaper than one Sol call, so retry cheap interpretation before Sol when the uncertainty is visual and non-destructive.

Do not retry indefinitely. Maximum:
- initial cheap visual pass: 1
- focused cheap retry: 1
- Sol escalation: 1
- then human/block unless the deterministic correction itself requires another read-back (read-back is not an AI call).
