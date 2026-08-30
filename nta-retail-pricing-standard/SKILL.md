---
name: "nta-retail-pricing-standard"
description: "Determine, validate, recommend, update, and verify Nano Tanks Australia retail prices using cost, category margin, market evidence, profitability, and controlled pricing safeguards."
version: "0.1"
---

# NTA Retail Pricing Standard — v0.1

## Purpose

This skill is the standard decision engine for determining retail prices for Nano Tanks Australia (NTA).

Use this skill whenever:

- creating a new Shopify product;
- reviewing an existing retail price;
- supplier cost changes;
- processing supplier orders or invoices;
- importing new products;
- performing catalogue price reviews;
- checking whether an existing product remains commercially viable;
- another workflow needs to determine or validate an NTA retail price.

The objective is not to produce the cheapest price.

The objective is to determine a commercially sensible NTA retail price that:

1. protects profitability;
2. remains defensible against the Australian market;
3. reflects product and operational risk;
4. recognises value customers receive from NTA;
5. maintains sensible retail price architecture; and
6. avoids unnecessary reductions to established profitable prices.

Competitor prices are evidence, not instructions.

## 1. Core Pricing Principle

Determine retail price in this order:

**Product identification → Cost validation → Unit conversion → Category classification → Margin requirement → Margin-derived price → Market validation → Risk/value assessment → Price architecture → Existing-price comparison → Confidence assessment → Final recommendation → Shopify verification**

Never determine price from only one factor.

In particular:

- Do not use cost × arbitrary markup as the sole pricing method.
- Do not automatically copy competitors.
- Do not automatically undercut competitors.
- Do not automatically reduce an existing NTA price because a lower calculated price is possible.
- Do not confuse markup percentage with gross margin percentage.

## 2. Required Inputs

Before determining a retail price, establish as many of the following as reasonably possible:

- Product name
- SKU
- Shopify product/variant ID where applicable
- Vendor/supplier
- Product category
- Supplier purchase cost
- Whether supplier cost includes or excludes GST
- Supplier pack quantity
- NTA retail unit quantity
- Directly attributable inbound costs where relevant
- Current NTA retail price
- Current compare-at price
- Current inventory
- Dropship status
- Australian market evidence
- Product availability/scarcity
- Relevant operational or product risk

Do not invent missing information.

If a material input cannot be established reliably, lower confidence or escalate for review.

## 3. Cost Normalisation

### 3.1 GST

Margin calculations should normally use GST-exclusive values.

Where supplier cost includes Australian GST:

**Ex-GST Cost = GST-Inclusive Cost ÷ 1.10**

Where supplier cost is already ex GST, do not remove GST again.

Customer-facing Australian retail prices should normally be expressed GST-inclusive.

## 4. Pack-to-Unit Conversion

Never assume supplier pack quantity equals Shopify retail quantity.

Determine:

**Unit Purchase Cost = Supplier Pack Cost ÷ Number of NTA Retail Units Produced**

Example:

Supplier invoice:

Cryptocoryne 10-pack  
Cost: $50 ex GST

NTA sells plants individually.

Therefore:

**Unit purchase cost = $50 ÷ 10 = $5**

The pricing engine must price the $5 retail unit, not treat $50 as the cost of one plant.

If pack quantity or retail-unit conversion is unclear:

**DO NOT AUTO-PRICE.**

Request or obtain clarification.

## 5. Landed Cost

Where meaningful:

**NTA Unit Landed Cost = Ex-GST Unit Purchase Cost + Directly Attributable Unit Costs**

Potential attributable costs may include:

- supplier freight;
- import freight;
- unavoidable supplier handling;
- per-product surcharges;
- unavoidable dropship fees;
- other direct acquisition costs.

Do not arbitrarily allocate general overhead to landed cost.

General operating expenses should eventually be considered through contribution analysis rather than fabricated product-level landed costs.

## 6. Dropship Products

Dropship is NOT a pricing category.

Dropship products follow exactly the same pricing methodology as equivalent stocked products.

Classify the product according to what it actually is.

Examples:

Dropship filter → equipment category  
Dropship fish food → food/consumables category  
Dropship aquarium accessory → appropriate accessory category

Dropship status may affect the underlying cost if NTA incurs unavoidable supplier freight, dropship charges, handling charges, or similar costs.

Therefore:

**Fulfilment method does not determine margin target.**

**Actual economic cost may affect profitability.**

## 7. Product Classification

Every product must be assigned to the most appropriate pricing category.

Initial categories:

### Common Livestock

Examples:
- commonly available community fish;
- standard livebearers;
- commonly traded aquarium livestock.

Provisional target gross margin:

**55–65%**

### Premium / Rare Livestock

Examples:
- uncommon varieties;
- difficult-to-source livestock;
- premium strains;
- high-risk or specialist livestock.

Provisional target gross margin:

**60–70%**

### Individual Bettas

Individually photographed/listed Bettas are treated separately from commodity livestock because individual specimen quality, colour, rarity and presentation can materially affect value.

Provisional target gross margin:

**60–70%**

### Shrimp / Specialist Invertebrates

Provisional target gross margin:

**55–70%**

Use strain quality, stability, rarity and market availability as supporting evidence.

### Aquarium Plants

Includes standard potted, loose, bunch, rooted and other conventional aquarium plants unless another category clearly applies.

Provisional target gross margin:

**55–65%**

### Tissue Culture

Provisional target gross margin:

**45–55%**

### Food / Consumables

Examples:

- fish food;
- shrimp food;
- conditioners;
- regularly replaced aquarium consumables.

Provisional target gross margin:

**35–45%**

### Commodity Branded Equipment

Products customers can readily compare across multiple Australian retailers.

Examples may include:

- common filters;
- heaters;
- pumps;
- lighting;
- widely distributed branded equipment.

Provisional target gross margin:

**30–40%**

### Specialist / Niche Equipment

Products with reduced direct comparability, specialist use or limited distribution.

Provisional target gross margin:

**40–50%**

### Low-Cost Accessories

Examples:

- small tools;
- fittings;
- inexpensive accessories;
- low-dollar miscellaneous products.

Provisional target gross margin:

**50–65%**

Minimum dollar gross profit becomes particularly important for this category.

## 8. Category Bleed Check

Do not classify products purely by keywords.

Consider the actual commercial nature of the product.

For example:

A specialist branded aquarium tool should not automatically become "commodity equipment" merely because it has a brand.

A rare but inexpensive fish should not automatically become "common livestock" because the species is normally common.

Where two categories could reasonably apply:

1. identify both;
2. explain which is more appropriate;
3. use the selected category;
4. reduce confidence where classification materially affects the recommendation.

## 9. Gross Margin Calculation

Gross margin is NOT markup.

Use:

**Gross Profit = Ex-GST Selling Price − Unit Landed Cost**

**Gross Margin % = Gross Profit ÷ Ex-GST Selling Price × 100**

To calculate the retail price required for a target margin:

**Required Ex-GST Retail = Unit Landed Cost ÷ (1 − Target Margin)**

Then:

**GST-Inclusive Retail = Required Ex-GST Retail × 1.10**

Example:

Unit landed cost = $10 ex GST  
Target gross margin = 60%

Required ex-GST retail:

$10 ÷ 0.40 = $25

GST-inclusive retail:

$25 × 1.10 = $27.50

$27.50 is the **margin-derived price**, not automatically the final NTA retail price.

## 10. Margin Range

Each category has a target margin range rather than one compulsory percentage.

The engine should determine where within the range the product reasonably belongs.

Factors supporting the upper part of the range may include:

- scarcity;
- mortality risk;
- livestock conditioning;
- inconsistent supplier availability;
- specialist care;
- unusual variety;
- high holding risk;
- individual specimen selection;
- premium presentation;
- limited direct competition;
- strong demonstrated customer willingness to pay.

Factors supporting the lower part may include:

- commodity product;
- extremely strong price transparency;
- high turnover;
- readily available supply;
- strategic traffic-generating product;
- very low handling/risk;
- unusually high dollar gross profit despite lower percentage margin.

Do not convert these factors into arbitrary percentage bonuses unless explicitly defined by a future version of this standard.

## 11. Market Research

Market research validates the NTA price.

It does not determine the price by itself.

Prefer Australian retailers selling:

1. the exact same product;
2. the same brand/model/size;
3. genuinely equivalent livestock strain/grade;
4. genuinely equivalent plant form/size;
5. genuinely comparable substitutes where exact matches are unavailable.

Record where possible:

- competitor;
- product;
- advertised retail;
- product size/quantity;
- stock status;
- sale vs normal price;
- similarity;
- date checked.

Derive where evidence allows:

**Market Low**

**Market Median**

**Market High**

**Sample Size**

## 12. Market Evidence Quality

Rate evidence:

### HIGH

Multiple credible Australian sellers with exact or near-exact product matches.

### MEDIUM

Some exact evidence plus reasonable comparable products.

### LOW

Few matches, questionable equivalence, outdated listings, marketplace sellers, overseas prices or highly variable products.

Low-quality evidence must not drive automatic price changes.

## 13. Market Outliers

Do not blindly include every observed price.

Potential outliers include:

- clearance pricing;
- liquidation;
- obvious pricing errors;
- permanently unavailable listings;
- tiny pack sizes compared with NTA;
- substantially different livestock grade;
- marketplace/private sellers;
- temporary promotional discounts.

Record relevant outliers but do not allow them to distort the normal market range without justification.

## 14. Do Not Automatically Undercut

Never assume NTA should be the cheapest seller.

If market range is:

$24.95  
$27.95  
$29.95  
$32.95

do not automatically recommend $24.90 or $24.95.

Determine the price based on:

- required margin;
- NTA value;
- product risk;
- existing price;
- market position;
- reasonable retail architecture.

NTA may appropriately price near the median, above the median, or occasionally at the high end where evidence supports it.

## 15. Existing Price Protection

An established NTA retail price has informational value.

If an existing product sells at $29.95 and a new mathematical calculation produces $24.95:

**DO NOT AUTOMATICALLY REDUCE THE PRODUCT TO $24.95.**

First determine whether:

- the existing price remains within a defensible market range;
- customers have demonstrated willingness to pay;
- margin is healthy;
- market conditions have materially changed;
- the product has changed;
- NTA's cost structure has changed.

If the existing price remains commercially defensible:

**KEEP THE EXISTING PRICE.**

Price reductions require stronger justification than simply discovering that NTA could theoretically sell the product for less.

## 16. Price Increase Review

Where supplier costs rise, recalculate profitability.

Do not automatically preserve an existing price if it now breaches NTA's acceptable profitability standard.

Determine:

- new landed cost;
- current gross profit;
- current gross margin;
- margin-derived retail;
- current market range;
- recommended new retail.

Material increases should be flagged where confidence is insufficient for automatic action.

## 17. Minimum Dollar Gross Profit

Percentage margin alone is insufficient.

Example:

Cost = $1  
Retail ex GST = $2

Gross margin = 50%

Gross profit = only $1.

Low-dollar products may consume picking, packing, transaction, staffing and handling resources disproportionate to their selling price.

Therefore every pricing assessment should calculate:

**Dollar Gross Profit Per Retail Unit**

Minimum dollar gross-profit thresholds are currently:

**TBD — requires NTA catalogue/order analysis.**

Until thresholds are formally established, unusually low dollar GP should trigger review rather than automatic approval.

## 18. Contribution Economics

Gross margin is the initial pricing standard.

Future versions should progressively incorporate contribution economics.

Potential contribution costs include:

- payment processing;
- packaging;
- picking/handling labour;
- livestock mortality;
- plant losses;
- warranty/DOA exposure;
- shipping subsidy;
- marketplace/platform costs;
- other directly attributable fulfilment expenses.

Do not fabricate contribution costs when reliable data is unavailable.

Gross margin remains the primary calculation until contribution rules are formally adopted.

## 19. Retail Price Architecture

Do not publish unnecessarily awkward mathematical prices.

Convert calculated prices into sensible customer-facing NTA prices.

Potential price points include:

- $4.95
- $5.95
- $7.95
- $9.95
- $12.95
- $14.95
- $15
- $19.95
- $24.95
- $29.95
- $34.95
- $39.95
- $49
- $59
- $69
- $79
- $89
- $99

These are examples, not mandatory price points.

Choose a sensible retail price based on product type and market context.

Never round downward if doing so causes an unacceptable margin without flagging the issue.

## 20. Sale and Compare-at Pricing

Never fabricate a compare-at price.

A compare-at price must represent a legitimate reference price and must not be created merely to make the current retail price appear discounted.

When reviewing Shopify pricing:

Check:

- current price;
- compare-at price;
- whether the comparison remains legitimate;
- whether variants have inconsistent pricing;
- whether stale sale pricing remains active.

If evidence is insufficient to support a compare-at price:

**DO NOT CREATE ONE.**

## 21. Pricing Decision

For each product, produce:

### Product
[NAME]

### SKU
[SKU]

### Category
[CATEGORY]

### Supplier
[SUPPLIER]

### Supplier Cost
[$]

### Supplier Cost GST Basis
[INC GST / EX GST / UNKNOWN]

### Supplier Pack Quantity
[#]

### NTA Retail Units Produced
[#]

### Unit Purchase Cost Ex GST
[$]

### Additional Attributable Cost
[$]

### Unit Landed Cost
[$]

### Current NTA Retail
[$]

### Current Gross Profit
[$]

### Current Gross Margin
[%]

### Target Margin Range
[%–%]

### Margin-Derived Retail
[$ INC GST]

### Australian Market
Low: [$]  
Median: [$]  
High: [$]  
Sample: [#]

### Market Evidence Quality
[HIGH / MEDIUM / LOW]

### Risk / Value Factors
[FACTORS]

### Recommended NTA Retail
[$]

### Recommended Gross Profit
[$]

### Recommended Gross Margin
[%]

### Price Movement
[$ AND %]

### Confidence
[HIGH / MEDIUM / LOW]

### Action
[AUTO APPROVE / REVIEW / DO NOT CHANGE]

### Reasoning
[SHORT FACTUAL EXPLANATION]

## 22. Decision Status

### GREEN — AUTO APPROVE

Use only where:

- cost is reliable;
- GST basis is known;
- unit conversion is reliable;
- category is clear;
- recommended margin is compliant;
- market evidence is sufficiently strong;
- price movement is not abnormal;
- no major contradictory evidence exists.

### AMBER — REVIEW

Use where:

- market evidence is weak;
- category is debatable;
- price movement is substantial;
- product is unusually rare;
- margin is unusual;
- dollar GP appears inadequate;
- existing NTA price materially differs from recommendation;
- supplier information is incomplete but a reasonable estimate exists.

### RED — DO NOT CHANGE

Use where:

- cost is unreliable;
- GST treatment materially affects the result and is unknown;
- pack/unit conversion cannot be established;
- product identity is uncertain;
- evidence conflicts materially;
- recommended price would create unacceptable economics;
- Shopify product/variant mapping is uncertain.

## 23. Confidence Assessment

Confidence must reflect evidence, not optimism.

### HIGH

Inputs verified and market evidence strong.

### MEDIUM

Core cost data reliable but some market/category uncertainty remains.

### LOW

Material assumptions or missing information could materially change the recommended price.

Never describe a result as HIGH confidence merely because the calculation itself is mathematically correct.

## 24. Devil's-Advocate Check

Before approving a recommended price, challenge it.

Ask:

1. Are we pricing too cheaply merely because competitors are cheap?
2. Are we pricing too high because the target margin is unrealistic for this category?
3. Is the competitor product genuinely equivalent?
4. Is supplier cost actually per unit?
5. Have we handled GST correctly?
6. Is the current NTA price already better than the proposed price?
7. Would lowering this price unnecessarily destroy existing margin?
8. Is apparent high margin hiding very low dollar gross profit?
9. Are we mistaking temporary scarcity for permanent pricing power?
10. Are we overlooking an unavoidable cost?
11. Is this recommendation based on sufficient evidence to change a live Shopify price?

If the devil's-advocate check exposes a material unresolved issue:

**DOWNGRADE CONFIDENCE OR ESCALATE.**

## 25. Shopify Write Rules

Where this skill is authorised to update Shopify:

Never write a new price until:

- correct product confirmed;
- correct variant confirmed;
- cost confirmed;
- unit conversion confirmed;
- pricing calculation completed;
- confidence/action threshold permits the change.

Where status is:

**GREEN / AUTO APPROVE**

the workflow may update the price if the calling workflow authorises automatic writes.

Where status is:

**AMBER / REVIEW**

do not automatically write unless explicitly authorised.

Where status is:

**RED / DO NOT CHANGE**

do not modify the price.

## 26. Post-Write Verification

A successful API response is not sufficient proof that pricing is correct.

After changing Shopify:

1. Re-fetch the product.
2. Re-fetch relevant variant.
3. Confirm retail price.
4. Confirm compare-at price.
5. Confirm SKU.
6. Confirm cost where accessible.
7. Confirm no unintended variant was changed.
8. Confirm intended customer-facing price.
9. Record verification result.

If verification fails:

**REPORT FAILURE AND DO NOT CLAIM THE TASK IS COMPLETE.**

## 27. Bulk Pricing

When reviewing multiple products:

Do not silently update an entire category based on one example.

For every product:

- calculate independently;
- classify independently;
- validate independently;
- assign confidence independently.

Bulk operations may share category rules and research evidence where products are genuinely comparable, but every SKU must still pass its own profitability and sanity checks.

## 28. Missing Cost

A retail price should not normally be automatically determined without reliable cost.

If Shopify cost is missing:

Attempt to establish cost from approved available evidence such as:

- supplier invoice;
- supplier order;
- supplier price list;
- verified current supplier information;
- other authoritative NTA records.

Never reverse-engineer cost from the existing retail price and then treat that estimate as fact.

If reliable cost cannot be found:

**RED — DO NOT AUTO-PRICE**

unless an explicitly authorised exception applies.

## 29. Record Keeping

Where supported, retain sufficient evidence to reconstruct why a retail price was selected.

Record where practical:

- date;
- cost;
- cost source;
- category;
- target margin;
- market evidence;
- existing retail;
- recommended retail;
- final retail;
- confidence;
- reason for override if applicable.

Pricing should be auditable rather than dependent on remembering why a number was chosen.

## 30. Human Override

The standard supports decision-making; it does not eliminate commercial judgment.

An authorised NTA decision-maker may override the recommended price.

Where an override materially breaches normal pricing rules, record:

**OVERRIDE**

and where possible:

- approved retail;
- reason;
- approver;
- date.

Do not silently rewrite the underlying pricing rules to rationalise an exception.

An exception is an exception.

## 31. Accuracy Rules

Never:

- invent supplier costs;
- invent competitor prices;
- invent pack quantities;
- invent GST treatment;
- claim a competitor match without verifying equivalence;
- treat sale pricing as normal market pricing without noting it;
- manufacture compare-at pricing;
- confuse markup with margin;
- claim Shopify was updated without verification;
- reduce an existing profitable price simply because the mathematical minimum is lower.

When uncertain:

**say so and reduce confidence.**

## 32. Current Provisional Status

This is:

**NTA Retail Pricing Standard — v0.1**

The category margin ranges are provisional.

Before promotion to v1.0, stress-test against a representative sample of actual NTA products including:

- common livestock;
- premium livestock;
- Bettas;
- shrimp;
- common plants;
- premium plants;
- tissue cultures;
- food;
- consumables;
- inexpensive accessories;
- commodity equipment;
- specialist equipment;
- stocked products;
- dropship products.

The stress test should identify:

- categories with unrealistic margin targets;
- products where dollar GP is inadequate;
- market-positioning conflicts;
- pack-conversion problems;
- cases where existing NTA prices outperform the calculated recommendation;
- appropriate thresholds for automatic price changes;
- appropriate minimum dollar GP rules.

Only after testing and adjustment should this standard be promoted to:

**NTA Retail Pricing Standard — v1.0**

## 33. Final Principle

The goal is not:

**"What is the cheapest price NTA can charge?"**

Nor is it:

**"What markup should NTA apply?"**

The goal is:

**"What is the most commercially appropriate retail price for NTA, supported by reliable cost data, acceptable profitability, credible market evidence, product risk, customer value, and existing sales reality?"**

Protect sustainable profit while remaining fair, competitive and evidence-based.
