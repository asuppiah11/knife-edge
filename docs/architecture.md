# Architecture

```mermaid
flowchart LR
  subgraph Data["Synthetic data (seeded)"]
    L[league.py<br/>20 clubs, squads, strengths] --> M[match.py<br/>event generator]
    M --> E[(events.jsonl<br/>match.json)]
    M --> T[(truth.json<br/>hidden regimes, intensities, hidden xG)]
    S[season.py] --> R[ratings.py<br/>Poisson MLE]
  end

  subgraph Engine
    E --> RP[replay.py<br/>per-event state]
    R --> RP
    RP --> ST[state.py<br/>live intensity<br/>score · men · momentum · tilt]
    ST --> WP[wp.py<br/>closed-form P(H/D/A)]
    WP --> G[greeks.py<br/>Delta Gamma Theta Vega]
  end

  subgraph API["API (FastAPI)"]
    G --> REST[/REST + SSE replay/]
    G --> MCP[/MCP tools: greeks_now, why_it_moved,<br/>top_moments, theta_curve, scenario/]
  end

  subgraph Agents["Agents (Agent Framework / in-process)"]
    MCP --> Q[Quant]
    MCP --> TA[Tactician]
    Q --> N[Narrator<br/>Foundry model]
    TA --> N
    N --> LO[Localiser<br/>ES · TA]
    LO --> V[Verifier<br/>deterministic + groundedness]
    V -- reject --> N
    V -- fallback --> TPL[templates.py]
  end

  V --> CUES[(overlay cues<br/>schema: t_in, t_out, priority,<br/>facts, evidence ids)]
  TPL --> CUES
  CUES --> UI[web/index.html<br/>casual · analyst · bench · player]
  REST --> UI
  T -. calibration only .-> CAL[calibration.py<br/>Brier · RPS · ECE]
```

## Data flow for one cue

1. The replay has computed, for event 1180 (a shot, xG 0.52, saved), P(home) before and after, and the decomposition `{time: 0.0, momentum: +4.3, discipline: 0, score: 0}`.
2. Quant ranks it as a *big chance*: expected swing = 0.52 × delta(home goal) = 30.4 pts.
3. Facts are assembled: player, team, xG, expected_pts, score, probabilities, minute label; evidence = `[1180]`.
4. Narrator drafts `{"headline": "...", "body": "..."}` from the facts (or the template renders it).
5. Verifier checks every number, scoreline, minute label, name, the vocabulary and the evidence id. On rejection, Narrator gets one retry with the reasons; otherwise the template is used.
6. The cue is emitted with `t_in = clock_s`, `t_out = t_in + 12`, priority 3, `source` and the verifier record, and the UI shows it when the replay clock reaches `t_in`.
