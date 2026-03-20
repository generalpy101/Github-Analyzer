"""LLM integration for GitHub profile review. Supports Anthropic, OpenAI, and Ollama."""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def _load_prompt():
    """Load the review prompt template."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(base, "prompt_template.md")
    with open(prompt_path) as f:
        content = f.read()
    # Extract the prompt part (everything before the placeholder)
    parts = content.split(
        "[PASTE CONTENTS OF runtime/data/github_data.json HERE]")
    return parts[0].rstrip() if parts else content


def _extract_json(text):
    """Extract JSON from LLM response, handling markdown code fences."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding the first { ... } block
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError("Could not extract valid JSON from LLM response")


def _call_anthropic(prompt, data_json, config):
    """Call Anthropic API, with optional extended thinking."""
    import anthropic

    client = anthropic.Anthropic(api_key=config["api_key"])
    thinking = config.get("extended_thinking", False)
    user_msg = prompt + "\n\n```json\n" + data_json + "\n```"

    kwargs = {
        "model": config.get("model", "claude-sonnet-4-20250514"),
        "messages": [{"role": "user", "content": user_msg}],
    }

    if thinking:
        kwargs["max_tokens"] = 32000
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": 10000,
        }
    else:
        kwargs["max_tokens"] = 16000

    message = client.messages.create(**kwargs)
    for block in message.content:
        if block.type == "text":
            return block.text
    return message.content[0].text


def _call_openai(prompt, data_json, config):
    """Call OpenAI API, with optional reasoning effort."""
    import openai

    client = openai.OpenAI(api_key=config["api_key"])
    thinking = config.get("extended_thinking", False)
    user_msg = prompt + "\n\n```json\n" + data_json + "\n```"

    kwargs = {
        "model": config.get("model", "gpt-4o"),
        "response_format": {"type": "json_object"},
        "max_tokens": 16000,
        "messages": [
            {"role": "system", "content": "You are a GitHub profile reviewer. Respond with valid JSON only."},
            {"role": "user", "content": user_msg},
        ],
    }

    if thinking:
        kwargs["reasoning_effort"] = "high"

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def _call_ollama(prompt, data_json, config, on_stream=None):
    """Call Ollama local API, with optional thinking mode and streaming."""
    import requests

    thinking = config.get("extended_thinking", False)
    url = config.get("ollama_url", "http://localhost:11434").rstrip("/")
    user_msg = prompt + "\n\n```json\n" + data_json + "\n```"

    options = {"num_ctx": 32768}
    if thinking:
        options["num_predict"] = 32000

    use_stream = on_stream is not None

    payload = {
        "model": config.get("model", "llama3.1"),
        "messages": [
            {"role": "system", "content": "You are a GitHub profile reviewer. Respond with valid JSON only."},
            {"role": "user", "content": user_msg},
        ],
        "format": "json",
        "stream": use_stream,
        "options": options,
    }

    if thinking:
        payload["think"] = True

    if not use_stream:
        response = requests.post(url + "/api/chat", json=payload, timeout=900)
        response.raise_for_status()
        return response.json()["message"]["content"]

    full_text = ""
    token_count = 0
    response = requests.post(
        url + "/api/chat", json=payload, timeout=900, stream=True)
    response.raise_for_status()
    for line in response.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = chunk.get("message", {}).get("content", "")
        if content:
            full_text += content
            token_count += 1
            if token_count % 50 == 0:
                on_stream(token_count)
    return full_text


DEFAULT_BATCH_SIZE = 5


def _call_llm(prompt, data_json, config, on_stream=None):
    """Dispatch to the configured LLM provider."""
    provider = config.get("provider", "anthropic")
    if provider == "anthropic":
        return _call_anthropic(prompt, data_json, config)
    elif provider == "openai":
        return _call_openai(prompt, data_json, config)
    elif provider == "ollama":
        return _call_ollama(prompt, data_json, config, on_stream=on_stream)
    raise ValueError("Unknown provider: {}".format(provider))


def _split_github_data(gh_data, batch_size):
    """Split github_data into chunks, each containing a subset of repositories.

    Batch 1 gets the full context (profile, stats, activity, contribution
    calendar).  Batches 2+ get only the repos and their details to reduce
    token usage — the LLM only needs repo data for those batches since the
    first batch already produced the profile/activity/summary sections.
    Returns a list of (chunk_dict, repo_names_in_chunk) tuples.
    """
    repos = gh_data.get("repositories", [])
    original_repos = [r for r in repos if not r.get("isFork", False)]
    if len(original_repos) <= batch_size:
        return [(gh_data, [r.get("name", "") for r in original_repos])]

    details = gh_data.get("top_repo_details", {})
    chunks = []
    for i in range(0, len(original_repos), batch_size):
        batch_repos = original_repos[i: i + batch_size]
        batch_names = [r.get("name", "") for r in batch_repos]
        batch_details = {k: v for k, v in details.items() if k in batch_names}

        if i == 0:
            chunk = dict(gh_data)
            chunk["repositories"] = batch_repos
            chunk["top_repo_details"] = batch_details
        else:
            chunk = {
                "username": gh_data.get("username", ""),
                "repositories": batch_repos,
                "top_repo_details": batch_details,
                "_batch_note": "This is a continuation batch. Only review the repositories listed here. Do NOT produce profile_review, activity_review, code_review, repo_presentation, categories, or summary — only repository_reviews.",
            }

        chunks.append((chunk, batch_names))
    return chunks


def _merge_reviews(base, additions):
    """Merge additional batch reviews into the base review.

    Appends repository_reviews from each addition into base and recalculates
    the top-level score as an average.
    """
    for add in additions:
        base.setdefault("repository_reviews", []).extend(
            add.get("repository_reviews", [])
        )
    all_repos = base.get("repository_reviews", [])
    if all_repos:
        scores = [r.get("score", 0) for r in all_repos]
        base["overall_score"] = int(sum(scores) / len(scores))
    return base


MAX_RETRIES = 2


def _call_llm_with_retry(prompt, data_json, config, retries=MAX_RETRIES,
                         on_progress=None, on_stream=None):
    """Call the LLM and parse JSON, retrying on transient/parse failures."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raw = _call_llm(prompt, data_json, config, on_stream=on_stream)
            return _extract_json(raw)
        except Exception as e:
            last_error = e
            snippet = ""
            if isinstance(e, ValueError) and "raw" in dir():
                snippet = (raw or "")[:200].replace("\n", " ")
            if on_progress:
                if attempt < retries:
                    on_progress(
                        "LLM response not valid JSON (attempt {}/{}). Retrying...{}".format(
                            attempt, retries,
                            " Response preview: " + snippet if snippet else ""
                        )
                    )
                else:
                    on_progress(
                        "LLM response not valid JSON after {} attempts. Error: {}{}".format(
                            retries, str(e)[:100],
                            " | Response preview: " + snippet if snippet else ""
                        )
                    )
            if attempt < retries:
                continue
    raise last_error


def _run_batch(idx, chunk, names, prompt, config, on_progress=None):
    """Execute a single batch call with retries. Returns (idx, review, error)."""
    batch_label = "batch {}".format(idx + 1)
    try:
        data_json = json.dumps(chunk, default=str)
        review = _call_llm_with_retry(
            prompt, data_json, config, on_progress=on_progress)
        return (idx, review, None)
    except Exception as e:
        return (idx, None, str(e))


def generate_review(github_data_path, config, on_progress=None):
    """Send GitHub data to an LLM for analysis and return the parsed review.

    When there are more repos than BATCH_SIZE, the data is split into batches
    and sent to the LLM in parallel using a thread pool, then merged.
    Batch 1 gets full context; batches 2+ get only repo data (reduced tokens).
    If a batch fails after retries, it is skipped and the rest still merge.

    For Ollama, streaming is enabled to report token progress.

    Args:
        github_data_path: Path to github_data.json
        config: Dict with provider, model, api_key, ollama_url
        on_progress: Optional callback(message) for batch progress updates

    Returns:
        Parsed review dict matching the schema in prompt_template.md
    """
    prompt = _load_prompt()

    with open(github_data_path) as f:
        gh_data = json.load(f)

    original_count = len([
        r for r in gh_data.get("repositories", [])
        if not r.get("isFork", False)
    ])
    batch_size = int(config.get("batch_size", DEFAULT_BATCH_SIZE))
    batch_size = max(2, min(batch_size, 20))
    chunks = _split_github_data(gh_data, batch_size)

    is_ollama = config.get("provider") == "ollama"

    def make_stream_cb(label):
        if not is_ollama or not on_progress:
            return None

        def cb(tokens):
            on_progress("{}: {} tokens generated...".format(label, tokens))
        return cb

    # Single batch — no parallelism needed
    if len(chunks) == 1:
        data_json = json.dumps(gh_data, default=str)
        stream_cb = make_stream_cb("Generating")
        review = _call_llm_with_retry(prompt, data_json, config,
                                      on_progress=on_progress,
                                      on_stream=stream_cb)
        _validate_review(review)
        return review

    if on_progress:
        on_progress("Splitting {} repos into {} batches of ~{} (parallel)...".format(
            original_count, len(chunks), batch_size
        ))

    # Send batch 1 first (needs full context for profile/summary sections)
    first_chunk, first_names = chunks[0]
    if on_progress:
        on_progress("Sending batch 1/{} ({} repos, full context)...".format(
            len(chunks), len(first_names)
        ))
    first_result = _run_batch(
        0, first_chunk, first_names, prompt, config, on_progress=on_progress
    )

    # Send remaining batches in parallel (stripped context)
    results = [first_result]
    remaining = chunks[1:]
    if remaining:
        if on_progress:
            on_progress("Sending batches 2-{}/{} in parallel ({} repos, stripped context)...".format(
                len(chunks), len(chunks),
                sum(len(n) for _, n in remaining)
            ))

        max_workers = min(len(remaining), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for i, (chunk, names) in enumerate(remaining, start=1):
                future = executor.submit(
                    _run_batch, i, chunk, names, prompt, config, on_progress=on_progress
                )
                futures[future] = (i, names)

            for future in as_completed(futures):
                batch_idx, names = futures[future]
                idx, review, error = future.result()
                results.append((idx, review, error))
                if on_progress:
                    if error:
                        on_progress("Batch {}/{} failed: {}".format(
                            batch_idx + 1, len(chunks), error[:80]
                        ))
                    else:
                        on_progress("Batch {}/{} complete.".format(
                            batch_idx + 1, len(chunks)
                        ))

    results.sort(key=lambda r: r[0])

    base_review = None
    batch_reviews = []
    failed_batches = []

    for idx, review, error in results:
        chunk_names = chunks[idx][1]
        if error:
            failed_batches.append((idx + 1, chunk_names, error))
        elif base_review is None:
            base_review = review
        else:
            batch_reviews.append(review)

    if base_review is None:
        if failed_batches:
            errors = "; ".join("batch {}: {}".format(b, err)
                               for b, _, err in failed_batches)
            raise ValueError("All LLM batches failed: {}".format(errors))
        raise ValueError("No batches were processed")

    merged = _merge_reviews(base_review, batch_reviews)

    if failed_batches:
        skipped = []
        for _, names, _ in failed_batches:
            skipped.extend(names)
        merged.setdefault("_skipped_repos", skipped)
        if on_progress:
            on_progress("{}/{} batches succeeded. {} repos skipped due to errors.".format(
                len(chunks) - len(failed_batches), len(chunks), len(skipped)
            ))

    _validate_review(merged)
    return merged


def _validate_review(review):
    """Raise ValueError if the review is empty or trivially incomplete."""
    if not isinstance(review, dict) or len(review) < 3:
        raise ValueError("LLM returned empty or trivial JSON")
    if review.get("overall_score", 0) == 0 and not review.get("repository_reviews"):
        raise ValueError(
            "LLM returned a review with no scores and no repository reviews")


def _build_chat_context(review, github_data=None):
    """Build a condensed system prompt from the review for chat context."""
    parts = []
    username = review.get("username", "unknown")
    parts.append(
        "You just reviewed the GitHub profile of @{}.".format(username))
    parts.append(
        "Overall score: {}/100.".format(review.get("overall_score", 0)))

    headline = review.get("headline", "")
    if headline:
        parts.append("Headline: {}".format(headline))

    summary = review.get("summary", "")
    if summary:
        parts.append("Summary:\n{}".format(summary[:1500]))

    pr = review.get("profile_review", {})
    if pr.get("strengths"):
        parts.append("Profile strengths: {}".format(
            ", ".join(pr["strengths"][:5])))
    if pr.get("improvements"):
        parts.append("Profile improvements needed: {}".format(
            ", ".join(pr["improvements"][:5])))

    readme_review = pr.get("profile_readme_review", "")
    if readme_review:
        parts.append("Profile README review: {}".format(readme_review[:500]))

    repos = review.get("repository_reviews", [])
    if repos:
        parts.append("\nRepository reviews ({} repos):".format(len(repos)))
        for r in repos[:20]:
            line = "- {} (score: {}, rec: {}): {}".format(
                r.get("repo_name", "?"), r.get("score", 0),
                r.get("recommendation", "?"), r.get("verdict", "")[:150],
            )
            parts.append(line)

    recs = review.get("top_recommendations", [])
    if recs:
        parts.append("\nTop recommendations:")
        for rec in recs[:5]:
            parts.append("- [{}] {}: {}".format(
                rec.get("priority", "?"), rec.get("title", ""),
                rec.get("description", "")[:200],
            ))

    if github_data:
        profile = github_data.get("profile", {})
        bio = profile.get("bio", "")
        if bio:
            parts.append("\nCurrent bio: \"{}\"".format(bio))
        readme = github_data.get("profile_readme", "")
        if readme:
            parts.append(
                "Current profile README (first 500 chars):\n{}".format(readme[:500]))

    return "\n".join(parts)


def chat_with_review(review, github_data, messages, config):
    """Send a chat message with the review as context.

    Args:
        review: The review dict (from review_json)
        github_data: The github_data dict (for profile/README context)
        messages: List of {role, content} dicts (chat history)
        config: LLM config dict

    Returns:
        The assistant's response as a plain text string
    """
    context = _build_chat_context(review, github_data)
    system_msg = (
        "You are a helpful GitHub profile coach. You have just completed a detailed "
        "review of a developer's GitHub profile. Use the review data below to answer "
        "their questions with specific, actionable advice.\n\n"
        "When suggesting improvements, be concrete — write actual text they can copy, "
        "name specific repos, and reference their real data. Use markdown formatting "
        "(**bold**, `code`, bullet lists) to make your responses clear.\n\n"
        "Review context:\n" + context
    )

    provider = config.get("provider", "anthropic")

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=config["api_key"])
        resp = client.messages.create(
            model=config.get("model", "claude-sonnet-4-20250514"),
            max_tokens=4000,
            system=system_msg,
            messages=messages,
        )
        for block in resp.content:
            if block.type == "text":
                return block.text
        return resp.content[0].text

    elif provider == "openai":
        import openai
        client = openai.OpenAI(api_key=config["api_key"])
        all_msgs = [{"role": "system", "content": system_msg}] + messages
        resp = client.chat.completions.create(
            model=config.get("model", "gpt-4o"),
            max_tokens=4000,
            messages=all_msgs,
        )
        return resp.choices[0].message.content

    elif provider == "ollama":
        import requests
        url = config.get("ollama_url", "http://localhost:11434").rstrip("/")
        all_msgs = [{"role": "system", "content": system_msg}] + messages
        resp = requests.post(
            url + "/api/chat",
            json={
                "model": config.get("model", "llama3.1"),
                "messages": all_msgs,
                "stream": False,
                "options": {"num_ctx": 16384},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    raise ValueError("Unknown provider: {}".format(provider))


def test_connection(config):
    """Test that the LLM connection works. Returns (success, message)."""
    provider = config.get("provider", "anthropic")

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=config["api_key"])
            resp = client.messages.create(
                model=config.get("model", "claude-sonnet-4-20250514"),
                max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            return True, "Connected to Anthropic ({})".format(config.get("model"))

        elif provider == "openai":
            import openai
            client = openai.OpenAI(api_key=config["api_key"])
            resp = client.chat.completions.create(
                model=config.get("model", "gpt-4o"),
                max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            return True, "Connected to OpenAI ({})".format(config.get("model"))

        elif provider == "ollama":
            import requests
            url = config.get(
                "ollama_url", "http://localhost:11434").rstrip("/")
            resp = requests.get(url + "/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            if models:
                return True, "Ollama connected. Models: {}".format(", ".join(models[:5]))
            return True, "Ollama connected (no models found)"

        else:
            return False, "Unknown provider: {}".format(provider)

    except Exception as e:
        return False, str(e)
