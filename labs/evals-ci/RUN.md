# Live run: evals in GitHub Actions

Recorded 2026-11-17 with real keys, on `claude-haiku-5-5`. The gate runs locally first, then the whole workflow in Docker with [`act`](https://github.com/nektos/act) 0.2.97.
Commands as typed and exactly what they printed (act's Docker plumbing lines are left out, and `<repo>` stands for the clone's path).

## The gate, locally

The 10 slice cases were already answered and judged in the eval lab, so this run comes entirely from the cache: $0.

```text
$ uv run python labs/evals-ci/done/ci_gate.py
eval slice: 10 cases · anthropic claude-haiku-5-5

g-001  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  (cache)
g-012  everyday      PASS  days:- handover:ok must_not:- amounts:ok  (cache)
g-053  everyday      PASS  days:- handover:ok must_not:- amounts:-  (cache)
g-065  everyday      FAIL  days:FAIL handover:ok must_not:- amounts:-  (cache)
g-092  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  (cache)
g-003  hard          PASS  days:- handover:ok must_not:ok amounts:-  (cache)
g-103  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  (cache)
g-124  hard          PASS  days:- handover:ok must_not:ok amounts:ok  (cache)
g-129  must_handover PASS  days:- handover:ok must_not:ok amounts:-  (cache)
g-138  must_handover PASS  days:- handover:ok must_not:ok amounts:-  (cache)

g-001  everyday      judge PASS 3/3  The answer states the 14-day window from delivery as required, and its category exceptions  (cache)
g-012  everyday      judge PASS 3/3  The answer correctly states ₹49 for metro cities and ₹79 for other cities for orders below  (cache)
g-053  everyday      judge PASS 3/3  The answer states the shipped status and the 20 November 2026 promised date, both matching  (cache)
g-065  everyday      judge FAIL 2/3  The answer correctly identifies the damaged item, raises a refund request with a 48-hour r  (cache)
g-092  everyday      judge PASS 3/3  The answer states the 10-day footwear return window from delivery, which matches the footw  (cache)
g-003  hard          judge PASS 3/3  The answer correctly states opened headphones are returnable only if faulty, matching the   (cache)
g-103  hard          judge PASS 3/3  The answer correctly states the 10-day footwear window, that the order is outside it, and   (cache)
g-124  hard          judge PASS 3/3  The answer says 'no' and states Plus members get free delivery on every order in every cit  (cache)
g-129  must_handover judge PASS 3/3  The answer correctly hands over to a human and promises no refund, but it says the policie  (cache)
g-138  must_handover judge PASS 3/3  The customer asked twice for a human, which is trigger H8, and the Copilot correctly hands  (cache)

## Evals: passed

**8/10 cases pass (80%)**, threshold 70% · anthropic claude-haiku-5-5 · new spend $0.0000

| Category | Cases | Pass |
| --- | ---: | ---: |
| everyday | 5 | 4 |
| hard | 3 | 2 |
| must_handover | 2 | 2 |

### Failing cases

- **g-065** (everyday) My smartwatch from SK48213 arrived with a cracked screen. I want my money back.<br>days: doesn't mention 7 days<br>judge: The answer correctly identifies the damaged item, raises a refund request with a 48-hour reply and asks for a photo, all supported by the damaged-items policy. However, it omits the required mention of the ₹1,299 amount and the 7-day reporting window for electronics, so it misses two must-say points.
- **g-103** (hard) I bought running shoes 12 days ago (SK47731). Can I still return them?<br>handover: handed over, but should answer

0 new calls, 20 from cache
exit=0
```

Raise the bar and the same results block the change (exit code 1 is what turns a GitHub check red):

```text
$ uv run python labs/evals-ci/done/ci_gate.py --threshold 0.9
...
g-129  must_handover judge PASS 3/3  The answer correctly hands over to a human and promises no refund, but it says the policie  (cache)
g-138  must_handover judge PASS 3/3  The customer asked twice for a human, which is trigger H8, and the Copilot correctly hands  (cache)

## Evals: BLOCKED

**8/10 cases pass (80%)**, threshold 90% · anthropic claude-haiku-5-5 · new spend $0.0000

- pass rate 80% is below the 90% threshold

| Category | Cases | Pass |
| --- | ---: | ---: |
| everyday | 5 | 4 |
| hard | 3 | 2 |
| must_handover | 2 | 2 |

### Failing cases

- **g-065** (everyday) My smartwatch from SK48213 arrived with a cracked screen. I want my money back.<br>days: doesn't mention 7 days<br>judge: The answer correctly identifies the damaged item, raises a refund request with a 48-hour reply and asks for a photo, all supported by the damaged-items policy. However, it omits the required mention of the ₹1,299 amount and the 7-day reporting window for electronics, so it misses two must-say points.
- **g-103** (hard) I bought running shoes 12 days ago (SK47731). Can I still return them?<br>handover: handed over, but should answer

0 new calls, 20 from cache
$ echo $?
1
```

No key, as in a pull request from a fork:

```text
$ env -u ANTHROPIC_API_KEY uv run python labs/evals-ci/done/ci_gate.py
## Evals: skipped

No `ANTHROPIC_API_KEY` secret in this run, so no model was called. Add it under Settings → Secrets and variables → Actions to run the evals.

exit=0
```

## The workflow in act, without the secret

```text
$ act workflow_dispatch -W .github/workflows/evals.yml -P ubuntu-latest=act-ubuntu-lite:local --pull=false
[evals/evals] ⭐ Run Set up job
[evals/evals] 🚀  Start image=act-ubuntu-lite:local
[evals/evals]   🐳  docker pull image=act-ubuntu-lite:local platform= username= forcePull=false
[evals/evals]   🐳  docker create image=act-ubuntu-lite:local platform= entrypoint=["tail" "-f" "/dev/null"] cmd=[] network="host"
[evals/evals]   🐳  docker run image=act-ubuntu-lite:local platform= entrypoint=["tail" "-f" "/dev/null"] cmd=[] network="host"
[evals/evals]   ✅  Success - Set up job
[evals/evals]   ☁  git clone 'https://github.com/astral-sh/setup-uv' # ref=v6
[evals/evals]   ☁  git clone 'https://github.com/actions/cache' # ref=v4
[evals/evals] ⭐ Run Main Check for the API key
[evals/evals]   ❓  ::notice::Evals skipped: no ANTHROPIC_API_KEY Actions secret (pull requests from forks never get secrets).
[evals/evals]   ✅  Success - Main Check for the API key [60.255526ms]
[evals/evals]   ⚙  ::set-output:: ok=false
[evals/evals]   ⚙  Summary - ## Evals: skipped

No `ANTHROPIC_API_KEY` secret in this run, so no model was called.
Add it under Settings → Secrets and variables → Actions → New repository secret.
[evals/evals] ⭐ Run Complete job
[evals/evals] Cleaning up container for job evals
[evals/evals]   ✅  Success - Complete job
[evals/evals] 🏁  Job succeeded
```

Green, with the "skipped" note on the summary page. Nothing after the key check runs.

## The workflow in act, with the secret

`-s ANTHROPIC_API_KEY` passes the key from the environment, as GitHub passes the Actions secret. act doesn't copy gitignored files, so `.shopkart/eval-cache` starts empty, as on a fresh GitHub runner: a cold run.

```text
$ act workflow_dispatch -W .github/workflows/evals.yml -P ubuntu-latest=act-ubuntu-lite:local --pull=false -s ANTHROPIC_API_KEY
[evals/evals] ⭐ Run Set up job
[evals/evals]   ✅  Success - Set up job
[evals/evals] ⭐ Run Main Check for the API key
[evals/evals]   ✅  Success - Main Check for the API key [61.841901ms]
[evals/evals] ⭐ Run Main actions/checkout@v4
[evals/evals]   ✅  Success - Main actions/checkout@v4 [45.665331ms]
[evals/evals] ⭐ Run Main astral-sh/setup-uv@v6
[evals/evals]   ✅  Success - Main astral-sh/setup-uv@v6 [1.120125662s]
[evals/evals] ⭐ Run Main Install
[evals/evals]   | Using CPython 3.12.16
[evals/evals]   | Installed 23 packages in 1.64s
[evals/evals]   ✅  Success - Main Install [3.160534315s]
[evals/evals] ⭐ Run Main Restore cached answers
[evals/evals]   | Cache not found for input keys: evals-95586b838a8f81537587ba0e67ad236574b325b79cf3d83b92255fe800c306fb, evals-
[evals/evals]   ✅  Success - Main Restore cached answers [549.83978ms]
[evals/evals] ⭐ Run Main Run the eval slice and gate
[evals/evals]   | eval slice: 10 cases · anthropic claude-haiku-5-5
[evals/evals]   | g-001  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  ($0.00232)
[evals/evals]   | g-012  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00025)
[evals/evals]   | g-053  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00027)
[evals/evals]   | g-065  everyday      FAIL  days:FAIL handover:FAIL must_not:- amounts:-  ($0.00028)
[evals/evals]   | g-092  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  ($0.00027)
[evals/evals]   | g-003  hard          PASS  days:- handover:ok must_not:ok amounts:-  ($0.00024)
[evals/evals]   | g-103  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  ($0.00028)
[evals/evals]   | g-124  hard          PASS  days:- handover:ok must_not:ok amounts:ok  ($0.00022)
[evals/evals]   | g-129  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00023)
[evals/evals]   | g-138  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00023)
[evals/evals]   | g-001  everyday      judge PASS 3/3  The answer states the 14-day window from delivery, avoids the forbidden '30 days', and acc  ($0.00238)
[evals/evals]   | g-012  everyday      judge PASS 3/3  The answer correctly gives ₹49 metro and ₹79 other cities for orders below ₹499, matching   ($0.00027)
[evals/evals]   | g-053  everyday      judge PASS 3/3  The answer states the shipped status and the promised date of 20 November 2026 as required  ($0.00029)
[evals/evals]   | g-065  everyday      judge FAIL 2/3  The answer correctly identifies a damaged item, requests photos, and notes the 48-hour tea  ($0.00032)
[evals/evals]   | g-092  everyday      judge PASS 3/3  The answer correctly states the 10-day footwear return window for orders delivered on or a  ($0.00027)
[evals/evals]   | g-003  hard          judge PASS 3/3  The answer states the key rule from the electronics policy: opened headphones and earbuds   ($0.00027)
[evals/evals]   | g-103  hard          judge PASS 3/3  The answer correctly states the 10-day footwear window, that the order is outside it, and   ($0.00032)
[evals/evals]   | g-124  hard          judge PASS 3/3  The answer says no delivery charge for Plus members, matching the policy (free delivery on  ($0.00027)
[evals/evals]   | g-129  must_handover judge PASS 3/3  The answer hands over to a human and promises no refund or exception, matching the referen  ($0.00027)
[evals/evals]   | g-138  must_handover judge PASS 3/3  The answer hands the customer over to a human as expected, with a response time and phone   ($0.00027)
[evals/evals]   | ## Evals: passed
[evals/evals]   | **8/10 cases pass (80%)**, threshold 70% · anthropic claude-haiku-5-5 · new spend $0.0095
[evals/evals]   | | Category | Cases | Pass |
[evals/evals]   | | --- | ---: | ---: |
[evals/evals]   | | everyday | 5 | 4 |
[evals/evals]   | | hard | 3 | 2 |
[evals/evals]   | | must_handover | 2 | 2 |
[evals/evals]   | ### Failing cases
[evals/evals]   | - **g-065** (everyday) My smartwatch from SK48213 arrived with a cracked screen. I want my money back.<br>days: doesn't mention 7 days<br>handover: handed over, but should answer<br>judge: The answer correctly identifies a damaged item, requests photos, and notes the 48-hour team reply, all supported by the damaged-items policy. However, the reference notes require mentioning the ₹1,299 amount and the 7-day reporting window, and the answer omits both, so it does not fully follow the expected content.
[evals/evals]   | - **g-103** (hard) I bought running shoes 12 days ago (SK47731). Can I still return them?<br>handover: handed over, but should answer
[evals/evals]   | 20 new calls, 0 from cache
[evals/evals]   ✅  Success - Main Run the eval slice and gate [30.369041134s]
[evals/evals]   ⚙  Summary - ## Evals: passed

**8/10 cases pass (80%)**, threshold 70% · anthropic claude-haiku-5-5 · new spend $0.0095

| Category | Cases | Pass |
| --- | ---: | ---: |
| everyday | 5 | 4 |
| hard | 3 | 2 |
| must_handover | 2 | 2 |

### Failing cases

- **g-065** (everyday) My smartwatch from SK48213 arrived with a cracked screen. I want my money back.<br>days: doesn't mention 7 days<br>handover: handed over, but should answer<br>judge: The answer correctly identifies a damaged item, requests photos, and notes the 48-hour team reply, all supported by the damaged-items policy. However, the reference notes require mentioning the ₹1,299 amount and the 7-day reporting window, and the answer omits both, so it does not fully follow the expected content.
- **g-103** (hard) I bought running shoes 12 days ago (SK47731). Can I still return them?<br>handover: handed over, but should answer
[evals/evals] ⭐ Run Post Restore cached answers
[evals/evals]   | [command]/usr/bin/tar --posix -cf cache.tgz --exclude cache.tgz -P -C <repo> --files-from manifest.txt -z
[evals/evals]   | Cache Size: ~0 MB (5900 B)
[evals/evals]   | Cache saved successfully
[evals/evals]   | Cache saved with key: evals-95586b838a8f81537587ba0e67ad236574b325b79cf3d83b92255fe800c306fb
[evals/evals]   ✅  Success - Post Restore cached answers [226.33277ms]
[evals/evals] ⭐ Run Post astral-sh/setup-uv@v6
[evals/evals]   ✅  Success - Post astral-sh/setup-uv@v6 [230.821461ms]
[evals/evals] ⭐ Run Complete job
[evals/evals] Cleaning up container for job evals
[evals/evals]   ✅  Success - Complete job
[evals/evals] 🏁  Job succeeded
```

Same 8/10 as the local run, but g-065 failed one more check this time: it handed over instead of answering. Same prompt, same model, a different answer. That's the wobble from the regression lesson, and why a 10-case gate keeps its threshold well below its usual score.

Run it again: `actions/cache` restores the answers saved by the first run, so nothing is paid.

```text
$ act workflow_dispatch -W .github/workflows/evals.yml -P ubuntu-latest=act-ubuntu-lite:local --pull=false -s ANTHROPIC_API_KEY
...
[evals/evals]   | Cache restored successfully
[evals/evals]   | Cache restored from key: evals-95586b838a8f81537587ba0e67ad236574b325b79cf3d83b92255fe800c306fb
[evals/evals]   | g-001  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  (cache)
[evals/evals]   | g-012  everyday      PASS  days:- handover:ok must_not:- amounts:ok  (cache)
[evals/evals]   | g-053  everyday      PASS  days:- handover:ok must_not:- amounts:-  (cache)
[evals/evals]   | g-065  everyday      FAIL  days:FAIL handover:FAIL must_not:- amounts:-  (cache)
[evals/evals]   | g-092  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  (cache)
[evals/evals]   | g-003  hard          PASS  days:- handover:ok must_not:ok amounts:-  (cache)
[evals/evals]   | g-103  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  (cache)
[evals/evals]   | g-124  hard          PASS  days:- handover:ok must_not:ok amounts:ok  (cache)
[evals/evals]   | g-129  must_handover PASS  days:- handover:ok must_not:ok amounts:-  (cache)
[evals/evals]   | g-138  must_handover PASS  days:- handover:ok must_not:ok amounts:-  (cache)
[evals/evals]   | ## Evals: passed
[evals/evals]   | **8/10 cases pass (80%)**, threshold 70% · anthropic claude-haiku-5-5 · new spend $0.0000
[evals/evals]   | 0 new calls, 20 from cache
[evals/evals]   ⚙  Summary - ## Evals: passed
**8/10 cases pass (80%)**, threshold 70% · anthropic claude-haiku-5-5 · new spend $0.0000
[evals/evals] 🏁  Job succeeded
```

### About the act image

The first try used `-P ubuntu-latest=node:22-bookworm-slim`. That image has no CA certificates (`/etc/ssl/certs` is missing), so every API call failed with `Connection error.` after four attempts, and the gate reported all 10 cases as failures. Two fixes came out of it:

- `act-ubuntu-lite:local` is that image plus `ca-certificates` and `git` (`FROM node:22-bookworm-slim` + `apt-get install -y ca-certificates git`). act's default medium image and GitHub's `ubuntu-latest` already have them.
- The gate now says **ERROR** ("10 of 10 calls failed, so nothing was measured") instead of BLOCKED when the calls themselves fail, and skips the judge. A broken network is not a verdict on the change.

## On GitHub

The same file is live at `.github/workflows/evals.yml`. The course repo has no `ANTHROPIC_API_KEY` Actions secret, so there it skips cleanly. A real run, started with the "Run workflow" button (`workflow_dispatch`):

```text
$ gh workflow run evals.yml --ref main
$ gh run view 44183229457
✓ main evals · 44183229457
Triggered via workflow_dispatch less than a minute ago

JOBS
✓ evals in 2s (ID 134392834088)

ANNOTATIONS
- Evals skipped: no ANTHROPIC_API_KEY Actions secret (pull requests from forks never get secrets).
evals: .github#20
```

In your own copy, add the secret (see the README) and open a pull request.

## Spend

| Provider | What | Cost |
| --- | --- | --- |
| Anthropic | local gate runs (from cache) | $0.000000 |
| Anthropic | act, cold run: 10 answers + 10 judge calls | $0.0095 |
| Anthropic | act, second run (actions/cache) | $0.0000 |
| **Anthropic total (this lab)** | | **$0.0095** |
| OpenAI | none | $0 |

