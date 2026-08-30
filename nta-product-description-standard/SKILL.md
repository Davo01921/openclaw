---
name: "nta-product-description-standard"
version: "1.0"
description: "Create, rewrite, validate and QA Nano Tanks Australia Shopify product descriptions using the mandatory NTA HTML structure, with category-specific rules for livestock, aquarium plants and dry goods."
---

# NTA Product Description Standard — v1.0

## Purpose

This skill is the canonical product-description standard for Nano Tanks Australia.

Use it whenever creating, rewriting, correcting, reviewing or bulk-updating Shopify product descriptions.

The objective is to ensure:

- all NTA product pages use the same visual structure;
- descriptions remain appropriate to the actual product type;
- useful aquarium-specific information is prioritised over generic marketing copy;
- factual claims are verified rather than guessed;
- livestock, plants and dry goods do not inherit inappropriate sections from one another;
- descriptions remain practical, customer-focused and recognisably NTA;
- Shopify HTML remains clean and consistent.

This skill applies to:

1. Livestock
2. Aquarium plants
3. Dry goods

Do not use a generic one-size-fits-all description.

## Single source of truth

This file is the canonical source for NTA product-description rules.

Other OpenClaw/Fred skills and workflows must reference this skill rather than copying its description templates, QA rules or factual standards into their own files.

When the standard changes, update this file. Do not maintain parallel copies elsewhere.

# 1. Core operating principle

Every description must answer:

1. What is this?
2. Why would someone choose it?
3. Is it suitable for their aquarium?
4. What must they know before buying?
5. How should it be cared for, planted, installed or used?
6. What makes this particular product useful?
7. What practical advice can NTA add?

The product category determines the factual fields and wording.

The visual HTML architecture remains consistent.

# 2. Mandatory classification

Before generating a description, classify the product.

Use:

```text
LIVESTOCK
├── Fish
├── Shrimp
├── Snails
├── Crayfish / Crabs
└── Other aquatic livestock

PLANTS
├── Stem
├── Rosette
├── Rhizome
├── Carpet
├── Moss
├── Floating
├── Tissue Culture
└── Other aquatic plant

DRY GOODS
├── Equipment
├── Food
├── Water Treatment
├── Aquascaping
├── Consumables
├── Medication
├── Spare Parts
└── Other dry goods
```

Do not proceed until the primary category is known.

If the category is uncertain, infer it from:

1. Shopify product type
2. Shopify category
3. Tags
4. Vendor
5. Product title
6. Existing product information

Never classify based solely on a single keyword if other product data contradicts it.

# 3. Mandatory HTML wrapper

Every completed description must use:

```html
<div class="nta-product">
...
</div>
```

The product title must use:

```html
<h2 class="nta-title">PRODUCT NAME</h2>
```

The introduction must use:

```html
<p class="nta-tagline">...</p>
```

Standard content sections use:

```html
<div class="nta-box">
<h3>SECTION TITLE</h3>
...
</div>
```

Important advice or warnings may use:

```html
<div class="nta-box nta-warning">
...
</div>
```

NTA-specific practical advice uses:

```html
<div class="nta-highlight">
<strong>NTA Insight:</strong><br>
...
</div>
```

Do not introduce alternative CSS classes unless authorised.

# 4. Global writing standard

## Tone

Write as a specialist aquarium retailer helping a customer make a sensible purchase.

The tone should be knowledgeable, clear, practical, approachable, confident where evidence supports the claim, cautious where information varies, and free from exaggerated sales language.

Avoid generic filler such as:

- "Whether you're a beginner or seasoned aquarist..."
- "Take your aquarium to the next level..."
- "A must-have for every aquarium..."
- "Transform your aquatic paradise..."
- "Perfect for any aquarium..."

Use specific reasons instead.

# 5. Accuracy and evidence rules

Never invent:

- scientific names;
- adult sizes;
- water parameters;
- tank-size recommendations;
- compatibility;
- ingredients;
- dosage;
- wattage;
- voltage;
- dimensions;
- flow rates;
- manufacturer specifications;
- included components;
- warranty;
- replacement-part compatibility;
- breeder information;
- origin;
- growth rates;
- CO₂ requirements;
- product capacity.

Use the strongest available source.

Preferred source hierarchy:

```text
1. Verified manufacturer specification
2. Existing trusted NTA product data
3. Supplier documentation
4. Authoritative aquarium reference
5. Established specialist consensus
6. Existing listing only where no stronger source exists
```

Existing Shopify descriptions are not automatically factual merely because they already exist.

If conflicting information exists, investigate before choosing a value.

If a fact cannot reasonably be verified, omit it, use qualified wording, or flag it for human review.

Never fill a missing field simply to complete the template.

# 6. Units and language

Use Australian English.

Use cm, L, °C, mm, W and V.

Use metric measurements unless a manufacturer specification is only meaningfully expressed otherwise.

Scientific names must be italicised:

```html
<em>Poecilia reticulata</em>
```

# 7. Product title rules

The displayed title should match the approved Shopify customer-facing product name.

Do not silently rename a product.

Correct obvious formatting issues only where authorised.

For livestock varieties, preserve relevant strain names.

For plants, include the accepted scientific name where appropriate.

For dry goods, retain model names and sizes where those identify the actual product.

# 8. Tagline rules

The tagline should normally contain 2–4 sentences.

It should explain what the product is, its strongest visual or practical characteristic, and where or why it is useful.

Do not repeat the product title several times, stuff SEO keywords, or make unsupported claims.

# 9. LIVESTOCK TEMPLATE

Use this structure for fish, shrimp, snails and other live animals.

```html
<div class="nta-product">

<h2 class="nta-title">PRODUCT NAME</h2>

<p class="nta-tagline">INTRODUCTION</p>

<div class="nta-box">
<h3>Quick Facts</h3>
<ul>
QUICK FACTS
</ul>
</div>

<div class="nta-box">
<h3>Is this for you?</h3>
PERFECT IF / CONSIDER SOMETHING ELSE
</div>

<div class="nta-box">
<h3>Why choose PRODUCT NAME?</h3>
PRODUCT-SPECIFIC REASONS
</div>

<div class="nta-box">
<h3>Key Benefits</h3>
<ul>
KEY BENEFITS
</ul>
</div>

<div class="nta-box">
<h3>Care &amp; Specifications</h3>
<ul>
CARE DATA
</ul>
</div>

<div class="nta-box">
<h3>What will you receive?</h3>
RECEIVE DETAILS
</div>

<div class="nta-box nta-warning">
<h3>Acclimation &amp; Introduction</h3>
ACCLIMATION STEPS
</div>

<div class="nta-box">
<h3>Ongoing Care</h3>
ONGOING CARE
</div>

<div class="nta-box">
<h3>Pairs perfectly with</h3>
<ul>
RELEVANT COMPLEMENTARY PRODUCTS
</ul>
</div>

<div class="nta-highlight">
<strong>NTA Insight:</strong><br>
PRODUCT-SPECIFIC PRACTICAL ADVICE
</div>

<div class="nta-box">
<h3>Before You Buy</h3>
PRE-PURCHASE CHECKS
</div>

<div class="nta-box">
<h3>FAQ</h3>
PRODUCT-SPECIFIC FAQ
</div>

</div>
```

# 10. Livestock Quick Facts

Use relevant fields such as:

```html
<li><strong>Scientific name:</strong> <em>...</em></li>
<li><strong>Common name:</strong> ...</li>
<li><strong>Variety / Strain:</strong> ...</li>
<li><strong>Type:</strong> ...</li>
<li><strong>Adult size:</strong> ...</li>
<li><strong>Temperament:</strong> ...</li>
<li><strong>Temperature:</strong> ...</li>
<li><strong>pH:</strong> ...</li>
<li><strong>GH:</strong> ...</li>
<li><strong>KH:</strong> ...</li>
<li><strong>Diet:</strong> ...</li>
<li><strong>Tank zone:</strong> ...</li>
<li><strong>Social needs:</strong> ...</li>
<li><strong>Difficulty:</strong> ...</li>
```

Only include fields that add useful information.

Do not use `Brand:` for ordinary livestock.

If breeder or supplier identity is genuinely customer-relevant, use:

```html
<li><strong>Breeder / Supplier:</strong> ...</li>
```

# 11. Livestock suitability section

Use:

```html
<p><strong>✔️ Perfect if:</strong></p>
<ul>
...
</ul>

<p><strong>❌ Consider something else if:</strong></p>
<ul>
...
</ul>
```

Make this product-specific.

Do not repeat identical generic bullets across hundreds of products unless genuinely applicable.

Examples of issues to mention where relevant include minimum group size, aggression, fin nipping, adult size, predatory behaviour, shrimp compatibility, jumping, burrowing, plant damage, territorial behaviour, water hardness, mature tank requirement, breeding rate and special feeding requirements.

Be willing to tell the customer that a product may not suit them.

# 12. Livestock care and specifications

Include useful verified information such as adult size, temperature, pH, hardness, diet, social group, minimum sensible aquarium size where defensible, compatibility, behaviour and breeding considerations where relevant.

Do not confuse sale size and adult size.

If Shopify contains a sale-size variant, identify it separately.

```html
<li><strong>Approximate sale size:</strong> 3 cm</li>
<li><strong>Typical adult size:</strong> 5 cm</li>
```

# 13. Livestock fulfilment and conditioning

NTA livestock should reflect actual NTA handling practices where applicable.

Do not imply livestock is simply picked and shipped immediately like dry goods.

Where appropriate, wording may acknowledge observation, conditioning, suitability checks and NTA's established livestock handling process.

Do not promise guaranteed health outcomes or invent quarantine treatments.

If referring to NTA policies, use the current authorised policy rather than embedding old policy wording permanently into the product description.

# 14. Livestock "What will you receive?"

Use livestock-appropriate wording.

```html
<ul>
<li>The selected livestock variant.</li>
<li>Livestock packed appropriately for the selected fulfilment method.</li>
<li>The quantity shown on the selected variant.</li>
</ul>
```

Do not say "what's included in the box", "manufacturer components" or "replacement parts" for livestock.

# 15. Livestock NTA Insight

This should contain practical advice that a competent aquarium retailer would genuinely give.

Examples include considering adult size rather than sale size, rapid livebearer reproduction, dense moss improving shrimplet survival, proper schooling numbers, colour response under particular conditions, or mineral requirements for snails.

Do not make the NTA Insight generic if product-specific advice is available.

# 16. Livestock FAQ

FAQ questions must be relevant to the exact species, strain or livestock type.

Good examples:

- How large does it grow?
- How many should I keep?
- Is it peaceful?
- Can it live with shrimp?
- Will it eat plants?
- Will it breed?
- What does this strain name mean?
- What should I feed it?
- Does it need hard water?
- Is it suitable for beginners?

Do not ask livestock questions such as:

- What does this product do?
- Is this the right model?
- Is it easy to install?
- What comes in the box?
- Are replacement parts available?

There is no mandatory FAQ count. Use only useful questions. A typical range is 4–8 questions, with more only where genuinely useful.

# 17. PLANT TEMPLATE

```html
<div class="nta-product">

<h2 class="nta-title">COMMON NAME (<em>SCIENTIFIC NAME</em>)</h2>

<p class="nta-tagline">INTRODUCTION</p>

<div class="nta-box">
<h3>Quick Facts</h3>
<ul>
QUICK FACTS
</ul>
</div>

<div class="nta-box">
<h3>Is this for you?</h3>
SUITABILITY
</div>

<div class="nta-box">
<h3>Why choose PLANT NAME?</h3>
REASONS
</div>

<div class="nta-box">
<h3>Key Benefits</h3>
<ul>
BENEFITS
</ul>
</div>

<div class="nta-box">
<h3>Plant Details &amp; Specifications</h3>
<ul>
DETAILS
</ul>
</div>

<div class="nta-box">
<h3>What will you receive?</h3>
RECEIVE DETAILS
</div>

<div class="nta-box nta-warning">
<h3>Planting &amp; Setup</h3>
PLANTING
</div>

<div class="nta-box">
<h3>Maintenance &amp; Trimming</h3>
MAINTENANCE
</div>

<div class="nta-box">
<h3>Pairs perfectly with</h3>
<ul>
RELATED ITEMS
</ul>
</div>

<div class="nta-highlight">
<strong>NTA Insight:</strong><br>
PRACTICAL ADVICE
</div>

<div class="nta-box">
<h3>Before You Buy</h3>
PLANT-SPECIFIC EXPECTATIONS
</div>

<div class="nta-box">
<h3>FAQ</h3>
FAQ
</div>

</div>
```

# 18. Plant Quick Facts

Use relevant fields:

```html
<li><strong>Scientific name:</strong> <em>...</em></li>
<li><strong>Common name:</strong> ...</li>
<li><strong>Plant type:</strong> ...</li>
<li><strong>Placement:</strong> ...</li>
<li><strong>Growth rate:</strong> ...</li>
<li><strong>Typical height:</strong> ...</li>
<li><strong>Light:</strong> ...</li>
<li><strong>CO₂:</strong> ...</li>
<li><strong>Difficulty:</strong> ...</li>
<li><strong>Temperature:</strong> ...</li>
```

Optional relevant fields include pH, propagation method, substrate requirements, tissue-culture format, origin, colour and growth habit.

# 19. Plant-specific truth rules

Clearly distinguish where relevant between emersed appearance, submerged appearance, mature appearance and sale appearance.

Do not imply a newly supplied plant will instantly look like an established aquascape specimen.

Where relevant explain transition melt, emersed-to-submerged leaf change, trimming requirements, replanting stems, rhizome positioning, carpeting requirements, CO₂ impact, lighting impact, nutrient impact and colour response.

Do not guarantee red colour merely because a plant can become red under ideal conditions.

Use qualified wording such as "Colour intensity generally improves with stronger lighting, appropriate nutrition and CO₂" when evidence supports it.

# 20. Tissue Culture rule

If the product is tissue culture, ensure the description makes this clear.

Include useful instructions such as removing the plant from the cup, rinsing culture gel, dividing into small portions and planting appropriately.

Do not describe tissue culture as automatically superior in every situation.

Where applicable, explain that tissue culture typically provides clean laboratory-propagated plant material.

# 21. Plant "Before You Buy"

Address relevant expectations such as supplied size variation, submerged leaf changes, colour dependence on growing conditions, transition melt, CO₂ expectations, growth-rate variation and living-product variability.

Photos may show mature submerged growth.

Do not include replacement parts, installation wiring or model compatibility.

# 22. Plant FAQ

Useful examples include:

- Does it need CO₂?
- How much light does it need?
- How tall does it grow?
- Where should I plant it?
- How fast does it grow?
- Can it grow without substrate?
- Can it be attached to rock or wood?
- Why do the leaves look different after planting?
- How do I propagate it?
- Is it suitable for beginners?
- Will shrimp use it?
- Is it tissue culture?

Use only questions relevant to that particular plant.

# 23. DRY GOODS TEMPLATE

```html
<div class="nta-product">

<h2 class="nta-title">PRODUCT NAME</h2>

<p class="nta-tagline">INTRODUCTION</p>

<div class="nta-box">
<h3>Quick Facts</h3>
<ul>
QUICK FACTS
</ul>
</div>

<div class="nta-box">
<h3>Is this for you?</h3>
SUITABILITY
</div>

<div class="nta-box">
<h3>Why choose PRODUCT NAME?</h3>
REASONS
</div>

<div class="nta-box">
<h3>Key Benefits</h3>
<ul>
BENEFITS
</ul>
</div>

<div class="nta-box">
<h3>Specifications</h3>
<ul>
SPECIFICATIONS
</ul>
</div>

<div class="nta-box">
<h3>What's included?</h3>
INCLUSIONS
</div>

<div class="nta-box nta-warning">
<h3>Setup &amp; Use</h3>
SETUP
</div>

<div class="nta-box">
<h3>Maintenance</h3>
MAINTENANCE
</div>

<div class="nta-box">
<h3>Pairs perfectly with</h3>
<ul>
RELATED PRODUCTS
</ul>
</div>

<div class="nta-highlight">
<strong>NTA Insight:</strong><br>
PRACTICAL ADVICE
</div>

<div class="nta-box">
<h3>Before You Buy</h3>
COMPATIBILITY AND PREPURCHASE INFORMATION
</div>

<div class="nta-box">
<h3>FAQ</h3>
FAQ
</div>

</div>
```

# 24. Dry Goods Quick Facts

Use relevant verified fields such as:

```html
<li><strong>Brand:</strong> ...</li>
<li><strong>Product type:</strong> ...</li>
<li><strong>Model:</strong> ...</li>
<li><strong>Size / Capacity:</strong> ...</li>
<li><strong>Suitable for:</strong> ...</li>
<li><strong>Freshwater / Marine:</strong> ...</li>
```

Additional fields may include dimensions, wattage, voltage, flow rate, cable length, pipe size, media volume, quantity, dosage, food pellet size, ingredient information, manufacturer code and compatibility.

Do not add irrelevant fields simply because the template supports them.

# 25. Dry Goods specifications

Manufacturer specifications should be preserved accurately.

Do not convert approximate marketing statements into precise technical claims.

If manufacturer revisions can alter specifications, use a note only where relevant.

Do not automatically add "Specifications may vary by manufacturer revision" to every product.

# 26. What's included

State actual known inclusions.

Never assume accessories are included based on promotional images.

If uncertain, verify before stating the inclusion.

Photographed accessories are not evidence of inclusion.

# 27. Setup & Use

The setup section should be specific to the product type.

Equipment may cover placement, electrical safety, priming, connection and flow adjustment.

Food may cover feeding amount, frequency and removing uneaten food where appropriate.

Water treatment may cover dosage, water volume, timing and warnings.

Aquascaping products may cover rinsing, preparation, placement, curing or soaking where applicable.

Do not generate generic installation instructions for products that require none.

# 28. Dry Goods "Before You Buy"

Use where relevant for physical dimensions, aquarium volume, inlet/outlet size, hose compatibility, voltage, power requirement, mounting clearance, glass thickness, model compatibility, replacement-part availability and consumable requirements.

This is the correct category for wording about installation, models, manufacturer revision and replacement parts.

Do not copy these concepts into livestock or plant listings.

# 29. FAQ quality rule

FAQ content is generated after the main description.

The system must ask:

```text
What would a real customer deciding whether to buy this exact product reasonably want to know?
```

Use those questions.

Do not generate filler to achieve an arbitrary FAQ count.

Every FAQ must relate to the exact product or product class, contain useful information, avoid repetition, avoid contradictions and avoid unsupported claims.

Use:

```html
<details><summary>QUESTION</summary><p>ANSWER</p></details>
```

# 30. "Pairs perfectly with" standard

This section should recommend categories or genuinely compatible complementary products.

Examples:

Livestock: suitable food, test kit, water conditioner, plants, moss, caves or mineral supplement where appropriate.

Plants: aquasoil, fertiliser, CO₂ equipment, planting tweezers, suitable light or root tabs.

Dry goods: replacement media, tubing, fittings, consumables or compatible accessories.

Do not recommend random products simply to increase basket size.

Compatibility comes before upselling.

# 31. NTA Insight standard

The NTA Insight is mandatory unless no meaningful insight can responsibly be provided.

It should add information beyond the manufacturer's description.

Prioritise practical aquarium experience, purchasing considerations, common customer mistakes, setup tips, long-term care, compatibility and realistic expectations.

Do not fabricate claims such as "We use this every day at NTA" unless verified.

If NTA use is verified, practical first-hand wording is encouraged.

# 32. Customer safety and responsible selling

Do not promote unsuitable combinations merely because they may increase sales.

Descriptions should help prevent incompatible livestock purchases, inadequate aquarium sizing, inappropriate schooling numbers, poor water-parameter matching, incorrect equipment sizing, unsafe electrical use, incorrect medication or chemical dosing and unrealistic plant expectations.

Commercial persuasion does not override responsible aquarium advice.

# 33. SEO standard

Product descriptions should naturally contain the product name, common name, scientific name where applicable, important product type and relevant aquarium application.

Do not keyword stuff, repeat titles unnaturally, generate SEO filler or create fake FAQ questions solely for search engines.

Readable product information takes priority.

# 34. Existing-description rewrite rule

When rewriting an existing product:

1. Preserve verified useful facts.
2. Remove unsupported claims.
3. Correct obvious category bleed.
4. Rebuild into the NTA HTML template.
5. Preserve material product-specific information.
6. Do not replace good existing copy simply for stylistic uniformity.
7. Improve weak sections rather than flattening all listings into identical wording.

# 35. Generic-template bleed detection

Before approval, scan for terms that may be inappropriate to the category.

## Livestock warning terms

Flag manufacturer revision, replacement parts, installation, model compatibility, included in the box, electrical, wattage, voltage and assembly unless legitimately relevant.

## Plant warning terms

Flag manufacturer revision, replacement parts, model, installation, warranty and electrical unless legitimately relevant.

## Dry goods warning terms

Flag inappropriate biological language such as adult size, schooling requirement, temperament, breeding behaviour and submerged leaf form unless genuinely relevant.

# 36. Duplication QA

Descriptions should not reuse entire paragraphs across unrelated products.

Generic framework reuse is allowed.

Product-specific copy must remain product-specific.

Flag identical taglines, identical "Why choose" paragraphs, identical NTA Insights, identical FAQs and irrelevant copied specifications.

# 37. HTML QA

Before sending to Shopify verify:

- one opening `<div class="nta-product">`;
- one matching closing `</div>`;
- valid heading hierarchy;
- all `<ul>` and `<ol>` elements close correctly;
- all `<li>` elements close correctly;
- all `<details>` elements close correctly;
- scientific names use `<em>`;
- no Markdown exists inside final HTML;
- no code fences are written into Shopify;
- no duplicate title heading;
- no malformed entities;
- no accidental editor comments.

# 38. Content QA checklist

A description passes only if all applicable checks pass.

```text
[ ] Product category correctly identified
[ ] Correct category template used
[ ] Product title correct
[ ] Tagline is product-specific
[ ] Scientific name verified where applicable
[ ] Key factual claims verified
[ ] Sale size not confused with adult size
[ ] Water parameters sensible and verified where applicable
[ ] Compatibility discussed where relevant
[ ] Plant growth expectations explained where relevant
[ ] Manufacturer specifications verified where relevant
[ ] What's included is verified
[ ] Setup/acclimation/planting instructions fit category
[ ] NTA Insight adds genuine value
[ ] Before You Buy is category-specific
[ ] FAQ contains useful product-specific questions
[ ] No generic-template bleed
[ ] No obvious AI filler
[ ] HTML validates
```

# 39. Confidence check

Before publishing assign an internal confidence level:

```text
HIGH
Core factual data is verified and category fit is clear.

MEDIUM
Description is substantially reliable but one or more non-critical facts are qualified or omitted.

LOW
Important product identity, specification, livestock care or compatibility information is uncertain.
```

LOW confidence descriptions must not be automatically published. They require review or additional research.

# 40. Publish behaviour

When authorised to update Shopify:

```text
1. Read current Shopify product data.
2. Determine product category.
3. Gather existing useful facts.
4. Verify missing critical information.
5. Generate description.
6. Run factual QA.
7. Run category QA.
8. Run HTML QA.
9. Compare against current product to ensure useful information was not lost.
10. Write the description to Shopify.
11. Re-read the saved Shopify description.
12. Confirm the saved output matches the generated output.
```

Do not treat a successful API response as proof that the correct content was saved.

Always verify after write.

# 41. Bulk processing

For bulk catalog work, process products independently.

Do not assume the next product has the same species, size, compatibility, manufacturer specifications, variant structure or care requirements.

Batching may optimise retrieval and API use, but must not reduce factual accuracy.

If several products share a verified manufacturer family, shared specifications may be reused only where the exact model supports them.

# 42. Human-review triggers

Stop automatic publishing and request review when:

- product identity is ambiguous;
- scientific name cannot be established;
- two sources materially disagree;
- product title appears incorrect;
- livestock identity is questionable;
- adult size differs significantly between credible sources;
- medication instructions conflict;
- electrical specification is uncertain;
- variant selection materially changes specifications;
- included components cannot be verified and are purchase-critical;
- existing Shopify information appears factually dangerous;
- a claim may create customer safety or animal-welfare risk.

# 43. Final quality principle

Consistency means:

```text
same NTA structure
+
same quality threshold
+
same tone
```

It does not mean:

```text
same words for every product
```

Every product description should look like it belongs to Nano Tanks Australia while still sounding like it was written specifically for that product.

The description should be useful enough that a customer can make a better purchasing decision after reading it.

When forced to choose between more content and more accurate content, choose accuracy.

When forced to choose between more sales language and better aquarium advice, choose better aquarium advice.
