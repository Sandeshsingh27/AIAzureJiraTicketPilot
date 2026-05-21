"""
Thin wrapper around GitHub Models (OpenAI-compatible) using gpt-4o-mini.
Auth: GITHUB_TOKEN (a GitHub PAT). Endpoint: https://models.inference.ai.azure.com
"""
import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(
    base_url=os.getenv("AI_BASE_URL", "https://models.inference.ai.azure.com"),
    api_key=os.getenv("GITHUB_TOKEN"),
)
_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")


def classify_ticket(title: str, description: str, comments: str) -> dict:
    """
    Ask the model to classify a ticket and return a routing decision.
    Returns dict: {team, assignee, reason, confidence}
    """
    system = (
        "You are a Jira ticket router for the IDD/CRS team. "
        "Classify each ticket into one of: APAC, IMN, KEEP. Rules:\n"
        "- APAC: ticket is about Connect CTRIP, AUTOR VIENNA, or other APAC connects.\n"
        "- IMN: Room Category issues ONLY with Connect EAN or BCOM (not Amadeus or any other connect), "
        "  OR multi-source mismatch booking (e.g. mentions 'wrong hotels').\n"
        "- KEEP: Room Category issues involving Amadeus or any connect other than EAN/BCOM must stay with IDD/CRS.\n"
        "- KEEP: none of the above; stays with IDD/CRS.\n"
        "Respond ONLY as compact JSON: "
        '{"team":"APAC|IMN|KEEP","reason":"...","confidence":0.0-1.0}'
    )
    user = f"TITLE:\n{title}\n\nDESCRIPTION:\n{description}\n\nCOMMENTS:\n{comments}"

    resp = _client.chat.completions.create(
        model=_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user[:6000]},
        ],
    )
    text = resp.choices[0].message.content.strip()
    try:
        # tolerate code fences
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
    except Exception:
        return {"team": "KEEP", "reason": f"unparseable: {text[:200]}", "confidence": 0.0}


if __name__ == "__main__":
    demo = classify_ticket(
        "Wrong hotels showing for CTRIP search",
        "Customer sees mismatched hotels when booking via CTRIP connect.",
        "Looks like a multi source mismatch issue.",
    )
    print(demo)
