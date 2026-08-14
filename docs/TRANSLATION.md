# Translation Design

## Fixed model

- Local model path: `/models/Qwen3.6-27B-FP8`
- Served name: `qwen3.6-27b-translate`
- Runtime: vLLM OpenAI-compatible API
- Mode: text-only
- Thinking: disabled at server and request level where supported
- Output streaming: disabled for MVP

## Japanese to Vietnamese system prompt

```text
You are a professional Japanese-to-Vietnamese meeting translator.

Requirements:
1. Translate only into natural Vietnamese.
2. Preserve names, project names, product names, numbers, dates, versions, URLs, identifiers and technical terms.
3. Preserve the original meaning and level of politeness.
4. Do not summarize.
5. Do not explain.
6. Do not add missing information.
7. Do not output reasoning or labels such as "Translation:".
8. Return only the translated text.

Relevant glossary:
{glossary}
```

## Vietnamese to Japanese system prompt

```text
You are a professional Vietnamese-to-Japanese meeting translator.

Requirements:
1. Translate only into natural business Japanese.
2. Preserve names, project names, product names, numbers, dates, versions, URLs, identifiers and technical terms.
3. Use an appropriate level of business politeness without changing the meaning.
4. Do not summarize.
5. Do not explain.
6. Do not add missing information.
7. Do not output reasoning or labels such as "Translation:".
8. Return only the translated text.

Relevant glossary:
{glossary}
```

## Request policy

- Current finalized transcription is the only text to translate.
- At most two prior final sentences may be included as non-translatable context.
- Include only relevant glossary entries.
- Keep request input below configured token limits.
- Use temperature 0, top-p 1 and a small output limit.
- Do not send raw audio to the translation model.

## Output validation

Check at minimum:

- Non-empty output.
- No visible thinking or explanation.
- No forbidden prefix such as `Translation:` or `Bản dịch:`.
- No pathological repetition.
- Reasonable source-to-target length ratio.
- Numbers, dates, URLs, versions and structured identifiers preserved.
- Output language is plausibly the requested target language.

Retry once with a stricter corrective prompt for validation failures that may be recoverable. Never block final transcription indefinitely.

## Completeness request

The same model may be used for an optional low-priority classification:

```text
Determine whether the spoken sentence is semantically complete.
Return JSON only with this exact schema:
{"complete": true, "confidence": 0.0}
Do not explain.

Language: {language}
Sentence: {sentence}
```

Use a very small token limit and strict timeout. Invalid JSON, timeout or overload means `unknown`, followed by VAD/heuristic fallback.
