TASK: Harden the Hallucination Investigation (Investigation Only, No Fixes)
MODE: No edits to core/, launchers, or .env. Scratch files are allowed.

STEP 0: Checkpoint
Run `git status -s` and `git diff --stat` in the repo root. Create a checkpoint commit of the current working tree on a new branch named `checkpoint/pre-hallucination-fix` (do not push). Report the commit hash. If the commit fails, stop and report why.

STEP 1: Server template check
Run `curl http://127.0.0.1:8080/props` (or the equivalent GET). Paste the full JSON. Report the `chat_template` field, or state that it is absent. State whether the server applies the Qwen template to the chat endpoint. Do not assume.

STEP 2: The 72-degree fabrication (highest priority)
Reproduce the Item 4 interruption setup: ask a long question, then interrupt with "Never mind, what's the weather?". Capture the full log for that turn, including:
  a. Whether any search or tool event fired for the weather question.
  b. The exact outgoing request for that turn.
  c. The response text, verbatim.
Report whether "72 degrees, sunny" appears anywhere in the logs, memory, or prompt. Search the whole repo and data/ for "72". Paste the matches with file:line. If the number is not found in any captured input, say the source is UNKNOWN and do not guess.

STEP 3: Repeated ablation (replaces the single-sample Step 6)
Using the captured request from the previous report, run each variant 10 times with fixed sampling (temperature 0, record top_p, max_tokens, seed if supported):
  V0 full prompt
  V1 no tone block
  V2 no personality block
  V3 no memory block
  V4 system and user split into separate roles (system = persona/tone, user = query), if the server template supports it
  V5 raw user-only, no system content
For each: count how many of 10 responses are correct for the query "What is 2 + 2?" and for "What is your name?". Report a table with counts, not single examples. Also paste one full example response per variant.

STEP 4: Missing row
Re-run the native-role row (V4) and report its result, since the earlier report left it blank.

STEP 5: Pinned-memory path
Find where pinned notes are read and whether they bypass the relevance filter. Capture one turn where a pinned note exists and the query is unrelated. Report included or excluded, with the code line that decides it. Then re-run the earlier "What did I tell you my name was?" case 5 times and report what was injected each time.

STEP 6: World Cup and location
  a. Report the search snippets verbatim (short quotes only), and mark the model's answer as faithful or unfaithful to them.
  b. Mark the truth of "Spain won 2026" as UNKNOWN unless a primary source is fetched. Use web_search on a primary source (FIFA) and paste its result.
  c. For location, capture the outbound request if possible. If not, mark the mechanism UNKNOWN.

STEP 7: Report
Give a table: hypothesis, the test, counts out of 10, status (CONFIRMED only if it meets the 9-of-10 rule, otherwise UNCONFIRMED). List every UNKNOWN with the evidence needed. Do not propose code changes.