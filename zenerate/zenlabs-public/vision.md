# Vision: Building the Voice AI Platform for Regulated, Workflow-Heavy Verticals

> A shareable strategy doc for hiring conversations. The premise: ElevenLabs is winning the voice-model layer, Sierra is winning enterprise voice agents, and Vapi is winning developer infrastructure. None of them are winning the **integration-deep, vertical-aware, mid-market** segment — and that's where ~$20B of capturable software TAM lives over the next 5 years.

---

## The Real Prize

Customer-service is a **$400B+ global / $130-180B US labor market**, not a software market. Sierra trades at 100x revenue because investors are pricing labor displacement, not seat-license replacement. Every minute of AI conversation at $0.30 replaces $3-8 of human labor + supervisor + facility cost. The right way to size this opportunity is to count the agent-hours an AI can capture, not the existing CCaaS line item.

US-buyer spend breakdown (the honest number, net of offshoring):
- ~$100-130B onshore (in-house + onshore BPO) — high-margin AI displacement, 60-80% cost reduction
- ~$30-50B offshored to Philippines/India/LATAM — volume play, 30-50% cost reduction
- Total addressable: $130-180B in labor + ~$25-30B in adjacent software

---

## 1. Use Cases by TAM

Use cases renumbered 1-10 by US TAM (descending). Capturable software TAM is roughly 10-25% of displaced labor cost.

| # | Use Case | Labor Pool | US TAM | Capturable SW TAM (2028-30) |
|---|---|---|---|---|
| 1 | Telephone voice assistant (human + AI) | Tier-1 phone agents: 1.5-2M onshore FTE-eq + offshored voice BPO bought by US firms | $70-110B | $15-30B |
| 2 | Dedicated agent-assist window | Productivity lift on ~3M US-buyer-funded agents (onshore + offshore) | $20-40B | $4-8B |
| 3 | Browser text assistant (human + AI) | Chat-tier agents (~500-700K FTE-eq) + existing chat SaaS spend | $20-35B | $4-8B |
| 4 | Phone voice conference (human + AI disabled + transfer) | Tier-2 / escalation agents (~300-500K FTE-eq, skewed onshore for regulated work) | $15-30B | $2-5B |
| 5 | Guardrails (core) | QA reviewers + compliance officers (~150-200K FTE-eq) + regulatory risk pool | $8-15B | $1-2B |
| 6 | Browser voice assistant (human + AI) | Voice volume migrating from phone to web (5-10% by 2028) | $5-12B | $1.5-3B |
| 7 | Multi-party voice (marketplace flows) | Marketplace ops + claims/dispute coordination (gig, insurance, logistics) | $4-12B | $1-3B |
| 8 | Conference with 2+ human agents + AI | Warm-transfer / supervisor barge-in / multi-skill collab on escalations | $2-6B | $0.5-1.5B |
| 9 | Browser voice conference (human + AI disabled + transfer) | Escalation voice agents on web channel — small early-stage slice | $1-3B | $0.3-1B |
| 10 | Integrations + orchestration (embedded core) | Not standalone — drives 20-30% pricing premium across #1, #2, #3, #6 | Embedded | — |

**Read:** Use cases #1 + #2 = ~75% of capturable TAM. #10 (integrations) is the moat, not a product line. #4 is the most underexplored real opportunity — large market, near-zero pure-play competitors, regulatory tailwind.

---

## 2. Top US Vertical Players by Industry

The horizontal-vs-vertical question is settled. Vertical players are raising at $1B+ valuations (Avoca, Eve, EvenUp, Hippocratic) while horizontal ones face pricing pressure. a16z's own view: "voice will become the wedge, not the product."

| Vertical | US Labor Pool | Top Startups (ordered by traction) |
|---|---|---|
| Home services (HVAC, plumbing, electrical, roofing) | ~600K dispatchers/CSRs; $50B HVAC alone | **Avoca** ($1B val, $125M raised, 8-fig ARR, on track to book $1B in jobs), Rilla (sales coaching for trades), Goodcall, Dialzara, Bravi (YC) |
| Legal intake / plaintiff law | ~50-80K paralegals + intake specialists | **Eve.legal** ($1B val, $103M raised, 450+ firms, 200K cases/yr), **EvenUp** ($2B val, $150M Series E), Supio ($60M), Caseflood.ai (YC), Filevine |
| Healthcare front office (clinics, dental, vet, PT) | ~1M front-desk + scheduling staff; $30-50B labor | **Hippocratic AI** ($402M raised, patient nurse calls), **Abridge** ($300M, ambient doc), Paratus Health (YC), Prosper AI, Decoda Health, Assort Health |
| Healthcare back office (RCM, payer-provider calls) | ~500K billing/RCM staff; $20-30B labor | **SuperDial** ($15M Series A, 4x productivity), **LunaBill** (YC, $764K ARR in 5 months), Corti ($605M val), Infinitus, Notable Health |
| Restaurants (drive-thru, phone orders, reservations) | ~400-500K front-of-house labor exposed to voice automation | **PolyAI** (restaurant phone), Vox AI ($8.7M, QSR drive-thru), Hostie AI (Yelp partnership), Kea, ConverseNow, Presto Automation (public) |
| Hotels / hospitality | ~200-300K front-desk + concierge | Canary Technologies, Aiello (AVA), Q Concierge, UPRISER (VEE) |
| Insurance (FNOL, claims, policy servicing) | ~400-500K claims + policy CSRs; $25-35B labor | Strada (insurance-purpose-built), Ema (universal AI worker), **FurtherAI** ($25M Series A), Inaza, Feather AI, Sixfold |
| Financial services (banking, lending, collections) | ~700-900K bank/lending CSRs; $50-70B labor (largest single vertical) | **Sierra** (Chime, SoFi, Rocket, Nubank), Salient (auto loans), Skit.ai (collections), Posh (community banks/CUs), Glia, TrueAccord |
| Debt collection | ~150-200K collectors; highly regulated | Skit.ai, Prodigal, TrueAccord, Salient |
| Staffing / recruiting (screening, interviews) | 43 public co agencies, $650B annual revenue | Mercor, Phenom, Paradox, Karat (engineering), HireVue |
| Sales coaching / training (voice as simulator) | ~200K sales managers + coaches | Rilla (field sales), Hyperbound (cold call sims), Second Nature, Replicate Labs |

**Read:** Financial services has the biggest labor pool and Sierra owns it. Insurance, healthcare back-office, and mid-market financial services are the most contested-but-still-open verticals. Skip the verticals where someone has clearly won.

---

## 3. Competitor Ranking by Captured Share

Directional ranking by customer logos, investor signal, and reported ARR. None publish revenue by use case. One row per use case lets us cover the full spectrum and see where the whitespace lives.

| Use Case | #1 (Leader) | #2 | #3 | #4 | #5 | Notes |
|---|---|---|---|---|---|---|
| #1 Telephone voice (human + AI) | **Sierra** | ElevenLabs Agents | Decagon | Retell AI | PolyAI | Sierra dominates F500 enterprise; ElevenLabs strong on infra side |
| #2 Agent-assist window | **Cresta** | ASAPP | Observe.AI | Balto | Level AI | Cresta + ASAPP have 5+ year head start; Balto wins compliance |
| #3 Browser text assistant | **Intercom Fin** | Zendesk AI | Salesforce Agentforce | Sierra (text) | Ada / Decagon | Incumbents (Intercom/Zendesk) bundling AI; Sierra moving in |
| #4 Phone conference (human + AI disabled + transfer) | *no clear leader* | Balto (adjacent) | NICE (feature) | Five9 (feature) | Genesys (feature) | **Real whitespace** — no pure-play; CCaaS players have weak features |
| #5 Guardrails (compliance + QA) | **Sierra (built-in)** | NICE/Verint QA (legacy) | Sedric.ai | Patronus | Lakera / Aporia | Sierra's PCI L1 cert is the bar; legacy QA being eaten |
| #6 Browser voice assistant | **ElevenLabs widget** | Vapi Web SDK | Retell | PolyAI | Synthflow | Light competition; will follow #1's leaders |
| #7 Multi-party voice (marketplace flows) | *no clear leader* | Sierra (moving in) | DoorDash internal | Uber internal | Salesforce Agentforce | Marketplaces build in-house; vendor opportunity exists |
| #8 Conference w/ 2+ human agents + AI | *no clear leader* | NICE supervisor-assist | Five9 supervisor | Genesys | Balto | Embedded features only; no platform play |
| #9 Browser voice conference + transfer | *no clear leader* | Zoom AI Companion (adjacent) | — | — | — | Too early to call |
| #10 Integrations + orchestration | **Sierra Agent OS** | Salesforce Agentforce | LangGraph | CrewAI | ElevenLabs tools | **ElevenLabs weakest here** — the moat opportunity |

**Read:** Sierra leads 4 of 10 use cases (#1, #5, #10, partially #3). Cresta owns #2. ElevenLabs only clearly leads #6. **Use cases #4, #7, #8, #9 have no leader** — that's $20-50B of TAM with no entrenched winner. ElevenLabs' weakest position is #10 (integrations), which is precisely the moat play.

---

## 4. Zero-CAC GTM: The 5 Paths

"Zero CAC" doesn't mean $0 effort. It means distribution that scales without paying per customer — someone else's audience, network, or product surface does the acquiring. Real zero-CAC is mostly a $0-10M ARR phenomenon and requires structural channels (SoRs, buying groups) more than tactics.

| # | GTM Path | What it is | Best-fit use cases | CAC profile | Companies winning with it |
|---|---|---|---|---|---|
| 1 | Sell through System of Record (SoR) | Build a certified, marketplace-listed integration into the dominant vertical SaaS (ServiceTitan, Guidewire, Epic, Toast, Cloudbeds, Clio, McLeod, Shopify). Get listed as "AI voice partner of record." Co-sell. | UC #1, #10 | Near-zero (rev-share or partner fee) | Avoca/ServiceTitan, SuperDial/Athena+Epic, Salient/MeridianLink, Eve/Filevine, Hippocratic/Epic |
| 2 | Sell to Buying Group / Franchise Network | Negotiate exclusive partnership + member rebate with industry buying group, franchise system, or trade association (Nexstar, Service Brands, IFA, AHA, ABA, IIABA/Big I). | UC #1, #5, #7 | Near-zero (5-10% group rev share) | Avoca/Nexstar, Hippocratic/AHA-adjacent, debt-collection consortiums |
| 3 | Sell to BPOs (white-label or co-sell) | Partner with Teleperformance, Concentrix, TTEC, TaskUs. They deploy your AI as "AI labor." You get scale; they defend their book against disintermediation. | UC #1, #2 | Low (slow 6-12 mo cycle but huge deals) | ASAPP/many BPOs, Cresta/TaskUs, Sanas/multiple BPOs, Observe.AI/Teleperformance |
| 4 | Enterprise Marketplace Listing | Get listed on Salesforce AppExchange, Genesys AppFoundry, AWS Connect, Twilio. Customers find you when shopping for "AI for [SoR]." | UC #2, #10 | Low (table stakes; don't expect leads alone) | All CCaaS-adjacent voice AI |
| 5 | Developer PLG | Free credits + great docs + Discord community. Developers prototype → companies adopt → enterprise upsell. | UC #1, #6 | Low ($0-100/signup, $5-50K LTV) | Vapi (100K+ devs, $8M ARR), Retell ($50M ARR), Bland, ElevenLabs (started here) |
| 6 | SMB PLG | Self-serve signup, credit-card billing, "make a call in 5 min" demo. Free tier → $99-499/mo plans. | UC #1 narrow, #6 (receptionist-class) | Tight LTV/CAC; ceiling at $20-50M ARR | Thoughtly, Synthflow, Dialzara, Goodcall, Posh AI (CU/banks) |
| 7 | Vertical First | Lead with one industry, build deep playbook, then expand to adjacent. | All UCs, scoped to one vertical | Medium ($2-10K w/ vertical channel; $30-50K without) | Avoca (home services), Eve (plaintiff law), SuperDial (healthcare RCM), Salient (auto loans), Skit.ai (collections) |
| 8 | Few Verticals Parallel | 2-3 verticals chosen for complementary properties (one big + one defensible + one PLG-friendly). | All UCs across 2-3 verticals | Medium-high (2-3x sales/marketing org cost) | Sierra initially (retail + fintech + tech), Decagon (internet-native verticals) |
| 9 | Horizontal Field Sales | Enterprise AE + SE + RFPs + 6-12 mo cycles. Targeting Fortune 1000 directly. | UC #1, #2 at large enterprise | High ($50-300K/customer) | Sierra now, Cresta, ASAPP, Cognigy, Parloa |

**Read:** True zero-CAC paths are #1 + #2. PLG (#5, #6) is low-CAC, not zero. Horizontal field sales (#9) is the highest-CAC option and only works post-$20M ARR with brand. The 5 paths in your framing map: Vertical First = #7; Few Verticals = #8; Horizontal = #9; Embedded = #1 + #2 + #3 + #4; PLG = #5 + #6.

---

## 5. Recommended GTM Sequencing

One vertical wedge isn't enough — many wedges are valid, and the right one depends on founder-fit + competitive density. Below: candidate verticals per phase, each with its dominant SoR, buying group / aggregator, and competitor density. Score the ones where you have founder-domain credibility.

| Phase | ARR | Vertical Wedge | Dominant SoR | Buying Group / Aggregator | Competitor Density | ACV Range |
|---|---|---|---|---|---|---|
| **Phase 1: Pick ONE** | $0 → $5M | Insurance brokers + mid-market carriers | Guidewire, Applied Epic | IIABA / Big I, PIA | Light (Strada small; Feather small; Ema enterprise) | $30-100K |
| Phase 1 | $0 → $5M | Healthcare RCM (payer-provider calls) | Athena, Epic, eClinicalWorks | MGMA, HFMA | Light-medium (SuperDial $15M, LunaBill <$1M, Infinitus) | $40-150K |
| Phase 1 | $0 → $5M | Mid-market FS (credit unions, community banks) | Q2, Jack Henry, Fiserv | CUNA, ICBA | Light (Posh AI leading but small) | $50-200K |
| Phase 1 | $0 → $5M | **Freight brokerage + 3PL** | **McLeod (PowerBroker), Descartes, MercuryGate** | TIA (Transportation Intermediaries Assoc.), CSCMP | Light (Parade.ai already partnered w/ McLeod for voice — beachhead exists but small) | $30-80K |
| Phase 1 | $0 → $5M | **DTC ecommerce + 3PL fulfillment** | **Shopify Plus, ShipBob, ShipMonk, Gorgias** | Shopify Plus partner program; DTC Pulse community | Medium (Gorgias dominates Shopify support; voice underpenetrated) | $20-60K |
| Phase 1 | $0 → $5M | **NBFCs (non-bank lenders, BNPL, auto finance)** | **MeridianLink, nCino, Blend, Tavant** | OLA (Online Lenders Alliance), AFSA | Light (Salient leads auto loans; Skit.ai collections) | $40-150K |
| Phase 1 | $0 → $5M | Property management (multifamily, residential) | AppFolio, Buildium, Yardi, RealPage | NAA, NMHC | Light (EliseAI leading leasing, but customer service open) | $30-100K |
| Phase 1 | $0 → $5M | Auto dealerships | CDK Global, Reynolds & Reynolds | NADA, dealer 20-groups | Light (Numa, Impel, but most legacy) | $40-150K |
| Phase 1 | $0 → $5M | K-12 + higher-ed admin | PowerSchool, Banner, Workday Student | AACRAO, NAIS | Very light (Mainstay/AdmitHub adjacent only) | $50-200K |
| ❌ Avoid | — | Home services | ServiceTitan | Nexstar | **Avoca owns** | — |
| ❌ Avoid | — | Plaintiff law | Filevine, Litify | TLA, AAJ | **Eve + EvenUp own** | — |
| ❌ Avoid | — | QSR / drive-thru | Toast, Olo | NRA | **PolyAI, ConverseNow, Vox crowded** | — |
| **Phase 2: Add 2-3 adjacent** | $5M → $25M | Replicate Phase 1 playbook in 2-3 adjacent verticals from above. BPO partnerships start. | — | — | — | — |
| **Phase 3: Horizontal platform** | $25M+ | Pitch "voice AI platform for regulated, integration-heavy verticals." 3+ verticals = proof points. Run field sales against Sierra. | — | — | — | — |

**Read:** The strongest *unclaimed* Phase 1 wedges are **(1) Freight brokerage** (McLeod has voice AI partners but no clear leader; Parade.ai is small), **(2) NBFCs + auto finance** (huge labor pool, MeridianLink/nCino integration depth wins), and **(3) DTC ecommerce post-purchase** (Gorgias owns text but voice is open; ShipBob/ShipMonk integration is the wedge). Insurance brokers and healthcare RCM remain strong if founder-fit exists. Sequencing matters more than picking the "biggest" — pick where you have credibility and where the SoR + buying-group combo gives you zero-CAC distribution from day one.

---

## 6. The Single Most Important Takeaway

The four current winners — Sierra, ElevenLabs, Avoca, Eve — each rode a different structural channel:

- **Sierra**: Bret Taylor's network + Greenoaks-led brand halo (not replicable without that founder profile)
- **ElevenLabs**: Developer PLG + Fortune 500 inbound (took 4 years and Sequoia)
- **Avoca**: ServiceTitan marketplace + Nexstar buying group (replicable in other verticals)
- **Eve**: Plaintiff bar conferences + a16z legal-tech network (replicable)

**The most copyable playbook is Avoca's: find a vertical with a dominant System of Record + a strong buying group, become the canonical voice AI partner for both, then expand.** That's the real zero-CAC path — and it compounds, because every SoR integration we ship deepens the moat ElevenLabs is structurally bad at building.

Also worth saying clearly: **the buyer for $1B in software is a CIO; the buyer for $100B in labor displacement is a COO or CFO.** Sierra figured this out and sells to operations leaders. ElevenLabs is still mostly selling to developers. That gap is the opportunity.