# TerpPilot

Batch-specific cannabis chemistry research prototype for Vivid and Robust.

- 688 lab-linked historical batch records (552 Vivid; 136 Robust).
- 688 source-verified cannabinoid panels with 16 measurements/statuses per batch, including THC, THCA, CBD, CBDA, CBG, CBGA, CBN, THCV, CBC, and acidic counterparts. Values are measured % by mass or lab status `ND` / `<LOQ`; neither is equated to zero.
- 671 full terpene analyte panels and 17 partial records, clearly labeled.
- Individual batch fingerprint pages, source COA links, minor cannabinoid highlights, batch-to-batch variation, and cannabinoid side-by-side comparisons.
- Terpene match score is descriptive only and is **not** a cannabinoid-adjusted score or a prediction of effects, safety, quality, or product availability.

Site: `index.html` (product catalog and UI), `cannabinoids.js` (COA-verified cannabinoid profiles), `robots.txt`.

Data snapshot: October 19, 2026. These are historical lab records, not real-time dispensary stock.


## Ask Terp Pilot (beta)

The Explore dashboard includes a conversational chemistry-search interface above the three existing doors (Vibe, Flavor, Science). It parses supported natural-language constraints (aroma families, named measured terpenes, product category, brand, minimum total terpenes, and a measured-myrcene ceiling), applies them through the existing catalog filter and match-score functions, and presents linked historical batch evidence.

The chat does **not** call a generative language model yet. Its source logic is in \`chat-discovery.js\`, its styling is in \`chat-discovery.css\`, and both are embedded into \`index.html\` because the Render static build publishes a single HTML file. If updating either source, also sync the embedded copy.

The measured-chemistry comparison must never be presented as an effect prediction or live inventory. A future language-model backend would require a separate authenticated/rate-limited server endpoint and an API key stored only server-side, not in HTML or client JavaScript.
