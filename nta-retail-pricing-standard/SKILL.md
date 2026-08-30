---
name: "nta-retail-pricing-standard"
description: "Determine, validate, recommend, update, and verify Nano Tanks Australia retail prices using cost, category margin, market evidence, profitability, fulfilment economics, and controlled pricing safeguards."
version: "0.2"
---

# NTA Retail Pricing Standard — v0.2

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

The objective is not to produce the cheapest price. The objective is to determine a commercially sensible NTA retail price that protects profitability, remains defensible against the Australian market, reflects product and operational risk, recognises NTA value, maintains sensible price architecture, and avoids unnecessary reductions to established profitable prices.

Competitor prices are evidence, not instructions.

## 1. Core Pricing Principle

Determine retail price in this order:

**Product identification → Cost validation → Unit conversion → Category classification → Margin requirement → Margin-derived price → Market validation → Risk/value assessment → Fulfilment treatment → Price architecture → Existing-price comparison → Confidence assessment → Final recommendation → Shopify verification**

Never determine price from only one factor.

In particular:

- Do not use cost × arbitrary markup as the sole pricing method.
- Do not automatically copy competitors.
- Do not automatically undercut competitors.
- Do not automatically reduce an existing NTA price because a lower calculated price is possible.
- Do not confuse markup percentage with gross margin percentage.
- Do not force a target margin where credible market evidence shows that doing so would make the product commercially unrealistic.

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
- Fulfilment type, including pickup, delivered or dropship where applicable
- Australian market evidence
- Product availability/scarcity
- Relevant operational or product risk

Do not invent missing information. If a material input cannot be established reliably, lower confidence or escalate for review.

## 3. Cost Normalisation

### 3.1 GST

Margin calculations should normally use GST-exclusive values.

Where supplier cost includes Australian GST:

**Ex-GST Cost = GST-Inclusive Cost ÷ 1.10**

Where supplier cost is already ex GST, do not remove GST again.

Customer-facing Australian retail prices should normally be expressed GST-inclusive.

If the GST basis is unknown and materially changes the decision, do not classify the result GREEN.

## 4. Pack-to-Unit Conversion

Never assume supplier pack quantity equals Shopify retail quantity.

Determine:

**Unit Purchase Cost = Supplier Pack Cost ÷ Number of NTA Retail Units Produced**

Example: a supplier 10-pack costing $50 ex GST that NTA sells individually has a unit purchase cost of $5.

If pack quantity or retail-unit conversion is unclear:

**DO NOT AUTO-PRICE.**

## 5. Landed Cost

Where meaningful:

**NTA Unit Landed Cost = Ex-GST Unit Purchase Cost + Directly Attributable Unit Costs**

Potential attributable costs may include supplier freight, import freight, unavoidable supplier handling, per-product surcharges, unavoidable dropship fees, or other direct acquisition costs.

Do not arbitrarily allocate general overhead to landed cost.

## 6. Dropship Products

Dropship is NOT a pricing category.

Dropship products follow the same pricing methodology as equivalent stocked products. Classify the product according to what it actually is.

Examples:

Dropship filter → equipment category  
Dropship fish food → food/consumables category  
Dropship aquarium accessory → appropriate accessory category

Dropship status may affect actual economic cost where NTA incurs unavoidable supplier freight, dropship charges, handling charges, or similar costs.

**Fulfilment method does not determine margin target. Actual economic cost may affect profitability.**

## 7. Fulfilment-Specific Variants

Pickup and delivered variants are not automatically equivalent price points.

Where a delivered variant includes a documented freight, handling or delivery allowance:

1. establish the underlying product retail first;
2. establish the direct delivery cost or approved delivery surcharge;
3. add that fulfilment amount to the base retail in a consistent way;
4. compare competitors on an equivalent fulfilment basis;
5. do not compare an NTA delivered price directly with a competitor pickup price or a competitor price that excludes shipping.

If an existing delivered variant has a deliberate, evidenced delivery differential and the base product price changes, preserve or recalculate that differential rather than independently repricing the delivered variant as though it were a separate product category.

If the delivery differential cannot be explained or supported, classify the affected variant AMBER until reviewed.

## 8. Product Classification

Every product must be assigned to the most appropriate pricing category.

### Common Livestock
Provisional target gross margin: **55–65%**

### Premium / Rare Livestock
Provisional target gross margin: **60–70%**

### Individual Bettas
Provisional target gross margin: **60–70%**

### Shrimp / Specialist Invertebrates
Provisional target gross margin: **55–70%**

### Aquarium Plants
Provisional target gross margin: **55–65%**

### Tissue Culture
Provisional target gross margin: **45–55%**

### Food / Consumables
Provisional target gross margin: **35–45%**

### Commodity Branded Equipment
Products customers can readily compare across multiple Australian retailers. Provisional target gross margin: **30–40%**

### Specialist / Niche Equipment
Products with reduced direct comparability, specialist use or limited distribution. Provisional target gross margin: **40–50%**

### Low-Cost Accessories
Provisional target gross margin: **50–65%**. Minimum dollar gross profit is especially important here.

These ranges remain provisional until broader catalogue testing is complete.

## 9. Category Bleed Check

Do not classify products purely by keywords. Consider the actual commercial nature of the product.

Where two categories could reasonably apply:

1. identify both;
2. explain which is more appropriate;
3. use the selected category;
4. reduce confidence where classification materially affects the recommendation.

## 10. Gross Margin Calculation

Gross margin is NOT markup.

**Gross Profit = Ex-GST Selling Price − Unit Landed Cost**

**Gross Margin % = Gross Profit ÷ Ex-GST Selling Price × 100**

To calculate the retail price required for a target margin:

**Required Ex-GST Retail = Unit Landed Cost ÷ (1 − Target Margin)**

Then:

**GST-Inclusive Retail = Required Ex-GST Retail × 1.10**

The margin-derived price is an analytical input, not automatically the final NTA retail price.

## 11. Margin Range

Each category has a target margin range rather than one compulsory percentage.

Factors supporting the upper part of the range may include scarcity, mortality risk, conditioning, inconsistent availability, specialist care, unusual variety, high holding risk, individual selection, premium presentation, limited competition, or demonstrated willingness to pay.

Factors supporting the lower part may include commodity status, strong price transparency, high turnover, readily available supply, strategic traffic-generation, low handling risk, or unusually high dollar GP despite a lower percentage margin.

Do not convert these factors into arbitrary percentage bonuses unless explicitly defined by a future version.

## 12. Market Research

Market research validates the NTA price. It does not determine the price by itself.

Prefer Australian retailers selling:

1. the exact same product;
2. the same brand/model/size;
3. genuinely equivalent livestock strain/grade;
4. genuinely equivalent plant form/size;
5. genuinely comparable substitutes where exact matches are unavailable.

Record where possible competitor, product, price, size/quantity, stock status, sale vs normal price, similarity and date checked.

Derive where evidence allows:

**Market Low / Market Median / Market High / Sample Size**

## 13. Market Evidence Quality

### HIGH
Multiple credible Australian sellers with exact or near-exact product matches.

### MEDIUM
Some exact evidence plus reasonable comparable products.

### LOW
Few matches, questionable equivalence, outdated listings, marketplace sellers, overseas prices or highly variable products.

Low-quality evidence must not drive automatic price changes.

## 14. Market Outliers

Potential outliers include clearance pricing, liquidation, obvious pricing errors, permanently unavailable listings, materially different pack sizes, substantially different livestock grade, private/marketplace sellers, or temporary promotional discounts.

Record relevant outliers but do not let them distort the normal market range without justification.

## 15. Do Not Automatically Undercut

Never assume NTA should be the cheapest seller.

Determine the price based on required margin, NTA value, product risk, existing price, market position and reasonable retail architecture.

NTA may appropriately price near the median, above the median, or at the high end where evidence supports it.

## 16. Market-Constrained Margin Exception

Target margin is a target, not permission to price a product irrationally above a strong market.

If the margin-derived floor is materially above a credible high-quality Australian market range:

1. confirm cost and GST basis;
2. confirm product and pack equivalence;
3. confirm no freight or fulfilment mismatch exists;
4. calculate the best defensible market price;
5. calculate the gross margin at that market-defensible price;
6. classify the product **AMBER — MARGIN CONSTRAINED BY MARKET**;
7. do not silently force the product above market merely to hit the category target.

Possible actions include accepting a lower margin as an approved exception, renegotiating supplier cost, changing supplier, changing the product offer, bundling value, or discontinuing the product.

A market-constrained exception must remain visible as an exception. Do not rewrite the target-margin standard to rationalise it.

## 17. Existing Price Protection

An established NTA retail price has informational value.

If an existing product sells above a lower mathematical recommendation, do not automatically reduce it.

First determine whether the existing price remains defensible, customers have demonstrated willingness to pay, margin is healthy, market conditions changed, the product changed, or NTA's cost structure changed.

If the existing price remains commercially defensible:

**KEEP THE EXISTING PRICE.**

Price reductions require stronger justification than simply discovering that NTA could theoretically sell for less.

## 18. Price Increase Review

Where supplier costs rise or an existing price is materially below a credible market and produces weak economics, recalculate profitability.

Determine new landed cost, current GP, current GM, margin-derived retail, current market range and recommended new retail.

A clear market-supported correction may be appropriate even without a recent supplier cost change where the current retail is demonstrably stale or underpriced.

Material increases should still be flagged where confidence is insufficient for automatic action.

## 19. Minimum Dollar Gross Profit

Percentage margin alone is insufficient.

Every pricing assessment should calculate:

**Dollar Gross Profit Per Retail Unit**

Minimum dollar gross-profit thresholds are currently:

**TBD — requires NTA catalogue/order analysis.**

Until thresholds are formally established, unusually low dollar GP should trigger review rather than automatic approval.

## 20. Contribution Economics

Future versions should progressively incorporate payment processing, packaging, picking/handling labour, livestock mortality, plant losses, warranty/DOA exposure, shipping subsidy, platform costs and other directly attributable fulfilment expenses.

Do not fabricate contribution costs when reliable data is unavailable.

## 21. Retail Price Architecture

Do not publish unnecessarily awkward mathematical prices.

Use sensible customer-facing points appropriate to the category and market, for example $9.95, $14.95, $19.95, $24.95, $29.95, $39.95, $49, $59, $69, $79, $89, $99, or clean whole-dollar pricing where the category uses it.

These are examples, not mandatory price points.

Never round downward if doing so causes unacceptable economics without flagging the issue.

## 22. Sale and Compare-at Pricing

Never fabricate a compare-at price.

A compare-at price must represent a legitimate reference price and must not be created merely to make the current retail look discounted.

When reviewing Shopify pricing, check current price, compare-at price, whether the comparison remains legitimate, variant consistency, and whether stale sale pricing remains active.

### Persistent Sale Check

If a product appears to have been left indefinitely at a sale price and the compare-at price is effectively the current ordinary Australian market price, do not automatically preserve the sale presentation.

Check whether there is evidence that the higher compare-at price was genuinely NTA's established former selling price and that the sale remains current and intentional.

If not supported:

- set the commercially appropriate regular retail price;
- clear the unsupported or stale compare-at price;
- do not manufacture a replacement discount.

If evidence is insufficient, classify AMBER rather than presenting an unsupported sale claim.

## 23. Pricing Decision Output

For each product, record where relevant:

- Product
- SKU
- Category
- Supplier
- Supplier cost
- GST basis
- Supplier pack quantity
- NTA retail units produced
- Unit purchase cost ex GST
- Additional attributable cost
- Unit landed cost
- Current NTA retail
- Current GP and GM
- Target margin range
- Margin-derived retail
- Australian market low/median/high/sample
- Market evidence quality
- Fulfilment treatment
- Risk/value factors
- Recommended NTA retail
- Recommended GP and GM
- Price movement
- Confidence
- Action
- Short factual reasoning

## 24. Decision Status

### GREEN — AUTO APPROVE
Use only where cost is reliable, GST basis known, unit conversion reliable, category clear, economics acceptable, market evidence sufficiently strong, price movement not abnormal, fulfilment comparison equivalent, and no major contradictory evidence exists.

### AMBER — REVIEW
Use where market evidence is weak, category debatable, movement substantial, product unusually rare, margin unusual or market-constrained, dollar GP inadequate, fulfilment differential uncertain, existing price materially differs, or supplier information is incomplete.

### RED — DO NOT CHANGE
Use where cost is unreliable, GST treatment materially affects the result and is unknown, pack conversion cannot be established, product identity is uncertain, evidence conflicts materially, economics are unacceptable, or Shopify product/variant mapping is uncertain.

## 25. Confidence Assessment

### HIGH
Inputs verified and market evidence strong.

### MEDIUM
Core cost data reliable but some market/category/fulfilment uncertainty remains.

### LOW
Material assumptions or missing information could materially change the recommendation.

Never describe a result as HIGH confidence merely because the arithmetic is correct.

## 26. Devil's-Advocate Check

Before approving a recommended price, ask:

1. Are we pricing too cheaply merely because competitors are cheap?
2. Are we pricing too high because the target margin is unrealistic for this category?
3. Is the competitor product genuinely equivalent?
4. Is supplier cost actually per unit?
5. Have we handled GST correctly?
6. Is the current NTA price already better than the proposed price?
7. Would lowering this price unnecessarily destroy existing margin?
8. Is apparent high margin hiding very low dollar GP?
9. Are we mistaking temporary scarcity for permanent pricing power?
10. Are we overlooking an unavoidable cost?
11. Are we comparing pickup with delivered pricing incorrectly?
12. Is a compare-at price stale or unsupported?
13. Is this recommendation based on sufficient evidence to change a live Shopify price?

If a material unresolved issue remains:

**DOWNGRADE CONFIDENCE OR ESCALATE.**

## 27. Shopify Write Rules

Never write a new price until the correct product and variant are confirmed, cost and unit conversion are validated, pricing calculation is complete, fulfilment treatment is understood, and the confidence/action threshold permits the change.

GREEN may be written where the calling workflow authorises automatic writes. AMBER requires review unless explicitly authorised. RED must not be modified.

## 28. Store-Controlled Fields

If a pricing/catalogue workflow also updates Shopify metafields, metaobjects or enumerated fields, never invent display values.

First read the field definition or accepted choices and use the store's exact canonical values.

A failed atomic validation is preferable to a partial write. If the platform rejects a value, inspect the accepted choices and retry with a valid canonical value rather than guessing.

Pricing logic must not use raw inventory quantity as a substitute for a separately managed customer-facing availability classification unless the store explicitly defines that relationship.

## 29. Post-Write Verification

A successful API response is not sufficient proof that pricing is correct.

After changing Shopify:

1. re-fetch the product;
2. re-fetch relevant variant;
3. confirm retail price;
4. confirm compare-at price;
5. confirm SKU;
6. confirm cost where accessible;
7. confirm no unintended variant changed;
8. confirm any related store-controlled field written by the workflow;
9. confirm intended customer-facing state;
10. record verification result.

If verification fails:

**REPORT FAILURE AND DO NOT CLAIM THE TASK IS COMPLETE.**

## 30. Bulk Pricing

Do not silently update an entire category based on one example.

For every product or SKU, calculate, classify, validate and assign confidence independently.

Bulk operations may share category rules and market evidence where products are genuinely comparable, but every SKU must pass its own profitability and sanity checks.

## 31. Missing Cost

A retail price should not normally be automatically determined without reliable cost.

Attempt to establish missing cost from approved evidence such as supplier invoices, supplier orders, supplier price lists, verified current supplier information or authoritative NTA records.

Never reverse-engineer cost from retail price and then treat that estimate as fact.

If reliable cost cannot be found:

**RED — DO NOT AUTO-PRICE**

unless an explicitly authorised exception applies.

## 32. Record Keeping

Where supported, retain enough evidence to reconstruct why a price was selected, including date, cost, cost source, category, target margin, market evidence, existing retail, recommended retail, final retail, confidence, fulfilment treatment and reason for override where applicable.

Pricing should be auditable rather than dependent on memory.

## 33. Human Override

An authorised NTA decision-maker may override the recommended price.

Where an override materially breaches normal rules, record **OVERRIDE**, the approved retail, reason, approver and date where practical.

Do not silently rewrite the underlying standard to rationalise an exception.

## 34. Accuracy Rules

Never:

- invent supplier costs;
- invent competitor prices;
- invent pack quantities;
- invent GST treatment;
- claim a competitor match without verifying equivalence;
- compare different fulfilment methods as though prices were equivalent;
- treat sale pricing as normal market pricing without noting it;
- manufacture compare-at pricing;
- confuse markup with margin;
- invent values for store-controlled metafields or enums;
- claim Shopify was updated without verification;
- reduce an existing profitable price simply because the mathematical minimum is lower.

When uncertain, say so and reduce confidence.

## 35. Field-Test Learnings — Aquael Aquariums, 31 August 2026

The first live field test of this skill against the NTA Aquael Aquariums collection established the following:

- equipment margin targets must remain subordinate to credible market validation;
- some stale promotional prices can materially suppress margin while the old compare-at price has become the normal market level;
- delivery-inclusive variants require separate fulfilment economics and must not be compared directly with pickup-only competitor prices;
- exact Shopify metafield choices must be read before writing store-controlled classifications;
- customer-facing availability classification can be intentionally independent of raw Shopify inventory quantity;
- a draft product should not be automatically published merely because its price or availability has been reviewed;
- post-write verification must confirm both price and any related catalogue state.

These are now formal rules in v0.2.

## 36. Current Provisional Status

This is:

**NTA Retail Pricing Standard — v0.2**

The category margin ranges remain provisional.

Before promotion to v1.0, continue stress-testing against common livestock, premium livestock, Bettas, shrimp, common and premium plants, tissue cultures, food, consumables, inexpensive accessories, commodity equipment, specialist equipment, stocked products and dropship products.

The remaining major unresolved controls are:

- minimum dollar GP thresholds;
- automatic price-change tolerance thresholds;
- fuller contribution-margin economics.

Only after broader testing and adjustment should this standard be promoted to **v1.0**.

## 37. Final Principle

The goal is not "What is the cheapest price NTA can charge?" and it is not "What markup should NTA apply?"

The goal is:

**"What is the most commercially appropriate retail price for NTA, supported by reliable cost data, acceptable profitability, credible market evidence, product risk, customer value, fulfilment economics and existing sales reality?"**

Protect sustainable profit while remaining fair, competitive and evidence-based.
