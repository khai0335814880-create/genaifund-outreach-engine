import json
import re
from openai import OpenAI

def extract_json_from_llm(raw_text: str) -> dict:
    """
    Extracts and parses JSON from raw LLM responses.
    Handles markdown blocks (```json ... ```), preamble commentary,
    and trailing comma syntax errors gracefully.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty LLM response received.")

    clean_text = raw_text.strip()

    # 1. Direct parse attempt
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code fences: ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Extract outermost curly braces
    match = re.search(r"\{.*\}", clean_text, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 4. Attempt to repair trailing commas: e.g. {"a": 1, } -> {"a": 1}
            repaired = re.sub(r",\s*([\}\]])", r"\1", json_str)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Could not extract valid JSON from LLM response: {clean_text[:150]}...")

class LLMClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.has_key = bool(cfg.llm_api_key and cfg.llm_api_key.strip())
        self.client = OpenAI(
            api_key=cfg.llm_api_key.strip() if self.has_key else "missing_key",
            base_url=cfg.llm_base_url,
        ) if self.has_key else None

    def complete_json(self, system: str, user: str, max_tokens: int = 800) -> dict:
        if not self.client:
            raise RuntimeError("LLM_API_KEY is not set. Please set it in .env or run in Mock Mode.")

        last_error = ""
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.cfg.llm_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                raw_text = response.choices[0].message.content or ""
                return extract_json_from_llm(raw_text)
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    # Retry once with explicit reinforcement
                    user += "\n\nCRITICAL: Respond ONLY with a valid JSON object. No preamble, no markdown formatting."

        raise RuntimeError(f"LLM JSON extraction failed after 2 attempts: {last_error}")
