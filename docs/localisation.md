# Localisation (EN / ES / TA)

Two paths produce Spanish and Tamil cues:

1. **LLM mode** — the Localiser agent writes the cue natively in the target language from the same facts (not a translation of the English), with numbers pinned as digits and names unchanged. The deterministic Verifier runs on the localised text exactly as on English: numbers, scorelines, minute labels, names, banned vocabulary and evidence ids.
2. **Template mode / fallback** — `knifeedge/agents/templates.py` holds hand-written templates per cue kind. Bench prompts carry their own ES/TA strings in `pipeline.py`.

## Review status

| Language | Templates | Reviewed by native speaker |
|---|---|---|
| English | 7 kinds × casual/analyst | yes |
| Spanish | 7 kinds × casual/analyst + 3 bench prompts | **to review** |
| Tamil | 7 kinds × casual/analyst + 3 bench prompts | **to review** — drafted by a model; Adhitya (native speaker) to correct idiom before the demo |

Things to check in Tamil: football idiom for "swing"/"fragile" (புள்ளிகள் மாற்றம், கத்தி முனையில்), whether team short codes should stay in Latin script (they do today so the Verifier can match them), and whether numbers read naturally with Tamil postpositions.

## Why the Verifier still works in other scripts

Numbers stay as ASCII digits, names stay in Latin script, and scorelines/minute labels keep their `1-1` / `45+2'` shapes, so the same regexes apply. The banned-vocabulary list covers English, Spanish (`apuesta`, `cuota`, `casa de apuestas`) and Tamil (பந்தயம், சூதாட்டம்) betting terms.
