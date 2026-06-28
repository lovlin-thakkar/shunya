# Platform Walkthrough

A click-by-click tour of the ZenLabs web app, grouped to match the left-nav: **Getting started → Configure → Monitor → Deploy**. Every section is a single `##` heading so the Cursor outline stays flat.

---

## Getting Started / Log in and pick a workspace

Open the ZenLabs web app. If you aren't signed in, you land on the login screen.

```
┌──────────────────────────────────────────────────────┐
│                      ZenLabs                          │
├──────────────────────────────────────────────────────┤
│                                                      │
│       ┌────────────────────────────────┐             │
│       │  Email                         │             │
│       │  [ jane@acme.com         ]     │             │
│       │                                │             │
│       │  Password                      │             │
│       │  [ •••••••••••••••       ]     │             │
│       │                                │             │
│       │           [   Sign in   ] ◄────┼─── click    │
│       └────────────────────────────────┘             │
│                                                      │
└──────────────────────────────────────────────────────┘
```

If your account belongs to more than one workspace, the next screen is the workspace picker.

```
┌──────────────────────────────────────────────────────┐
│  Pick a workspace                                    │
├──────────────────────────────────────────────────────┤
│   ◯  Acme Pets                                       │
│   ◉  Pizza Co        ◄── click your workspace        │
│   ◯  Demo Tenant                                     │
│                                                      │
│                       [   Continue   ]               │
└──────────────────────────────────────────────────────┘
```

Choose one and continue. You land on **Agents**.

---

## Getting Started / Switch workspace

The active workspace name lives in the top bar. Click it to open the switcher.

```
┌──────────────────────────────────────────────────────┐
│  ZenLabs    [ Acme Pets ▼ ]    Agents  Tests  ⋯      │
│             ──────────────                            │
│             │ ✓ Acme Pets │  ◄── current              │
│             │   Pizza Co  │  ◄── click to switch      │
│             │   Demo      │                           │
│             ──────────────                            │
└──────────────────────────────────────────────────────┘
```

Picking a different workspace reloads the app with that workspace's data. No re-login needed.

---

## Getting Started / The left navigation

After you sign in, a persistent left-nav appears, with the ZenLabs logo at the top and three section headers below it:

```
┌──────────────────────┐
│  Z  ZenLabs          │
│  ─────────────────── │
│  🏠  Home            │
│                      │
│  Configure           │
│  🤖  Agents          │
│  📖  Knowledge Base  │
│  🔧  Tools           │
│  🧩  Integrations    │
│  🔌  Connections     │
│                      │
│  Monitor             │
│  📊  Analytics       │
│  💬  Conversations   │
│  🧪  Tests           │
│                      │
│  Deploy              │
│  📞  Phone Numbers   │
│  💬  WhatsApp  Soon  │
│  📤  Outbound        │
└──────────────────────┘
```

Each section below maps to one entry in this nav.

---

## Configure / Settings — Workspace Secrets

Path: `/settings/secrets`

The Settings page holds **workspace-level configuration and credentials**. The page subtitle is *"Workspace-level configuration and credentials."*

The page is laid out with a thin sub-nav on the left (today only one tab: **Workspace Secrets**) and the secret list on the right.

```
┌───────────────────────────────────────────────────────────────────────┐
│  Settings                                                             │
│  Workspace-level configuration and credentials.                       │
│                                                                       │
│  ┌──────────────────┐    Workspace Secrets        [ + Add secret ]    │
│  │ Workspace Secrets│    Securely store credentials shared across     │
│  └──────────────────┘    agents. Once added, the value cannot be      │
│                          retrieved.                                   │
│                                                                       │
│                          🔒  DAILY_API_KEY       [ Unused  ]    ⋯    │
│                              No description · Added 3 days ago        │
│                                                                       │
│                          🔒  CARTESIA_API_KEY    [ Used by 2 ]  ⋯    │
│                              No description · Added 3 days ago        │
│                                                                       │
│                          🔒  OPENROUTER_API_KEY  [ Used by 3 ]  ⋯    │
│                              No description · Added 3 days ago        │
│                                                                       │
│                          🔒  DEEPGRAM_API_KEY    [ Used by 2 ]  ⋯    │
│                              No description · Added 3 days ago        │
└───────────────────────────────────────────────────────────────────────┘
```

Workspace secrets are credentials shared across every agent in the workspace — provider API keys, mostly. Typical entries:

- `CARTESIA_API_KEY` — text-to-speech
- `DEEPGRAM_API_KEY` — speech-to-text
- `OPENROUTER_API_KEY` — LLM provider gateway
- `DAILY_API_KEY` — WebRTC transport

Click **+ Add secret** to add a new one. The dialog asks for a name and a value. **Once added, the value cannot be retrieved** — only overwritten or deleted. Each row shows a usage chip (`Used by N` / `Unused`) so you can spot orphaned secrets.

The row menu (`⋯`) lets you edit the description, rotate the value, or delete the secret.

---

## Configure / Agents / Seed agents — Import YAML

Path: `/agents`

Today the fastest way to get a working agent is to import one from a YAML file.

Click **Agents → + Import** in the top-right.

```
┌──────────────────────────────────────────────────────────────┐
│  Agents                          [ + Import ]  [ New agent ] │
│                                       ▲                       │
│                                       └── click               │
│  ──────────────────────────────────────────────────────────  │
│  Title                  LLM             Last edited           │
│  ──────────────────────────────────────────────────────────  │
│  Customer Onboarding    gpt-4o          3h ago                │
│  Lead Qualifier         claude-sonnet   1d ago                │
└──────────────────────────────────────────────────────────────┘
```

```
┌────────────────────────────────────────┐
│  Import agent                          │
├────────────────────────────────────────┤
│   ┌────────────────────────────────┐   │
│   │  Drop a .yaml or .zip here     │   │
│   │  or                            │   │
│   │     [  Browse files  ]         │   │
│   └────────────────────────────────┘   │
│                                        │
│   Conflict mode                        │
│   ◉ Create new   (suffix added)        │
│   ○ Replace existing                   │
│   ○ Abort on conflict                  │
│                                        │
│   [ Cancel ]      [  Import  ] ◄───────┼── click
└────────────────────────────────────────┘
```

The dialog validates the YAML first. If anything is off, you see a per-field error list. If clean, **Import** creates the agent with all nodes, variables, edges, integrations, and business hours intact.

---

## Configure / Agents / Review an agent

Click any agent in the list to open the detail view. The right-hand **Settings** rail is where the agent's identity lives. Walk it top-down:

| Drawer | What you edit |
|--------|----------------|
| **Name & prompt** | Agent display name, system prompt, internal description |
| **LLM** | Provider (OpenAI / Google / OpenRouter), model, temperature, max tokens |
| **Voice** | Provider (Cartesia / ElevenLabs), voice id, speed, stability |
| **Transcriber** | Deepgram model, language, endpointing, smart format |
| **Workflow** | Nodes, edges, variables, business hours, integrations |

A quick review pass is: name → prompt → LLM model → voice → transcriber → walk the canvas left-to-right.

---

## Configure / Agents / Run a preview

Click **Preview** in the top-right of the agent detail page. A side panel opens.

```
┌──────────────────────────────────────────────┐
│  [ Inline ]  [ Widget ]              ⤢   ✕  │
│                                              │
│                                              │
│                                              │
│                  ╭───────────╮               │
│                  │           │               │
│                  │ ░░ orb ░░ │ ◄── click to  │
│                  │  ╭───╮    │     toggle    │
│                  │  │ 📞│    │     mic       │
│                  │  ╰───╯    │               │
│                  ╰───────────╯               │
│                                              │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ Send a message to start a chat   ►    │ ◄┼─ type +
│  │ ⚙   🎤                                │  │  send
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

The preview supports two layouts and two modalities, all in one panel:

- **Inline tab (default)** — preview lives inside the agent detail view alongside the canvas.
- **Widget tab** — preview pops out as a standalone chat widget that mirrors how an embedded ZenLabs widget would look on a customer site. Useful for screen-sharing demos.

The expand icon (⤢) in the top-right enlarges the panel; the close icon (✕) closes it.

Inside either tab:

- **Voice** — click the central gradient orb (with the phone icon) to toggle the microphone on. The orb pulses while the agent is speaking and shows a quieter pulse while it's listening. Click again to mute.
- **Text** — type into the **Send a message to start a chat** box at the bottom and hit the send arrow (or `⏎`). Same workflow, no microphone needed.
- The small gear icon (⚙) under the input opens preview-only options (e.g. seeded variables, override prompts). The mic icon (🎤) next to it toggles voice without using the orb.

Use text to iterate on logic fast. Use voice to verify barge-in, prosody, and latency. The transcript expands as turns accumulate, and both modes log the full conversation under **Conversations** when you close the panel.

---

## Configure / Agents / Design a new agent — Dynamic vs Task Blocks

Every node in an agent's workflow runs in one of two modes, controlled by the **Steps mode** toggle on the node config panel.

**The node config panel.** Open any node from the canvas — a side panel slides in from the right. The first thing at the top is the **Steps mode** toggle.

```
┌──────────────────────────────────────────────────┐
│  ✨  Auth2                                ✕     │
│                                                  │
│  Steps mode                                ⮤ [●] │ ◄── toggle
│  Structured step-by-step flow                    │
│  ───────────────────────────────────────────────│
│  ⌄ General                                       │
│    Description                                   │
│    [ Greeting.                              ]    │
│    Entrypoint                              [●]   │
│    End node                                [○]   │
│    Respond immediately                     [●]   │
│  ───────────────────────────────────────────────│
│  ⌄ Steps                                         │
│    18 steps configured        [ Edit Steps  ⮤ ]  │
│  ───────────────────────────────────────────────│
│  > Variables                                  9  │
│  > Edges                                      0  │
│  > Actions                                       │
└──────────────────────────────────────────────────┘
```

Below the **Steps mode** toggle the panel has:

- **General** — `Description`, plus three switches: **Entrypoint** (this is the node the workflow starts from), **End node** (terminates the conversation), and **Respond immediately** (don't wait for user input before speaking the first line).
- **Steps** — present only when Steps mode is on. Shows `N steps configured` and an **Edit Steps** button that opens the steps detail page.
- **Variables**, **Edges**, **Actions** — collapsible sections, each with a count on the right.

**The two modes.**

- **Steps mode OFF → Dynamic node.** A single LLM step driven by a free-form prompt. The agent improvises each turn based on the prompt plus conversation state.
  - **Pros:** Quick to author. Handles open-ended exchanges. Good for greetings, qualification, free-form Q&A.
  - **Cons:** Hard to make deterministic. Variable extraction is best-effort. Hard to assert against.
  - **Use when:** the conversation is genuinely open-ended and rigid scripting would feel robotic.

- **Steps mode ON → Task Blocks node.** A structured, step-by-step flow. The agent walks an ordered list of typed steps deterministically; the LLM only fills in the natural-language wrapper around each step.
  - **Pros:** Predictable. Easy to test with assertions. Cleanly integrates with external systems.
  - **Cons:** More setup. Less flexible for open exchanges.
  - **Use when:** you need guarantees — KYC, scheduling, payment, structured handoffs, anything you'd write a test for.

**A common pattern.** Real agents mix both modes:

```
   ┌─────────┐     ┌─────────────┐     ┌───────────┐     ┌──────┐
   │ Dynamic │ ──► │ Task Blocks │ ──► │ Condition │ ──► │ End  │
   │ opener  │     │ collect KYC │     │ qualified?│     └──────┘
   └─────────┘     └─────────────┘     └─────┬─────┘
                                             │ no
                                             ▼
                                       ┌──────────┐
                                       │ Transfer │
                                       └──────────┘
```

Start dynamic for the opener; flip Steps mode on the moment you can write a test you care about and the dynamic node can't pass it reliably.

---

## Configure / Agents / Editing the steps

When **Steps mode** is on, click **Edit Steps** (or navigate directly to `/agents/{agent_id}/nodes/{node_id}/v2`).

The steps detail page lists every step in the node's flow as a numbered row. A representative 8-step **Main Flow** (a `LEAF` node) doing a reservation-confirmation call:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ← Back to v1   │   Kanban v2   │   PHASE 5 · ADD STEP + POLISH              │
│                                                                              │
│  ╭─ Main Flow  [LEAF]                                                    8 ─╮│
│  │                                                                          ││
│  │  1   ▣  Set    customer_type_api               to   owner               ││
│  │  2   ▣  Set    customer_reservation_dates_api  to   July 27th to Aug 15 ││
│  │  3   ▣  Set    resort_name_api                 to   Hanalei Bay Resort  ││
│  │  4   ▣  Set    customer_first_name_api         to   Traci               ││
│  │  5   ▤  Collect confirm_first_name  [Exact Script ▾]                    ││
│  │             "Hello, this is an AI Agent on a recorded line calling      ││
│  │              on behalf of Hanalei Bay Resort regarding your upcoming    ││
│  │              reservation. Am I speaking with Traci?"                    ││
│  │  6   ▦  IF  >  Confirmed identity · 3 steps        [Resolution-driving] ││
│  │  7   ▦  IF  >  Wants callback → #15 · 1 step                            ││
│  │  8   ✂  Exact Script ▾                                                  ││
│  │             "No problem. A Vacation Specialist will call you back       ││
│  │              at a better time. Thank you."                              ││
│  │                                                                          ││
│  │  Press for instructions                                                  ││
│  ╰──────────────────────────────────────────────────────────────────────────╯│
│  ↓ Continues to next node                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

Each row has a colored icon indicating step type, a label (the step's `name` or generated summary), and any inline configuration (variable name, script mode, branch summary).

Step types you'll author here:

- **Set** *(green)* — assign a value to a variable. Often used to capture a value coming from an external API call into a workflow variable.
- **Collect** *(orange)* — prompt the user, then capture and validate a typed variable (Phone, Email, Number, Address, free text, …). The prompt can be free-form (LLM rephrases) or **Exact Script** (verbatim).
- **IF** *(yellow)* — branch on a variable, business-hours check, or LLM-judged condition. The branch summary shows how many sub-steps it owns (e.g. `· 3 steps`) and can be tagged (e.g. `Resolution-driving`).
- **Exact Script** *(red)* — say a verbatim line. Often the terminal step in a flow, or used anywhere phrasing is compliance-mandated.
- **Transfer**, **End conversation**, **Integration**, **Custom prompt**, **Speak**, **Set value** — additional types available from the add-step picker (click between rows or use the "+" button at the bottom of the list).

The header above the list shows breadcrumbs (`← Back to v1`), the node name, and a phase tag from the agent's authoring lifecycle. The number on the right of the header (here `8`) is the step count.

**Press for instructions** at the bottom of the page expands inline help for whichever step is selected. **Continues to next node** under the panel indicates that if none of the IF branches fire, control falls through to the next workflow node.

---

## Configure / Connections

Path: `/settings/connections` (or **Configure → Connections** in the left nav).

Connections are **provider instances** the workspace authenticates against. The page is a simple table.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Integrations                                  [ ↻ Sync ]  [ + Add integration ]│
│                                                                              │
│  [ 🔍 Search integrations...                                              ]  │
│                                                                              │
│  Provider     Connection ID         Health         Last tested      Actions │
│  ─────────────────────────────────────────────────────────────────────────  │
│  Aws-Iam      93b56f54-548c-40...   ✓ Healthy      5/4/2026, 5:08 PM   ⋯    │
│  Twilio       69e42552-a3fc-4a...   ✓ Healthy      4/24/2026, 12:45 AM ⋯    │
│  Salesforce   8562cf72-6969-4e...   ✗ Unhealthy    5/11/2026, 5:08 AM  ⋯    │
└──────────────────────────────────────────────────────────────────────────────┘
```

Columns:

- **Provider** — the connection type (Aws-Iam, Twilio, Salesforce).
- **Connection ID** — opaque identifier, useful for support tickets and API calls.
- **Health** — `Healthy` (green) or `Unhealthy` (red), based on the most recent automated test.
- **Last tested** — when the most recent health check ran.
- **Actions (⋯)** — re-test, edit credentials, or remove the connection.

The **Sync** button forces a refresh of all rows' health status. **+ Add integration** opens the new-connection wizard.

We support three connection providers today:

| Provider | What it does | Used by |
|----------|--------------|---------|
| **Twilio** | Voice (SIP / phone) origination + termination | Phone Numbers, outbound calling |
| **AWS-IAM** | Programmatic access to Amazon Connect contact centers | Phone Numbers (Amazon Connect provider) |
| **Salesforce** | CRM read/write — accounts, contacts, opportunities, custom objects | Integration steps inside agents, Salesforce Atoms suite |

Unhealthy rows usually indicate a credential rotation, an expired sandbox, or a network blip. Use the row menu to re-test or rotate.

---

## Configure / Integrations / Seed Integration Suites

Path: `/settings/integrations` (or **Configure → Integrations** in the left nav).

Integrations are reusable **suites of integration scenarios** that exercise a connection. They live next to test suites conceptually, but target external systems instead of the agent itself.

The Integrations page header has a **Seed integration suites** button. Click it to open the seeding dialog.

```
┌──────────────────────────────────────────────────┐
│  Seed integration suites                         │
├──────────────────────────────────────────────────┤
│  Pick a catalogue suite to seed into this        │
│  workspace.                                      │
│                                                  │
│  [x]  Salesforce Atoms                           │
│  [x]  Twilio Atoms                               │
│  [ ]  AWS-IAM Atoms                              │
│  [ ]  Nango Generic                              │
│                                                  │
│  [ Cancel ]              [   Seed   ] ◄── click  │
└──────────────────────────────────────────────────┘
```

The catalogue ships curated suites — one per supported provider. Tick the ones you want and click **Seed**. The selected suites appear in the Integrations list, ready to run.

The pattern mirrors test-suite seeding (see **Monitor / Test Suites** below); the difference is that integration suites target external connections rather than the agent itself.

---

## Configure / Integrations / Salesforce Atoms

Click into a seeded suite — e.g. **Salesforce Atoms**. The detail page opens.

```
┌───────────────────────────────────────────────────────────────────────┐
│  ←   🧩  Salesforce Atoms                          [ ▷ Run All ]  🗑  │
│                                                                       │
│  Reusable per-endpoint Salesforce smoke tests. Each atom exercises    │
│  one Nango-proxied Salesforce REST endpoint with canned mock          │
│  responses in simulation mode and live execution against a sandbox    │
│  connection under ``execution`` mode.                                 │
│                                                                       │
│  [ Scenarios ]   Runs                                                 │
│  ─────────────                                                        │
│  ID      Name                Active        Version       Actions      │
│  ─────────────────────────────────────────────────────────────────── │
│  #232    auth_check          [● Active]    v1              ▷         │
│  #233    create_record       [● Active]    v1              ▷         │
│  #234    delete_record       [● Active]    v1              ▷         │
│  #235    describe_object     [● Active]    v1              ▷         │
│  #236    get_record_by_id    [● Active]    v1              ▷         │
│  #237    query_soql          [● Active]    v1              ▷         │
│  #238    update_record       [● Active]    v1              ▷         │
│                                                                       │
│  7 scenarios                                  ◀  Page 1 of 1  ▶      │
└───────────────────────────────────────────────────────────────────────┘
```

Salesforce Atoms is a set of **reusable per-endpoint Salesforce smoke tests**. Each atom exercises one Nango-proxied Salesforce REST endpoint, with canned mock responses in **simulation mode** and live execution against a sandbox connection in **execution mode**.

The page has two tabs:

- **Scenarios** — every scenario in the suite, with `ID`, `Name`, an `Active` toggle, a `Version` chip, and a per-row run button.
- **Runs** — historical runs (mock or live), with timing, status, and per-scenario results.

The seven shipped atoms cover the common Salesforce ops:

| ID  | Atom | Exercises |
|-----|------|-----------|
| #232 | `auth_check`        | OAuth token round-trip |
| #233 | `create_record`     | `POST /sobjects/{Type}` |
| #234 | `delete_record`     | `DELETE /sobjects/{Type}/{id}` |
| #235 | `describe_object`   | `GET /sobjects/{Type}/describe` |
| #236 | `get_record_by_id`  | `GET /sobjects/{Type}/{id}` |
| #237 | `query_soql`        | `GET /query?q=...` |
| #238 | `update_record`     | `PATCH /sobjects/{Type}/{id}` |

---

## Configure / Integrations / Run

Two ways to kick off scenarios in any integration suite:

- **Run All** — the black `▷ Run All` button in the top-right of the suite page. Runs every active scenario in order; results land under the **Runs** tab.
- **Run a single scenario** — click the **▷ (play)** icon at the end of any scenario row. Useful for iterating on one atom without waiting for the others.

Toggle a scenario off via the **Active** switch to skip it during **Run All** without removing it from the suite. The pagination at the bottom shows the total count and lets you walk through suites with many scenarios.

The trash icon (top-right, next to **Run All**) retires the entire suite. Retired suites can be restored from the Integrations retired page, same pattern as test suites below.

---

## Monitor / Test Suites / Seed test suites

Path: `/tests`.

```
┌──────────────────────────────────────────────────────────────┐
│  Tests                                  [ + Seed test suites ]│ ◄── click
│  ──────────────────────────────────────────────────────────  │
│  [ ]  Title                Pass    Last run    Retired (3) ▸ │
│  ──────────────────────────────────────────────────────────  │
│  [ ]  Smoke Tests          12/12   2h ago               ⋯    │
│  [ ]  Onboarding Flow       8/8    1d ago               ⋯    │
└──────────────────────────────────────────────────────────────┘
```

Clicking **Seed test suites** opens a dialog with a catalogue of curated suites. Tick the ones you want and click **Seed**.

```
┌────────────────────────────────────┐
│  Seed test suites                  │
├────────────────────────────────────┤
│  [x] Smoke Tests                   │
│  [x] Phone collection              │
│  [ ] Address collection            │
│  [ ] Transfer-to-human             │
│                                    │
│  [ Cancel ]      [   Seed   ] ◄────┼── click
└────────────────────────────────────┘
```

---

## Monitor / Test Suites / Run All Tests

On any suite row, click the **⋯** menu and pick **Run All Tests**.

```
   ⋯  ◄── click
   ┌──────────────────┐
   │ Run All Tests    │ ◄── kicks off every scenario in the suite
   │ Export           │
   │ Retire           │
   └──────────────────┘
```

Click into the suite to watch progress — each scenario shows pass / fail / running as it executes.

---

## Monitor / Test Suites / Retire (soft-delete) a suite

Tick rows with the checkboxes, then click **Retire** in the toolbar that appears.

```
┌──────────────────────────────────────────────────────────────┐
│  [ x  3 selected ]   [ Retire ] ◄── click                    │
│  ──────────────────────────────────────────────────────────  │
│  [x]  Smoke Tests                                            │
│  [x]  Onboarding Flow                                        │
│  [x]  Edge Cases                                             │
└──────────────────────────────────────────────────────────────┘
```

Retired suites disappear from the main list but are not deleted.

---

## Monitor / Test Suites / Restore a retired suite

Click **Retired (N) ▸** in the page header.

```
┌──────────────────────────────────────────────────────────────┐
│  Tests / Retired                       [ ← Back to active ]  │
│  ──────────────────────────────────────────────────────────  │
│  [ x  2 selected ]   [ Restore ] ◄── click                   │
│  ──────────────────────────────────────────────────────────  │
│  [x]  Old Smoke Tests          retired 2d ago                │
│  [x]  Deprecated Flow          retired 1w ago                │
└──────────────────────────────────────────────────────────────┘
```

Restored suites reappear on the main Tests page.

---

## Deploy / Phone Numbers

Path: `/phone-numbers`.

The Phone Numbers page is the deployment surface — every number that can ring or be rung from this workspace. A typical view:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Phone Numbers                                              [ + Import number ] │
│                                                                                 │
│  Phone Number          Inbound Agent                              Webhooks      │
│  ─────────────────────────────────────────────────────────────────────────────  │
│  📞  +12142240222     Outbound Reservation Confirmation              —        ⋯│
│      amazon connect    (BH + Escalation + Global Listener) - v19                │
│      number                                                                     │
│                                                                                 │
│  📞  +13802203369     Outbound Reservation Confirmation       ✓ Webhooks live ⋯│
│      GPR ResCon        (BH + Escalation + Global Listener) - v19                │
│                                                                                 │
│  📞  +13187128019     Outbound Debt Collection                ◴ Pending       ⋯│
│      ZenLabs Dev Bot    (Listener + Escalation + Business Hours) - v12           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Columns:

- **Phone Number** — the E.164 number, with a short provider/workspace label underneath (e.g. `amazon connect number`, `GPR ResCon`, `ZenLabs Dev Bot`).
- **Inbound Agent** — the agent that picks up incoming calls on this number, including version (e.g. `Outbound Reservation Confirmation (BH + Escalation + Global Listener) - v19`). Blank if no agent is bound yet.
- **Webhooks** — status of the carrier webhook plumbing: `✓ Webhooks live` (green) means inbound events have been observed; `Pending` (gray) means the number is provisioned but no inbound event has flowed yet; `—` means the provider doesn't use webhooks (typical for Amazon Connect, where events route through the contact flow instead).

Use the row menu (`⋯`) to rebind the inbound agent, re-test webhooks, or remove the number.

---

## Deploy / Import Phone Number

Click **+ Import number** in the top-right of the Phone Numbers page. A dialog opens.

```
┌───────────────────────────────────────────────────┐
│  📞  Import phone number                       ✕  │
│                                                   │
│  Pick a provider, then attach a number and        │
│  optionally assign an inbound agent.              │
│                                                   │
│  Provider                                         │
│  [ Twilio                                    ▾ ]  │
│                                                   │
│  Phone number                                     │
│  [ +1 555 123 4567                             ]  │
│                                                   │
│  Label (optional)                                 │
│  [ e.g. Main Office, Support Line              ]  │
│                                                   │
│  Twilio connection                                │
│  [ Select a Twilio connection                ▾ ]  │
│                                                   │
│  Inbound agent (optional)                         │
│  [ Assign later                              ▾ ]  │
│                                                   │
│                       [ Cancel ]   [  Import  ]   │
└───────────────────────────────────────────────────┘
```

The dialog header reads *"Pick a provider, then attach a number and optionally assign an inbound agent."* The fields below the **Provider** dropdown change depending on which provider you pick.

---

## Deploy / Import Phone Number / Provider: Twilio

For a Twilio number you already own in your Twilio account:

1. **Provider** → `Twilio`.
2. **Phone number** → enter in E.164 format, e.g. `+1 555 123 4567`.
3. **Label (optional)** → human label such as `Main Office` or `Support Line`. Shown in the list under the number.
4. **Twilio connection** → pick a Twilio connection from the dropdown. (Set this up first under **Configure → Connections** if the dropdown is empty.)
5. **Inbound agent (optional)** → bind an agent now, or pick **Assign later** and bind from the agent detail page.
6. Click **Import**. The dialog provisions the number, wires up the Twilio voice webhook (so inbound calls reach ZenLabs), and the row appears with `Pending` webhooks status until the first test call flows through. Once a real call has hit the webhook, the status flips to `✓ Webhooks live`.

---

## Deploy / Import Phone Number / Provider: Amazon Connect

For a number that lives in your Amazon Connect instance:

1. **Provider** → `Amazon Connect`.
2. **Phone number** → the claimed number in your Amazon Connect instance, E.164 format.
3. **Label (optional)** → as above. Imports from Amazon Connect typically render in the list with the label `amazon connect number` underneath the E.164 if no override is provided.
4. **AWS-IAM connection** → pick the connection that has IAM credentials with the necessary `connect:*` permissions on your instance. (Set this up first under **Configure → Connections**.)
5. **Connect instance / contact flow** → pick the Amazon Connect instance and the contact flow that should route inbound calls into ZenLabs.
6. **Inbound agent (optional)** → as above.
7. Click **Import**. The dialog associates the number with the contact flow and registers the ZenLabs lambda as the contact-flow target. Because Amazon Connect doesn't expose a "webhook" in the Twilio sense, the **Webhooks** column for these rows shows `—` rather than `Webhooks live`. Health is verified instead by the linked AWS-IAM connection's last-tested timestamp.

---

## Quick navigation cheat sheet

| You want to… | Click path |
|--------------|------------|
| Sign in | `Email + Password → Sign in` |
| Change workspace | `Top bar → Workspace name → pick another` |
| Add a workspace secret | `Settings → Workspace Secrets → + Add secret` |
| Browse agents | `Configure → Agents` |
| Import an agent YAML | `Agents → + Import → drop file → Import` |
| Review agent settings | `Agents → click agent → Settings rail on right` |
| Preview an agent | `Agent detail → Preview ▾ → Inline / Widget` |
| Toggle Dynamic ↔ Task Blocks | `Open node → Steps mode toggle` |
| Edit step list | `Open node → Edit Steps  (path: /agents/{id}/nodes/{nid}/v2)` |
| Browse connections | `Configure → Connections` |
| Add a connection | `Connections → + Add integration` |
| Seed integration suites | `Configure → Integrations → Seed integration suites` |
| Run all integration scenarios | `Integration suite page → ▷ Run All` |
| Run one integration scenario | `Integration suite page → ▷ on the row` |
| Browse tests | `Monitor → Tests` |
| Seed test suites | `Tests → + Seed test suites → Seed` |
| Run every scenario in a suite | `Tests → ⋯ on row → Run All Tests` |
| Retire test suites | `Tests → tick rows → Retire` |
| Restore retired suites | `Tests → Retired (N) → tick rows → Restore` |
| Browse phone numbers | `Deploy → Phone Numbers` |
| Import a Twilio number | `Phone Numbers → + Import number → Twilio` |
| Import an Amazon Connect number | `Phone Numbers → + Import number → Amazon Connect` |
