---
name: "nta-customer-service"
version: "0.1"
description: "Assess NTA customer complaints using evidence, responsibility classification, ACL-aware reasoning, proportionate remedies, and clear customer communication."
---

# NTA Customer Service

Use this skill when David asks to assess, respond to, document, or resolve an NTA customer-service issue, including livestock health/DOA concerns, refunds, replacements, shipping disputes, product-description errors, missing or incorrect items, pickup/shipping misunderstandings, and goodwill requests.

The objective is not to automatically side with NTA or the customer. Establish the facts, identify what can and cannot be proven, classify responsibility, test the proposed position from the customer's side, and choose the smallest fair remedy that actually resolves the issue.

## Required workflow

1. Gather evidence before concluding:
   - customer messages, photos and videos
   - Shopify order, fulfilment and refund records when relevant
   - product listing/policy wording that applied at purchase
   - shipping/tracking evidence when relevant
   - known store observations, conditioning history, or in-person inspection context
2. Separate confirmed facts from assumptions and disputed claims.
3. Classify responsibility as one of:
   - `NTA`
   - `CARRIER`
   - `CUSTOMER`
   - `SHARED`
   - `UNDETERMINED`
4. Check the relevant NTA policy, but never treat store policy as overriding Australian Consumer Law.
5. Identify any material post-sale variables, including customer husbandry, transport handling, delayed pickup, acclimation, storage, feeding, water quality, or failure to follow documented instructions. Do not assert causation unless the evidence supports it.
6. Decide whether more evidence is needed before a remedy. Ask only for evidence that could materially change the decision.
7. Choose a proportionate remedy:
   - advice / monitoring only
   - correction or clarification
   - store credit
   - partial refund
   - replacement
   - full refund
   - carrier escalation
   - no remedy, with a clear factual explanation
8. Run the devil's-advocate test: state the strongest reasonable argument against NTA's preferred position. If it exposes a factual, legal, or fairness weakness, revise the recommendation.
9. Give a confidence rating: `LOW`, `MODERATE`, `MODERATE-HIGH`, or `HIGH`.
10. Draft the customer response only after the decision logic is complete.

## Communication standard

- Calm, concise, respectful and factual.
- Acknowledge genuine concerns without admitting liability prematurely.
- Do not accuse the customer of causing a problem when causation is uncertain.
- Do not use defensive wording such as "you chose it, so it is your problem."
- When an in-person customer had a meaningful opportunity to inspect an item, that is relevant evidence, not a waiver of consumer rights.
- Explain the next step and what evidence would change the outcome.
- Avoid long policy dumps unless the customer is actively disputing the decision.

## Livestock-specific rule

For a live-animal health complaint, distinguish visible symptoms from diagnosis. Photos and videos may support observations such as swelling, posture, external lesions, raised scales, colour change, respiration, or swimming behaviour, but do not overstate a diagnosis from imagery alone.

Where post-sale husbandry could materially affect the outcome, record it as a contributing variable and request relevant parameters only when needed. For fish this may include temperature, ammonia, nitrite, nitrate, acclimation method, time in transport water, feeding, tank maturity, tankmates, and observed waste/behaviour.

Do not offer a refund or replacement merely because the customer asks for one. Equally, do not deny a remedy merely because the customer selected the animal in person.

## ACL safeguard

NTA policy is an operating guide, not a substitute for Australian Consumer Law. If a case may involve a consumer guarantee failure, misleading product representation, or a disputed high-value remedy, verify the current ACL/ACCC position before making a legal claim. Do not tell a customer that store policy removes statutory rights.

## Emotional / after-hours safeguard

If David is frustrated, angry, or responding after hours to a difficult customer, analyse the case first and draft a neutral response. Do not send or recommend an emotionally reactive message. Where there is no operational urgency, recommend waiting until normal business hours before sending.

## Data and repository safety

Customer names, emails, phone numbers, addresses, order numbers, private messages, payment data, and other identifying customer information must not be committed to this repository. Case examples in GitHub must be anonymised and stripped of identifiers.

## Output contract

Return, in this order:

1. `Facts`
2. `Responsibility`
3. `Key evidence / missing evidence`
4. `ACL / policy considerations`
5. `Devil's-advocate test`
6. `Recommended remedy`
7. `Confidence`
8. `Customer reply`

For simple WhatsApp/SMS cases, David may ask for only the final reply. The internal reasoning steps still apply even when the visible output is short.
