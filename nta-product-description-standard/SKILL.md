---
name: "nta-product-description-standard"
version: "1.1"
description: "Create, rewrite, validate and QA Nano Tanks Australia Shopify product descriptions using the mandatory NTA HTML structure, with category-specific rules for livestock, aquarium plants and dry goods."
---

# NTA Product Description Standard — v1.1

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
├── Aquarium / Tank
├── Aquarium Stand / Cabinet
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

Never invent scientific names, adult sizes, water parameters, tank-size recommendations, compatibility, ingredients, dosage, wattage, voltage, dimensions, flow rates, manufacturer specifications, included components, warranty, replacement-part compatibility, breeder information, origin, growth rates, CO₂ requirements or product capacity.

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

Use Australian English and metric measurements: cm, L, °C, mm, W and V.

Scientific names must be italicised with `<em>`.

# 7. Product title rules

The displayed title should match the approved Shopify customer-facing product name. Do not silently rename a product.

For livestock varieties, preserve relevant strain names. For plants, include the accepted scientific name where appropriate. For dry goods, retain model names and sizes where those identify the actual product.

# 8. Tagline rules

The tagline should normally contain 2–4 sentences and explain what the product is, its strongest visual or practical characteristic, and where or why it is useful.

Do not repeat the product title several times, stuff SEO keywords, or make unsupported claims.

# 9. LIVESTOCK TEMPLATE

Use the standard NTA wrapper and the following sequence:

Title → Tagline → Quick Facts → Is this for you? → Why choose? → Key Benefits → Care & Specifications → What will you receive? → Acclimation & Introduction → Ongoing Care → Pairs perfectly with → NTA Insight → Before You Buy → FAQ.

Livestock Quick Facts may include scientific name, common name, strain, adult size, temperament, temperature, pH, GH/KH, diet, tank zone, social needs and difficulty.

Do not use `Brand:` for ordinary livestock. Use `Breeder / Supplier:` only when genuinely customer-relevant.

The suitability section must use Perfect if / Consider something else if and be product-specific.

Do not confuse sale size and adult size.

Livestock FAQ questions must be species- or strain-specific. Do not use equipment questions such as model compatibility, installation or replacement parts.

# 10. PLANT TEMPLATE

Use the standard NTA wrapper and the following sequence:

Title → Tagline → Quick Facts → Is this for you? → Why choose? → Key Benefits → Plant Details & Specifications → What will you receive? → Planting & Setup → Maintenance & Trimming → Pairs perfectly with → NTA Insight → Before You Buy → FAQ.

Quick Facts may include scientific name, common name, plant type, placement, growth rate, height, light, CO₂, difficulty and temperature.

Clearly distinguish emersed, submerged, mature and sale appearance where relevant. Explain transition melt, trimming, replanting, rhizome positioning, carpeting requirements and colour response where relevant. Do not guarantee colour outcomes.

For tissue culture, explain rinsing gel, dividing portions and planting appropriately.

# 11. DRY GOODS TEMPLATE

Use the standard NTA wrapper and the following sequence:

Title → Tagline → Quick Facts → Is this for you? → Why choose? → Key Benefits → Specifications → What's included? → Setup & Use → Maintenance → Pairs perfectly with → NTA Insight → Before You Buy → FAQ.

Quick Facts may include brand, product type, model, size/capacity, suitable use, freshwater/marine, dimensions, wattage, voltage, flow rate, quantity, dosage, compatibility and manufacturer code where verified.

Only include relevant fields.

# 12. Aquarium / Tank subtype rules

Aquariums are not generic powered equipment. Do not describe a bare aquarium as if it were a filter, pump, heater or electrical appliance.

For aquariums, prioritise:

- exact capacity;
- exact external dimensions where verified;
- exact model;
- whether it is a bare tank or an all-in-one kit;
- verified inclusions such as lid, hood, light, filter, pump, heater or media;
- intended freshwater/marine use only where verified;
- matching stand/cabinet where known;
- fulfilment restrictions or delivery variants where material.

Do not include irrelevant aquarium wording such as:

- confirm voltage;
- prime before switching on;
- check impellers;
- inspect tubing;
- replacement parts;
- manufacturer tank-size ratings;
- head height;

unless the aquarium listing genuinely includes equipment for which that advice is relevant.

For bare glass tanks, Setup & Use should focus on:

1. a level, structurally suitable stand or surface;
2. full support of the exact aquarium footprint;
3. final placement before filling;
4. appropriate filtration, heating and lighting selected for the intended setup;
5. cycling before livestock.

For all-in-one aquarium kits, distinguish clearly between the tank itself and included electrical components.

# 13. Aquarium load and footprint rule

Aquarium descriptions must warn customers that nominal length labels such as `2ft`, `3ft` and `4ft` are not sufficient for compatibility decisions.

Before You Buy must include, where relevant:

- the exact aquarium base footprint;
- a requirement to verify the stand or supporting surface against that footprint;
- a reminder that a filled aquarium weighs materially more than its water capacity alone because glass, substrate, hardscape and equipment add load;
- a warning not to assume every stand with the same nominal foot length is compatible;
- a requirement to match exact model, dimensions and structural suitability.

Do not invent a total filled weight unless verified. Use qualitative wording if the exact weight is unknown.

# 14. Aquarium Stand / Cabinet subtype rules

Aquarium stands and cabinets require exact model and footprint matching.

Prioritise:

- exact matching aquarium model;
- supported footprint dimensions where verified;
- stand dimensions where verified;
- colour/finish;
- flat-pack or assembled status where verified;
- assembly requirement where verified;
- load rating only when verified;
- SKU/model code where useful.

Do not describe a stand using electrical-equipment language. Do not mention voltage, priming, cable routing, impellers, tubing, filtration performance or replacement media.

Setup & Use for stands should focus on:

1. assembling exactly to supplied instructions where assembly is required;
2. placing on a level, structurally suitable floor;
3. confirming all fasteners and panels are secure;
4. ensuring the aquarium footprint is fully supported as intended;
5. rechecking level before filling the aquarium.

Never infer that a generic stand is suitable merely because both products are called `2ft`, `3ft` or `4ft`.

# 15. What's included

State actual known inclusions only.

Never assume accessories are included based on promotional images.

For bare tanks, do not imply a filter, light, heater, stand or accessories are included unless verified.

For aquarium kits, enumerate verified included components.

For stands, do not imply the aquarium itself is included unless explicitly stated.

# 16. Setup & Use

Setup instructions must be specific to the subtype.

Equipment may include placement, electrical safety, priming, connection and flow adjustment.

Food should describe feeding amount/frequency where verified.

Water treatment and medication should use verified dosing and warnings only.

Aquariums and stands must follow their dedicated subtype rules above.

# 17. Pairs perfectly with

Recommend genuinely compatible complementary products or categories.

For aquariums, suitable examples include the exact matching stand, appropriate filtration, lighting, heater where required, conditioner, test kit, substrate and aquascaping materials.

For stands, the exact matching aquarium is the primary recommendation.

Compatibility comes before upselling.

# 18. NTA Insight

The NTA Insight should add genuine practical advice beyond manufacturer copy.

For aquariums, useful insight includes planning around adult livestock needs, exact footprint, load, maintenance access and long-term equipment choices.

For stands, useful insight includes exact model matching and levelling before the tank is filled.

Do not fabricate claims such as `We use this every day at NTA` unless verified.

# 19. FAQ quality rule

Ask what a real customer deciding whether to buy this exact product would reasonably want to know.

There is no mandatory FAQ count.

Aquarium FAQ examples:

- What are the exact dimensions?
- What is the stated capacity?
- Is a lid included?
- Does it include a filter or light?
- Which stand matches this model?
- Can it be used for a planted aquarium?
- Is delivery available for this size?

Stand FAQ examples:

- Which exact aquarium does this stand fit?
- What footprint does it support?
- Does it require assembly?
- Is the aquarium included?
- Can I use it with another aquarium of similar nominal length?

Avoid generic filler such as `What does this product do?` when the answer is obvious from the product itself.

# 20. Generic-template bleed detection

Flag aquarium/tank descriptions containing irrelevant terms such as:

```text
prime before switching on
impeller
head height
filter media load
replacement parts
voltage
cable routing
pump performance
```

unless those terms specifically describe included equipment.

Flag stand descriptions containing:

```text
voltage
power
filter
pump
impeller
tubing
prime
livestock load
head height
```

unless genuinely relevant.

# 21. Duplication QA

Descriptions should not reuse entire paragraphs across unrelated products.

Generic framework reuse is allowed, but product-specific copy must remain product-specific.

Flag identical taglines, identical Why choose paragraphs, identical NTA Insights, identical FAQs or irrelevant copied specifications.

# 22. HTML QA

Before sending to Shopify verify:

- one opening `<div class="nta-product">` and one matching closing `</div>`;
- all standard sections that are relevant use `.nta-box`;
- NTA Insight uses `.nta-highlight`;
- warning sections use `.nta-warning` where appropriate;
- all lists and details tags close correctly;
- no Markdown exists inside final HTML;
- no generic placeholders remain.

# 23. Content QA checklist

A description passes only if all applicable checks pass:

```text
[ ] Product category and subtype correctly identified
[ ] Correct category template used
[ ] Product title correct
[ ] Tagline is product-specific
[ ] Key factual claims verified
[ ] Capacity and dimensions verified where material
[ ] Inclusions verified
[ ] Aquarium footprint/load advice included where relevant
[ ] Stand exact-model compatibility included where relevant
[ ] Setup instructions fit the actual subtype
[ ] NTA Insight adds genuine value
[ ] Before You Buy is category-specific
[ ] FAQ contains useful product-specific questions
[ ] No generic-template bleed
[ ] No obvious AI filler
[ ] HTML validates
```

# 24. Confidence check

Before publishing assign an internal confidence level:

```text
HIGH — Core factual data is verified and category fit is clear.
MEDIUM — Description is substantially reliable but one or more non-critical facts are qualified or omitted.
LOW — Important identity, specification, inclusion, compatibility or safety information is uncertain.
```

LOW confidence descriptions must not be automatically published.

# 25. Publish behaviour

When authorised to update Shopify:

1. Read current Shopify product data.
2. Determine category and subtype.
3. Gather existing useful facts.
4. Verify missing critical information.
5. Generate description.
6. Run factual QA.
7. Run category/subtype QA.
8. Run HTML QA.
9. Compare against current product to ensure useful information was not lost.
10. Write the description to Shopify.
11. Re-read the saved Shopify description.
12. Confirm the saved output matches the generated output.

Do not treat a successful API response as proof that the correct content was saved.

# 26. Bulk processing

Process products independently.

Do not assume the next product has the same size, inclusions, compatibility, variant structure or specifications.

Batching may optimise retrieval and API use, but must not reduce factual accuracy.

# 27. Human-review triggers

Stop automatic publishing and request review when product identity is ambiguous, key specifications conflict, exact compatibility is uncertain, included components cannot be verified and are purchase-critical, electrical or medication information is uncertain, or existing Shopify information appears factually dangerous.

# 28. Final quality principle

Consistency means the same NTA structure, the same quality threshold and the same tone. It does not mean the same words for every product.

When forced to choose between more content and more accurate content, choose accuracy.

When forced to choose between more sales language and better aquarium advice, choose better aquarium advice.
