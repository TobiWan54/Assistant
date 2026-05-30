from __future__ import annotations

import json
from typing import List

from openai import OpenAI


class AlarmResolver:
    """
    Uses the LLM only as a resolver/reranker over structured candidate alarms.

    Output format:
    {
      "status": "matched",
      "alarm_id": "abc123",
      "reason": "..."
    }

    {
      "status": "ambiguous",
      "alarm_ids": ["abc123", "def456"],
      "reason": "..."
    }

    {
      "status": "no_match",
      "reason": "..."
    }
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def resolve(self, reference: str, candidates: List[dict]) -> dict:
        if not candidates:
            return {
                "status": "no_match",
                "reason": "No candidate alarms were found.",
            }

        if len(candidates) == 1:
            return {
                "status": "matched",
                "alarm_id": candidates[0]["alarm_id"],
                "reason": "Only one candidate alarm exists.",
            }

        system_prompt = """
You are an alarm reference resolver.

You are given:
1. a user’s natural-language alarm reference
2. a list of candidate alarms

Your job is to choose the best matching alarm among the candidates.

Return JSON only.

Rules:
- Never invent an alarm_id.
- If exactly one candidate is clearly the best match, return:
  {"status":"matched","alarm_id":"...","reason":"..."}
- If multiple candidates are plausible, return:
  {"status":"ambiguous","alarm_ids":["...","..."],"reason":"..."}
- If none of the candidates match well, return:
  {"status":"no_match","reason":"..."}

Use:
- label meaning
- time
- day/date cues
- active/ringing status
- likely user intent
""".strip()

        user_prompt = f"""
Reference:
{reference}

Candidate alarms:
{json.dumps(candidates, indent=2)}
""".strip()

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            top_p=1.0,
        )

        content = resp.choices[0].message.content or "{}"
        content = content.strip()

        if content.startswith("```"):
            lines = content.splitlines()
            if len(lines) > 2:
                content = "\n".join(lines[1:-1]).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {
                "status": "ambiguous",
                "alarm_ids": [c["alarm_id"] for c in candidates[:3]],
                "reason": f"Resolver returned invalid JSON: {content}",
            }

        valid_ids = {c["alarm_id"] for c in candidates}

        if parsed.get("status") == "matched":
            alarm_id = parsed.get("alarm_id")
            if alarm_id in valid_ids:
                return {
                    "status": "matched",
                    "alarm_id": alarm_id,
                    "reason": parsed.get("reason", "Resolved to a single alarm."),
                }
            return {
                "status": "ambiguous",
                "alarm_ids": list(valid_ids)[:3],
                "reason": "Resolver returned an invalid alarm_id.",
            }

        if parsed.get("status") == "ambiguous":
            ids = [a for a in parsed.get("alarm_ids", []) if a in valid_ids]
            if ids:
                return {
                    "status": "ambiguous",
                    "alarm_ids": ids,
                    "reason": parsed.get("reason", "Multiple alarms are plausible."),
                }
            return {
                "status": "ambiguous",
                "alarm_ids": list(valid_ids)[:3],
                "reason": "Resolver reported ambiguity.",
            }

        return {
            "status": "no_match",
            "reason": parsed.get("reason", "No suitable alarm match."),
        }