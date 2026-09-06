---
name: benchmarks
description: Recall's measured benchmark results — the 11-scenario resolution baseline (B³/pairwise), the EIG vs random vs uncertainty question-efficiency table, the fixture inventory, and the post-fix business-bundle sweeps. Read before quoting, re-running, or comparing any eval number, and to get the thresholds that must be quoted alongside every result.
---

# Recall benchmark results

Every number here is a dated measurement. **Quote the thresholds in force with any
result** — they are listed with the resolution baseline below. `temperature=0` is not
determinism on Bedrock, so report variance, not a single run.

### Resolution baseline — re-measured 3 Sep (11 scenarios), `repeats=3`

Thresholds in force: `T_MATCH=3.0`, `T_NONMATCH=1.0`, `MIN_MARGIN=1.0`, `W_NAME_EXACT=2.5`,
`NAMELESS_CEILING=2.5`. Quote them with any result.

| scenario              | B³ F1        | B³ P  | B³ R  | pair F1 | subst | covrg |
| --------------------- | ------------ | ----- | ----- | ------- | ----- | ----- |
| `partner_notes`       | 0.968 ±0.000 | 1.000 | 0.938 | 0.933   | 0.970 | 0.938 |
| `account_notes`       | 0.962 ±0.000 | 1.000 | 0.926 | 0.929   | 0.944 | 0.944 |
| `ehoc_c4`             | 0.924 ±0.059 | 0.989 | 0.870 | 0.850   | 0.959 | 0.954 |
| `conference_notes`    | 0.916 ±0.022 | 1.000 | 0.846 | 0.859   | 0.944 | 0.944 |
| `arc_godwin`          | 0.877 ±0.000 | 0.947 | 0.816 | 0.667   | 0.952 | 0.947 |
| `site_visit_notes`    | 0.870 ±0.025 | 1.000 | 0.771 | 0.719   | 0.971 | 0.941 |
| `arc_sales`           | 0.865 ±0.000 | 1.000 | 0.762 | 0.615   | 0.933 | 0.929 |
| `client_followups`    | 0.865 ±0.034 | 1.000 | 0.763 | 0.682   | 0.946 | 0.939 |
| `arc_acacia`          | 0.775 ±0.026 | 1.000 | 0.633 | 0.493   | 0.873 | 0.857 |
| `same_first_name`     | 1.000        | 1.000 | 1.000 | 1.000   | 1.000 | 1.000 |
| `genuinely_ambiguous` | 1.000        | 1.000 | 1.000 | 1.000   | 1.000 | 1.000 |

`B³ F1 across all scenarios: 0.911 ±0.121 (n=33)` — no extraction failures this run.

**Precision is 1.000 on eight of eleven scenarios, and — the headline — on all five new
professional fixtures.** The B2B set was written with deliberate name collisions (two
Aarons at different banks, two Alexes, Cheryl Ng/Cheryl Wong, Darren Chia/Darren Chew,
Elena Loh/Elaine Low, Alisha Rahman/Alicia Yap); **none merged.** The only sub-1.000
precision is `ehoc_c4` (0.989) and `arc_godwin` (0.947), both the LLM adjudicator on
non-interactive runs, not the band (To fix #5d). This is the strongest evidence yet that
the resolver's precision is a property of the method, not of one student setting.

**Two things moved from the prior `0.918 ±0.095 (n=18)` baseline, and both are expected:**

- **The spread widened (±0.095 → ±0.121).** More scenarios, more range: the diagnostics
  sit at 1.000, `arc_acacia` at 0.775. Not a regression, just a wider sample.
- **`arc_acacia` recall fell (0.681 → 0.633).** This is the `NAMELESS_CEILING` policy
  (To fix #2) doing exactly what it was chosen to do: `arc_acacia` leans on descriptor-only
  references that now go to a question instead of auto-resolving. Recall is the cost of
  the "always ask when no name" trade, paid where descriptions carry the most weight.
  Precision there stayed 1.000.

**`arc_sales` and the B2B fixtures carry the professional-setting claim now.** B³ P = 1.000
across all of them — the case no student arc can test, because nobody in them has an
employer. Recall in the 0.76–0.94 band is the loose-reference half: company/role-only
mentions (`"the DBS transformation guy"`, `"the Axiata CRM director"`) are missed
recognitions, not wrong merges — the right direction to fail in, and the direction the
question path exists to fix. Quote `arc_sales`/`client_followups` with their memo counts —
both are ~10 memos, below `run_eval`'s ~20-memo "anecdote" warning, so cite the count.

The runtime ambiguous band flagged **294 mentions across the sweep**, far above the
9 labelled ambiguous. Names plus companies produce partial matches everywhere, and
`NAMELESS_CEILING` now holds every nameless match in the band too, so a professional
setting feeds the EIG denominator much harder than a hall does.

#### `arc_sales` question efficiency — a 4-way case, re-measured 3 Sep

`run_questions.py --scenario arc_sales --repeats 3`, after adding the three-way memo
(m12/m13: Wei Lin plus two GIC colleagues, then a nameless "someone from the GIC team"):

```
eig            0.750 ±0.000  (n=3)   100% <=1 question
uncertainty    0.750 ±0.000  (n=3)   100%
random         1.167 ±0.375  (n=3, min 0.750 max 1.500)   83%
```

Scorable cases per run: `[4, 4, 4]` — m2/m7/m10 at 2 hypotheses and **m13 at 4**. That
fourth case is the point: **EIG now beats random (0.75 vs 1.17)**, where the earlier
all-2-way version was a dead three-way tie (0.722 across the board). EIG still **ties
uncertainty sampling**, which is honest and expected — on a flat prior (all four GIC
records cap at `NAMELESS_CEILING`, so entropy is maximal) the two strategies often pick
the same question. Quote it as "EIG beats random, ties uncertainty here", never as EIG
losing.

**Why two hypotheses can never separate the strategies.** With exactly two candidates
every discriminating question is worth identical bits, so the argmax has nothing to
choose and all three strategies agree by construction — the same property that makes
`_spread()` show the worst question, not a plain top-N. A fixture needs a **3+**-hypothesis
case to exercise selection at all; m13 is that case, built by giving three people one
shared employer and then referring to them by it with no name.

`arc_sales` still is not the headline on its own (one fixture, four cases). The headline
stays the all-fixture table. But it now contributes to the question claim rather than only
the resolution one, and it is B³ P held while doing so — see the baseline table.

**A new baseline, not a delta.** The old `arc_acacia` figure (`B³ P=1.000 R=0.856
F1=0.922`, pairwise 0.800) is superseded and must not be compared against: three things
changed between the two measurements — `W_NAME_EXACT` 3.0 → 2.5, the name/descriptor
channel separation in `compare()`, and the eval scorer rewrite. Each is unit-tested
alone; no run separates their contribution to these numbers.

**Precision is a per-scenario claim, not a global one.** `arc_acacia` and `ehoc_c4` are
at 1.000 — nothing wrongly merged, every loss a missed recognition, the right direction
to fail in. The old blanket sentence _"precision had been 1.000 throughout"_ was **false
when written**: `arc_acacia` held a real wrong merge (`marvi`+`shiny`, see Hard-won
findings) that the broken scorer hid. `arc_godwin` sits at 0.947, and that loss is
**the LLM adjudicator, not the band** — see To fix #5d.

### Question efficiency — re-measured 3 Sep (11 scenarios), `repeats=3`

```
strategy       questions/resolution                       <=1 question
eig            0.862 ±0.037  (n=3, min 0.824  max 0.897)       78%
uncertainty    1.033 ±0.072  (n=3, min 0.985  max 1.129)       75%
random         1.129 ±0.008  (n=3, min 1.118  max 1.134)       69%
```

**The strongest version of the headline the project has produced.** ~69 scorable cases
across the three runs (~23/run), budget cap 5. **EIG's maximum (0.897) sits below both
baselines' minimums (uncertainty 0.985, random 1.118)** — the ranges do not overlap at
all, so `_verdict()` passes decisively. 26/69 of the chosen questions are multi-valued,
43/69 yes/no.

**Why this run separates the strategies where earlier ones barely did.** The B2B fixtures
supply many **3- and 4-hypothesis** ambiguous cases — e.g. `partner_notes/m6 'Fortinet
channel guy'` against four candidates, `client_followups/m8 'OCBC procurement guy'`
against three. With two candidates every discriminating question is worth the same bits
and all strategies tie; with three or four, the argmax has something to choose, and EIG's
choice is measurably better. The near-homophone name pairs are what manufacture those
multi-way ties. This is the result the enlarged fixture set was for.

**Claim "EIG beats both baselines."** Here it also beats them in order (EIG < uncertainty
< random) with clean separation, but keep the conservative claim — uncertainty and random
have swapped before at smaller n. What is solid and repeatable is that **EIG is first and
its range clears both.**

One caveat still travels with this table:

- **The denominator is coupled to the resolver.** `W_NAME_EXACT=2.5` and now
  `NAMELESS_CEILING=2.5` push bare-name and nameless returns into the ambiguous band, so
  resolution quality and question efficiency are **not independent results** and must not
  be written up as if they were. Fair across strategies (one case set per run), which is
  what the comparison rests on.

No extraction failures took down a run this sweep — the per-memo isolation (To fix #5a)
held across all 11 scenarios.

### Fixtures

**The default sweep is the eleven scenarios below: 114 memos, 234 mentions, 83 recurring
people.** The five-arc business bundle is a further 50 memos and lives in
`eval/fixtures/bundles/`, deliberately OUT of the default glob so the published tables
stay reproducible by the bare `run_eval.py` / `run_questions.py` commands printed beside
them — reach it with `--fixture`. `uv run eval/check_fixtures.py` validates all sixteen
(164 memos, 384 mentions, 119 recurring) and exits 0.

| Scenario              | memos | people | what it carries                                                                                                                                                       |
| --------------------- | ----- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `arc_acacia`          | 24    | 12     | the original arc, source of the resolution baseline                                                                                                                   |
| `arc_sales`           | 13    | 7      | **the first professional setting.** `company`/`role` populated and CONFLICTING, not silent. Two Alexes at different firms, one job change, three GIC people for a 4-way ambiguous case (m13), dated commitments in most memos |
| `arc_godwin`          | 14    | 20     | Luminia OG. **11 loose references**, 8 of which land in the ambiguous band — the EIG denominator. Four same-syllable name pairs                                       |
| `ehoc_c4`             | 11    | 14     | Eusoff Hall orientation. **13 recurring of 14** — the densest recognition test. Four memos of descriptor-only references, and the fixture that exposed the scorer bug |
| `account_notes`       | 10    | 8      | **B2B accounts.** Two Aarons at different banks (Goh/DBS vs Lim/StanChart), heavy role/company loose refs, a job change (Sophia: Oceanic→NexPort), one 2-way Aaron ambiguity |
| `client_followups`    | 10    | 11     | customer follow-ups. Two Alexes again, densest cast (11 people), 3 passing mentions                                                                                    |
| `conference_notes`    | 10    | 8      | three-day conference. **Near-homophone pairs** Raymond Lee/Ray Lim, Cheryl Ng/Cheryl Wong, Farid Hassan/Farah Aziz — the precision landmines                          |
| `partner_notes`       | 9     | 9      | MY/SG partners. Four near-collision pairs (Vikram/Victor, Ben Lim/Bernard Low, Nur Aisyah/Noor Aziz, Alisha Rahman/Alicia Yap)                                         |
| `site_visit_notes`    | 9     | 9      | site visits. Darren Chia/Darren Chew, Elena Loh/Elaine Low — same/near-same names that must not merge                                                                  |
| `same_first_name`     | 2     | 2      | precision diagnostic. Merged two Alexes until 28 Aug; now 1.000                                                                                                       |
| `genuinely_ambiguous` | 2     | 1      | two memos, one scored mention                                                                                                                                         |

**The five `*_notes` / `*_followups` fixtures are a professional B2B set added 3 Sep**
(banks, logistics, insurance, regional partners). They are the direct answer to the
"benchmark rests on one kind of setting" caveat: real employers that agree AND conflict,
and deliberate near-homophone name pairs that stress precision in a way the student arcs
cannot. `account_notes` measured B³ P=1.000 on its first run — the two Aarons did not merge.

The `ambiguous` counter in `check_fixtures.py` reads the **label**, not the runtime band.
`arc_godwin`'s eight scorable references are labelled `ambiguous: false` on purpose — you
know the answer, the resolver does not. Do not chase that progress bar by adding
`UNRESOLVED` mentions; those cannot separate EIG from random.

---


---

## Post-fix business-bundle sweeps

Regression measurements on the 50-memo five-arc bundle. **Not a replacement for the
11-scenario headline table above.**

#### Post-fix business-fixture resolution sweep — 3 Sep, `repeats=3`

`uv run eval/run_eval.py --fixture eval/fixtures/bundles/recall_business_guideline_50.yaml`
now runs the five-scenario YAML bundle directly. The fixture has **50 memos** in five
independent, ten-memo professional arcs; its result is a post-fix regression measurement,
not a replacement for the existing 11-scenario headline table.

| scenario | B3 F1 | B3 P | B3 R | pair F1 | substantive | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `arc_consulting` | 0.846 ±0.107 | 1.000 | 0.745 | 0.795 | 0.955 | 0.827 |
| `arc_enterprise_sales` | 0.905 ±0.000 | 1.000 | 0.827 | 0.881 | 0.920 | 0.923 |
| `arc_founder_investor` | 0.884 ±0.060 | 1.000 | 0.796 | 0.823 | 0.935 | 0.905 |
| `arc_partnership_events` | 0.839 ±0.018 | 0.971 | 0.739 | 0.760 | 0.943 | 0.919 |
| `arc_recruiting` | 0.849 ±0.045 | 1.000 | 0.739 | 0.753 | 0.964 | 0.963 |

**B3 F1 across the 15 scenario/repeat measurements: 0.865 ±0.117** (min 0.704, max
0.937). Four arcs held 1.000 precision; the `arc_partnership_events` loss is a
non-interactive adjudicator outcome, not an automatic resolver merge. The runtime band
flagged 241 mentions against five labelled ambiguities, and two malformed extractions
(`arc_consulting/m10`, `arc_founder_investor/m10`) were isolated rather than taking down
their repeats. The suite proves the post-fix pipeline runs on professional arcs; it does
not replace the existing 11-scenario resolution baseline.

#### Post-fix business-fixture question sweep — 4 Sep, `repeats=3`

`uv run eval/run_questions.py --fixture eval/fixtures/bundles/recall_business_guideline_50.yaml`
collected **[64, 63, 64]** scorable ambiguous cases across the three full pipeline runs
(191 total). No memos dropped during this sweep; 36 of the first run's 64 selected
questions were multi-valued.

| strategy | questions / resolution | resolved in ≤1 question |
| --- | ---: | ---: |
| EIG | **1.069 ±0.041** (min 1.016, max 1.097) | **74%** |
| uncertainty | 1.261 ±0.076 (min 1.188, max 1.339) | 71% |
| random | 1.353 ±0.097 (min 1.226, max 1.419) | 60% |

EIG is first and its displayed range clears both baselines. However, `_verdict()` uses
the **largest** strategy spread (0.19, from random) against the EIG-to-baseline mean
gap and therefore printed **inconclusive**. Preserve both statements: the observed
ordering and ranges are encouraging, while the harness's conservative, pre-existing
verdict does not authorize a stronger new claim without more repeats.
