"""LLM integration for GitHub profile review. Supports Anthropic, OpenAI, and Ollama."""

from __future__ import annotations

import json
import os
import re
import sys


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
    parts = content.split("[PASTE CONTENTS OF runtime/data/github_data.json HERE]")
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


def _call_ollama(prompt, data_json, config):
    """Call Ollama local API, with optional thinking mode."""
    import requests

    thinking = config.get("extended_thinking", False)
    url = config.get("ollama_url", "http://localhost:11434").rstrip("/")
    user_msg = prompt + "\n\n```json\n" + data_json + "\n```"

    options = {"num_ctx": 32768}
    if thinking:
        options["num_predict"] = 32000

    payload = {
        "model": config.get("model", "llama3.1"),
        "messages": [
            {"role": "system", "content": "You are a GitHub profile reviewer. Respond with valid JSON only."},
            {"role": "user", "content": user_msg},
        ],
        "format": "json",
        "stream": False,
        "options": options,
    }

    if thinking:
        payload["think"] = True

    response = requests.post(url + "/api/chat", json=payload, timeout=900)
    response.raise_for_status()
    return response.json()["message"]["content"]


DEFAULT_BATCH_SIZE = 5


def _call_llm(prompt, data_json, config):
    """Dispatch to the configured LLM provider."""
    provider = config.get("provider", "anthropic")
    if provider == "anthropic":
        return _call_anthropic(prompt, data_json, config)
    elif provider == "openai":
        return _call_openai(prompt, data_json, config)
    elif provider == "ollama":
        return _call_ollama(prompt, data_json, config)
    raise ValueError("Unknown provider: {}".format(provider))


def _split_github_data(gh_data, batch_size):
    """Split github_data into chunks, each containing a subset of repositories.

    Each chunk keeps the full profile / stats / activity context but only a
    slice of the repos list and their matching top_repo_details entries.
    Returns a list of (chunk_dict, repo_names_in_chunk) tuples.
    """
    repos = gh_data.get("repositories", [])
    original_repos = [r for r in repos if not r.get("isFork", False)]
    if len(original_repos) <= batch_size:
        return [(gh_data, [r.get("name", "") for r in original_repos])]

    details = gh_data.get("top_repo_details", {})
    chunks = []
    for i in range(0, len(original_repos), batch_size):
        batch_repos = original_repos[i : i + batch_size]
        batch_names = [r.get("name", "") for r in batch_repos]
        chunk = dict(gh_data)
        chunk["repositories"] = batch_repos
        chunk["top_repo_details"] = {
            k: v for k, v in details.items() if k in batch_names
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


def generate_review(github_data_path, config, on_progress=None):
    """Send GitHub data to an LLM for analysis and return the parsed review.

    When there are more repos than BATCH_SIZE, the data is split into batches
    and each batch is sent to the LLM separately, then the results are merged.

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

    if len(chunks) == 1:
        data_json = json.dumps(gh_data, default=str)
        raw = _call_llm(prompt, data_json, config)
        review = _extract_json(raw)
        _validate_review(review)
        return review

    if on_progress:
        on_progress("Splitting {} repos into {} batches of ~{}...".format(
            original_count, len(chunks), batch_size
        ))

    base_review = None
    batch_reviews = []

    for idx, (chunk, names) in enumerate(chunks):
        if on_progress:
            on_progress("Sending batch {}/{} ({} repos: {})...".format(
                idx + 1, len(chunks), len(names),
                ", ".join(names[:3]) + ("..." if len(names) > 3 else "")
            ))

        data_json = json.dumps(chunk, default=str)
        raw = _call_llm(prompt, data_json, config)
        review = _extract_json(raw)

        if idx == 0:
            base_review = review
        else:
            batch_reviews.append(review)

    merged = _merge_reviews(base_review, batch_reviews)
    _validate_review(merged)
    return merged


def _validate_review(review):
    """Raise ValueError if the review is empty or trivially incomplete."""
    if not isinstance(review, dict) or len(review) < 3:
        raise ValueError("LLM returned empty or trivial JSON")
    if review.get("overall_score", 0) == 0 and not review.get("repository_reviews"):
        raise ValueError("LLM returned a review with no scores and no repository reviews")


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
            url = config.get("ollama_url", "http://localhost:11434").rstrip("/")
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
