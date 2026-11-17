# Lab: a local open model vs an API model on the Copilot eval suite

Run an open-weight model inside your Codespace with Ollama, plug it into the Copilot with almost no code changes, and put it next to `claude-haiku-5-5` on the same 20 golden questions: correctness, latency and cost.
It follows the lessons on open-weight models and on running models locally with Ollama.

```text
labs/local-model/
  Modelfile           the Copilot's local preset: model, context window, threads, temperature
  questions.json      20 golden questions (12 everyday, 4 hard, 4 must-hand-over) with code checks
  start/compare.py    your copy, with TODO 1–3
  done/compare.py     the finished answer
  tests/              the checkpoints, with no Ollama and no network
```

Runs the API side on Anthropic by default. For OpenAI add `--provider openai`.
The local side is $0 per token. The API side costs about a fifth of a US cent for 20 questions.

## 1. Install Ollama in the Codespace

A Codespace has 2 cores and 8 GB of memory, and no GPU. The installer needs `zstd`, and a Codespace has no systemd, so start the server yourself:

```bash
sudo apt-get update && sudo apt-get install -y zstd
curl -fsSL https://ollama.com/install.sh | sh
ollama serve > /tmp/ollama.log 2>&1 &
ollama --version
```

The download is about 1.5 GB, because it includes GPU libraries we won't use.

## 2. Pick a model that fits

```bash
ollama pull qwen2.5:1.5b
```

| model | download | licence | 2 cores, 20 questions | correct |
| --- | --- | --- | --- | --- |
| `qwen2.5:1.5b` | 986 MB | Apache 2.0 | 2.6 min | 13/20 |
| `qwen2.5:3b` | 1.9 GB | Qwen **Research** licence: not for commercial use | 5.2 min | 11/20 |
| `llama3.2:3b` | 2.0 GB | Llama 3.2 Community licence | 5.1 min | 14/20 |

All three fit in 8 GB. We use `qwen2.5:1.5b`: twice as fast as the 3B models, and a licence ShopKart can ship with. Note the trap in the middle row: same family name, different licence. Run `ollama show qwen2.5:3b --license` and read it.

## 3. A Modelfile for the Copilot

```bash
ollama create shopkart-local -f labs/local-model/Modelfile
ollama run --verbose shopkart-local "In two sentences, explain what a return window is for an online store, and why stores have one."
ollama ps
```

The Modelfile sets three things. None of them trains anything:

- `num_ctx 8192`: Ollama's default context is 4,096 tokens (`ollama ps` shows it), and a longer prompt is trimmed with no error. Set it, because the OpenAI-style endpoint can't change it per request.
- `num_thread 2`: one thread per core. In our test, Ollama counted the host's cores instead of the container's 2, started 16 threads, and crawled at **0.06 tokens a second**. With 2 threads: 8 to 11.
- `temperature 0`: the same answer every run, so the comparison is fair.

`--verbose` prints the speed. On 2 cores we saw the answer written at 8 to 11 tokens a second, and the prompt read at 15 to 50 (faster on longer prompts).

## 4. Same code, different address

**TODO 1.** In `local_llm`, point the Copilot's own `LLM` class at Ollama: an `openai.OpenAI` client with `base_url="http://localhost:11434/v1"`, any API key (the local server ignores it), and the model name. Register its price as $0 per token. Nothing else in the Copilot changes.

```bash
uv run python labs/local-model/start/compare.py --local shopkart-local --limit 2 --local-only
```

## 5. Check the answers in code

Both models get exactly the same prompt: the policy sections each golden question cites (retrieval done for them, so we compare the models and nothing else), the order record if there is one, and a fixed format, `VERDICT: yes | no | info | handover` then `ANSWER: ...`.

**TODO 2.** `check()` grades an answer with simple code checks from `questions.json`: the verdict must match, the key facts must be there (a regex such as `\b14\b` for the 14-day window), and the wrong ones must not (`30 days`).
A judge model is more flexible (that's the eval lessons); code checks are free and never change their mind.

## 6. Run both, and compare

**TODO 3.** `summary()`: correct answers, median and slowest latency, total time, and the **cost per 1,000 answers**. For the API model that's tokens. For the local model it's the machine: a 2-core Codespace costs $0.18 an hour, whether it's busy or not.

```bash
uv run python labs/local-model/start/compare.py --local shopkart-local
uv run python labs/local-model/start/compare.py --local shopkart-local --show g-127
```

In our run:

| | `shopkart-local` (qwen2.5:1.5b, 2 cores) | `claude-haiku-5-5` |
| --- | --- | --- |
| correct | 13/20 | 19/20 |
| median latency | 10.2 s | 1.0 s |
| 20 answers took | 204 s | 21 s |
| cost per 1,000 answers | $0.51 of Codespace time | $0.09 of tokens |

The small model got 13 of the 16 questions it should answer right: return windows, delivery fees, an order's status. It missed all 4 must-hand-over cases. Asked for a ₹9,499 refund, it wrote "Refund request raised" instead of handing over to a human (`--show g-127`).

**Checkpoint:** `LAB=start uv run pytest labs/local-model -q` passes.

## The hardware truth

- A 2-core CPU writes about 8 to 11 tokens a second with a 1.5B model, and about 5 with a 3B model. A 1,000-token prompt takes 5–20 seconds before the first word. Fine for one developer on a plane, not for a sale day with thousands of customers. Ollama answers one request at a time by default.
- A free model isn't a free answer. On this hardware the local model costs *more* per answer than Haiku, because the machine is slow and you pay for it by the hour. That changes with a GPU, a busy server, or a rule that the data can't leave your machine.
- Quality fell exactly where the lessons said it would: judgement calls and hand-overs, not plain facts. Your eval set, not a leaderboard, decides whether a local model is good enough for a job.
- Your numbers will differ. A shared or busy machine is slower: on our first try, another job on the same 2 cores made answers take 30 to 100 seconds.

The real output of a live run is in [RUN.md](RUN.md).
