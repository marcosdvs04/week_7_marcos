# DocuBot Model Card

This model card is a short reflection on your DocuBot system. Fill it out after you have implemented retrieval and experimented with all three modes:

1. Naive LLM over full docs  
2. Retrieval only  
3. RAG (retrieval plus LLM)

Use clear, honest descriptions. It is fine if your system is imperfect.

---

## 1. System Overview

**What is DocuBot trying to do?**  
Describe the overall goal in 2 to 3 sentences.

> DocuBot answers developer questions about a project using the project's own documentation (the `docs/` folder). It can answer three ways: by asking an LLM directly, by searching the docs and returning the matching sections, or by searching first and having the LLM answer only from what it found (RAG). The goal is answers that are grounded in the docs, and a refusal when the docs don't cover the question.

**What inputs does DocuBot take?**  
For example: user question, docs in folder, environment variables.

> A natural-language question from the CLI (or the built-in sample queries in `dataset.py`), the `.md`/`.txt` files in `docs/`, and the `GEMINI_API_KEY` environment variable loaded from `.env`. Without the key, only Mode 2 works.

**What outputs does DocuBot produce?**

> Mode 1: free-form LLM text. Mode 2: the top 3 matching doc sections, each labeled with its filename. Mode 3: a short LLM answer built only from the retrieved sections, naming the files it used. Modes 2 and 3 return "I do not know based on these docs." when retrieval finds no evidence.

---

## 2. Retrieval Design

**How does your retrieval system work?**  
Describe your choices for indexing and scoring.

- How do you turn documents into an index?
- How do you score relevance for a query?
- How do you choose top snippets?

> - **Chunking:** every document is split into markdown sections. Each heading line starts a new chunk and keeps its body, so code blocks inside a section stay together. Chunks that are only a heading (like `## Tables`) are dropped.
> - **Tokenizing:** text is lowercased and split on non-word characters. Stopwords ("where", "is", "the", "which"...) are removed, and a tiny suffix stemmer makes `generated`/`generation`, `users`/`user`, and `stored`/`stores` match.
> - **Index:** an inverted index maps each token to the files containing it (`{"token": ["API_REFERENCE.md", "AUTH.md", ...]}`). It narrows the search to candidate files before sections are scored.
> - **Scoring:** a section's score is the number of distinct query terms in it, plus 0.5 for each query term in the section's heading, plus 2 if a route in the query (e.g. `/api/projects/<project_id>`) is exactly the route in the heading.
> - **Selection:** sections below the evidence threshold are dropped. The rest are sorted by score, ties go to the shorter section, and the top 3 are returned.

**What tradeoffs did you make?**  
For example: speed vs precision, simplicity vs accuracy.

> - **Simplicity over recall:** keyword matching with no synonyms or embeddings. "sign in" will not find the `/api/login` section, and "credentials table" will not find `users`.
> - **Precision over completeness:** returning sections instead of whole files makes the evidence focused (the auth-token answer is the 15-line `## Token Generation` section, not all of AUTH.md), but an answer split across two sections can get cut by `top_k=3`.
> - **Hand-tuned weights:** the heading and route bonuses fixed real ranking mistakes (the users-table query, the `/api/projects/<project_id>` route), but they are tuned to this small corpus.
> - **Stemmer:** crude, but every token goes through the same function, so its mistakes are at least consistent (`access` becomes `acces` on both sides).

---

## 3. Use of the LLM (Gemini)

**When does DocuBot call the LLM and when does it not?**  
Briefly describe how each mode behaves.

- Naive LLM mode:
- Retrieval only mode:
- RAG mode:

> - **Model:** `gemini-3.5-flash-lite`. The starter's `gemini-flash-lite-latest` returned 404 (no longer available to this key), so `GEMINI_MODEL_NAME` in `llm_client.py` was updated.
> - **Naive LLM mode:** calls Gemini once per question. As written in `llm_client.py`, the prompt *ignores* the docs text and sends only the question, so every answer comes from the model's general knowledge.
> - **Retrieval only mode:** never calls the LLM. It prints the retrieved sections, or refuses.
> - **RAG mode:** runs retrieval first. If nothing clears the evidence threshold, it refuses *without* calling the LLM. Otherwise it sends only the top 3 sections to Gemini.

**What instructions do you give the LLM to keep it grounded?**  
Summarize the rules from your prompt. For example: only use snippets, say "I do not know" when needed, cite files.

> The RAG prompt tells Gemini to use only the provided snippets, not to invent functions, endpoints, or config values, to reply exactly "I do not know based on the docs I have." when the snippets aren't enough, and to name the files it relied on. Each snippet is labeled with its filename.

---

## 4. Experiments and Comparisons

Run the **same set of queries** in all three modes. Fill in the table with short notes.

You can reuse or adapt the queries from `dataset.py`.

| Query | Naive LLM: helpful or harmful? | Retrieval only: helpful or harmful? | RAG: helpful or harmful? | Notes |
|------|---------------------------------|--------------------------------------|---------------------------|-------|
| Where is the auth token generated? | Unhelpful: it never sees the docs, so it asks the user to paste the codebase. | Helpful: #1 is AUTH.md `## Token Generation` (`generate_access_token` in `auth_utils.py`). The other 2 results are related but redundant. | Helpful: "`generate_access_token` in `auth_utils.py`", cites AUTH.md. | Only RAG gives a direct, cited answer. |
| How do I connect to the database? | **Harmful:** confidently invents `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD` env vars. The project uses a single `DATABASE_URL`. | Helpful but scattered: the `DATABASE_URL` examples are in `## Connection Configuration`, while the doc intro ranks just as high and says little. | Helpful: `DATABASE_URL`, the SQLite default `app.db`, a PostgreSQL example, and `db.py`. | Clearest case of naive mode sounding sure while being wrong. |
| Which endpoint lists all users? | Harmful: says `GET /users` (wrong path, missing `/api`). | Helpful: #1 is `### GET /api/users`, including the admin-only note. #3 is DATABASE.md `get_all_users()`, a different layer that could confuse a reader. | Helpful: `GET /api/users`, cites API_REFERENCE.md. It leaves out that the endpoint is admin-only, even though that's in the snippet. | Plausible, close-but-wrong naive answer. |
| How does a client refresh an access token? | **Harmful:** a long, generic OAuth2 `grant_type=refresh_token` flow posting to `/oauth/token`. This project has no refresh tokens. | Correct but hard to read: #1 is `## Client Workflow` (step 4: call `/api/refresh`) and the actual `POST /api/refresh` spec is #3. The reader has to piece them together. | Partly helpful: "call `/api/refresh` when it expires" is correct, but it omits that it's a `POST` with the current token in `Authorization: Bearer`, which was in snippet #3. | RAG is grounded but incomplete. |
| Is there any mention of payment processing in these docs? | Unhelpful: asks the user to paste the docs. | Helpful: correctly refuses ("I do not know based on these docs."). | Helpful: refused by the retrieval guardrail, without calling the LLM. | Refusal is the right answer here. |
| What does the /api/projects/<project_id> route return? | **Harmful:** a made-up JSON example with `id`, `created_at`, `updated_at` and "Website Redesign". None of these are in the docs. | Helpful: the exact `GET /api/projects/<project_id>` section ranks #1, after the route-bonus fix. | Helpful: lists the documented fields `project_id`, `name`, `description`, `status`, `owner`. | |
| Which fields are stored in the users table? | **Harmful:** a Laravel-style schema (`name`, `email_verified_at`, `remember_token`...) introduced with "Based on the documentation", even though it never saw the docs. | Helpful: DATABASE.md `### users` table ranks #1. | Helpful: exactly `user_id`, `email`, `password_hash`, `joined_at` with types. | Worst naive case: a false claim to have read the docs. |

**What patterns did you notice?**  

- When does naive LLM look impressive but untrustworthy?  
- When is retrieval only clearly better?  
- When is RAG clearly better than both?

> **Retrieval only (observed):** always grounded and always says where its answer came from, and it refuses cleanly on off-topic questions. It is clearly better than naive mode for exact facts like function names, env vars, and routes, because it can't invent them. Its weakness is readability. You get raw markdown sections, and for multi-part questions (the refresh flow) the answer is spread across sections you have to combine yourself.
>
> **Naive LLM (observed):** most impressive and least trustworthy on "how" and "what fields" questions. It produced well-formatted env-var lists, JSON examples and an OAuth refresh flow, all generic and all wrong for this project. Once it even said "Based on the documentation" when it had never seen the docs (`naive_answer_over_full_docs` sends only the question). On "where is X" questions it just asked for the code, which is at least honest.
>
> **RAG (observed):** clearly better than both on every answerable sample question. It's short and readable like the LLM, but it uses this project's actual names (`DATABASE_URL`, `/api/users`, `password_hash`) and cites the file. It also inherits the retrieval guardrail: the payment question is refused before Gemini is ever called.
>
> **Where RAG still fails (observed):**
> - **Drops useful details:** for the refresh question it said "call `/api/refresh`" but left out the `POST` method and the `Authorization: Bearer` header, which were in the snippets. For the list-users question it left out "admin only". Being correct is not the same as being complete.
> - **False refusal from weak retrieval:** "How do I sign in?" retrieves AUTH.md `## Common Failure Cases` and two env-var sections, because "sign" matches "signed" and a one-term query needs only one match. Gemini correctly refused instead of guessing, but `/api/login` *is* documented. Better retrieval would have answered.
> - **Over-reading weak evidence:** asked "What happens to existing tokens when the secret key is rotated?", RAG answered from the "stale or rotated key" failure bullet and the "rotate the secret key" troubleshooting tip. That is a reasonable inference, but the docs never directly describe what happens to existing tokens, so a hedged answer would be more honest.

---

## 5. Failure Cases and Guardrails

**Describe at least two concrete failure cases you observed.**  
For each one, say:

- What was the question?  
- What did the system do?  
- What should have happened instead?

> **Users-table query (fixed).** Question: "Which fields are stored in the users table?" My first version returned only AUTH.md `## Token Generation`, which mentions "user ID" and "stored". The DATABASE.md `### users` section never says "table", and the stemmer turned "Stores" into `store` but "stored" into `stor`, so the right section only matched one term and fell under the threshold. It should have returned the `### users` table. Fix: the stemmer also drops a trailing `e`, and heading matches earn a bonus. It now ranks first.

> **Route-specific query (fixed).** Question: "What does the /api/projects/<project_id> route return?" The general `GET /api/projects` section ranked above `GET /api/projects/<project_id>`, because both mention `project_id` and only the general one contains the word "Returns". A reader would see the list endpoint first and could confuse the two. Fix: a +2 bonus when the exact route in the query is the route in a heading.

> **Still open: vocabulary mismatch.** Question: "How do I sign in?" Because the query has only one meaningful term (`sign`), one match clears the threshold. Retrieval returned unrelated sections that contain "signed" (common auth failures, env vars), and the RAG answer was "I do not know based on the docs I have." It should have found `POST /api/login`. The LLM's refusal kept this safe, but it's a false "I don't know".

**When should DocuBot say “I do not know based on the docs I have”?**  
Give at least two specific situations.

> - The question's topic isn't in the docs at all, e.g. "Is there any mention of payment processing?", "How do I deploy to Kubernetes?", "What is the weather today?". All three are refused.
> - The docs mention the words but don't answer the question, e.g. asking which port PostgreSQL runs on in production (the docs only show an example connection string), or what happens to existing tokens when the secret key is rotated.
> - The question is too vague to match evidence, e.g. "Tell me about the project".

**What guardrails did you implement?**  
Examples: refusal rules, thresholds, limits on snippets, safe defaults.

> 1. **Evidence threshold** (`min_score_for` in `docubot.py`): a section must match at least 2 distinct meaningful query terms (or all terms for a one-term query). One incidental word overlap is not evidence.
> 2. **Refusal happens in `retrieve()`:** an empty result makes both Mode 2 and Mode 3 return "I do not know based on these docs.", and Mode 3 never calls the LLM in that case, so the model can't fill the gap with a guess.
> 3. **Snippet limits:** at most 3 sections, each about one heading's worth of text, so the LLM only sees focused evidence.
> 4. **Prompt-level refusal:** the RAG prompt requires an exact "I do not know" reply when the snippets aren't enough.

---

## 6. Limitations and Future Improvements

**Current limitations**  
List at least three limitations of your DocuBot system.

1. Keyword-only matching: synonyms and paraphrases ("sign in" vs "login") cause misses or false refusals.
2. The threshold is a fixed count. A long question that shares two generic words with an unrelated section ("token" + "user") can still pass.
3. Naive mode doesn't actually send the docs to the model, and RAG trusts that the model obeys the prompt. Nothing checks the generated answer against the snippets.
4. The weights and stemmer are tuned to four small docs and may not transfer to a larger corpus.
5. The Gemini free tier allows 15 requests per minute for `gemini-3.5-flash-lite`. Running the full comparison (2 LLM calls per question) hits that limit, and the error comes back as the "answer" text instead of a clear failure.

**Future improvements**  
List two or three changes that would most improve reliability or usefulness.

1. Add a small synonym map or embedding-based retrieval to handle paraphrases.
2. Weight terms by rarity (TF-IDF/BM25), so common words like "token" count less than distinctive ones like "refresh".
3. Show the retrieved snippets alongside every RAG answer, and add a check that each claim in the answer appears in a snippet.

---

## 7. Responsible Use

**Where could this system cause real world harm if used carelessly?**  
Think about wrong answers, missing information, or over trusting the LLM.

> A confident wrong answer about auth or the database could cause real damage: a wrong env var, a token stored somewhere unsafe, an endpoint assumed to be public when it is admin-only, or a schema change that breaks production. Naive mode is the riskiest because it sounds authoritative without using the docs at all. Stale docs are a problem even for RAG: it faithfully repeats whatever the docs say.

**What instructions would you give real developers who want to use DocuBot safely?**  
Write 2 to 4 short bullet points.

- Use RAG or Retrieval-only mode, not Naive mode, for anything you'll act on, and check the cited file yourself.
- Treat "I do not know based on these docs" as a signal to read the docs or the code, not to rephrase until the bot guesses.
- Never act on security-sensitive answers (auth, secrets, permissions) without confirming in the source code.
- Keep `docs/` up to date: DocuBot is only as correct as its documentation.

---
