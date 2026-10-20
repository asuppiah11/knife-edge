"""Template narration in English, Spanish and Tamil.

Templates are the guaranteed fallback when the LLM draft fails verification,
and the whole product in offline mode. Every number is interpolated from the
cue's ``facts`` so the Verifier always passes on template output.

Tamil strings were drafted by a non-native model and are marked for native
review (see docs/localisation.md). Numbers stay as digits in every language
so the Verifier can check them.
"""

from __future__ import annotations

from typing import Dict

# fmt: off
TEMPLATES: Dict[str, Dict[str, Dict[str, str]]] = {
    "swing": {
        "en": {
            "headline": "{player} scores. {home_short} {score_home}-{score_away} {away_short}",
            "body": "Swing of {swing_pts} points: {team} are now {team_p_pct}% to win. {biggest_text}",
            "body_analyst": "Swing {swing_pts} pts (score {score_pts}, momentum {momentum_pts}). {team} now {team_p_pct}% to win, draw {p_draw_pct}%. Shot xG {xg}.",
        },
        "es": {
            "headline": "Gol de {player}. {home_short} {score_home}-{score_away} {away_short}",
            "body": "Un giro de {swing_pts} puntos: {team} tiene ahora un {team_p_pct}% de probabilidad de ganar. {biggest_text}",
            "body_analyst": "Giro de {swing_pts} pts (marcador {score_pts}, impulso {momentum_pts}). {team} ahora {team_p_pct}% de ganar, empate {p_draw_pct}%. xG del tiro {xg}.",
        },
        "ta": {
            "headline": "{player} கோல். {home_short} {score_home}-{score_away} {away_short}",
            "body": "{swing_pts} புள்ளிகள் மாற்றம்: {team} வெற்றி வாய்ப்பு இப்போது {team_p_pct}%. {biggest_text}",
            "body_analyst": "மாற்றம் {swing_pts} புள்ளிகள் (கோல் {score_pts}, உந்துதல் {momentum_pts}). {team} வெற்றி {team_p_pct}%, டிரா {p_draw_pct}%. ஷாட் xG {xg}.",
        },
    },
    "big_chance": {
        "en": {
            "headline": "{player}: {outcome_word}, {xg} xG",
            "body": "That chance was worth {expected_pts} points to {team} before it was taken. {rank_phrase}",
            "body_analyst": "Expected swing {expected_pts} pts (xG {xg} x next-goal delta). Realised move {swing_pts} pts via momentum. {team} now {team_p_pct}% to win.",
        },
        "es": {
            "headline": "{player}: {outcome_word}, {xg} xG",
            "body": "Esa ocasión valía {expected_pts} puntos para {team} antes de rematar. {rank_phrase}",
            "body_analyst": "Giro esperado {expected_pts} pts (xG {xg} x delta del próximo gol). Movimiento real {swing_pts} pts por impulso. {team} ahora {team_p_pct}% de ganar.",
        },
        "ta": {
            "headline": "{player}: {outcome_word}, {xg} xG",
            "body": "அந்த வாய்ப்பு {team} அணிக்கு {expected_pts} புள்ளிகள் மதிப்புடையது. {rank_phrase}",
            "body_analyst": "எதிர்பார்க்கப்பட்ட மாற்றம் {expected_pts} புள்ளிகள் (xG {xg}). உண்மையான மாற்றம் {swing_pts} புள்ளிகள். {team} வெற்றி வாய்ப்பு {team_p_pct}%.",
        },
    },
    "knife_edge": {
        "en": {
            "headline": "Knife-edge: next goal swings it by {next_goal_swing_max} points",
            "body": "{home_short} {score_home}-{score_away} {away_short}, {remaining_min} minutes left. A {swing_team} goal here would move the match more than anything yet.",
            "body_analyst": "Fragility {knife_edge_pts} pts: home goal {next_goal_swing_home} pts, away goal {next_goal_swing_away} pts. P(home) {p_home_pct}%, draw {p_draw_pct}%, away {p_away_pct}%.",
        },
        "es": {
            "headline": "Al filo: el próximo gol mueve el partido {next_goal_swing_max} puntos",
            "body": "{home_short} {score_home}-{score_away} {away_short}, quedan {remaining_min} minutos. Un gol de {swing_team} ahora cambiaría el partido más que cualquier otra cosa hasta hoy.",
            "body_analyst": "Fragilidad {knife_edge_pts} pts: gol local {next_goal_swing_home} pts, gol visitante {next_goal_swing_away} pts. P(local) {p_home_pct}%, empate {p_draw_pct}%, visitante {p_away_pct}%.",
        },
        "ta": {
            "headline": "கத்தி முனையில்: அடுத்த கோல் {next_goal_swing_max} புள்ளிகள் மாற்றும்",
            "body": "{home_short} {score_home}-{score_away} {away_short}, {remaining_min} நிமிடங்கள் மீதம். {swing_team} கோல் அடித்தால் ஆட்டம் முழுவதும் மாறும்.",
            "body_analyst": "நிலையற்ற தன்மை {knife_edge_pts} புள்ளிகள்: ஹோம் கோல் {next_goal_swing_home}, அவே கோல் {next_goal_swing_away}. P(ஹோம்) {p_home_pct}%, டிரா {p_draw_pct}%, அவே {p_away_pct}%.",
        },
    },
    "theta": {
        "en": {
            "headline": "{leader} gain {theta_pts_per_min} points a minute just by holding on",
            "body": "{leader} are {leader_p_pct}% to win with {remaining_min} minutes left. Every minute without a goal is working for them.",
            "body_analyst": "Theta {theta_pts_per_min} pts/min for {leader} at {minute_label}. Remaining {remaining_min} min. P(win) {leader_p_pct}%, draw {p_draw_pct}%.",
        },
        "es": {
            "headline": "{leader} gana {theta_pts_per_min} puntos por minuto solo con aguantar",
            "body": "{leader} tiene un {leader_p_pct}% de ganar y quedan {remaining_min} minutos. Cada minuto sin gol juega a su favor.",
            "body_analyst": "Theta {theta_pts_per_min} pts/min para {leader} en el {minute_label}. Quedan {remaining_min} min. P(ganar) {leader_p_pct}%, empate {p_draw_pct}%.",
        },
        "ta": {
            "headline": "{leader} ஒவ்வொரு நிமிடமும் {theta_pts_per_min} புள்ளிகள் பெறுகிறது",
            "body": "{leader} வெற்றி வாய்ப்பு {leader_p_pct}%, {remaining_min} நிமிடங்கள் மீதம். கோல் இல்லாத ஒவ்வொரு நிமிடமும் அவர்களுக்கு சாதகம்.",
            "body_analyst": "தீட்டா {theta_pts_per_min} புள்ளிகள்/நிமிடம், {leader}, {minute_label}. மீதம் {remaining_min} நிமிடம். வெற்றி {leader_p_pct}%, டிரா {p_draw_pct}%.",
        },
    },
    "vega": {
        "en": {
            "headline": "Chaos favours {chaos_team}",
            "body": "If this game opens up, {chaos_team} gain about {vega_pts} points. {other_team} want it slow.",
            "body_analyst": "Vega {vega_pts} pts for {chaos_team} per +100% tempo. Recent tilt {chaos_team_tilt_pct}% of final-third touches. Score {score_home}-{score_away}.",
        },
        "es": {
            "headline": "El caos favorece a {chaos_team}",
            "body": "Si el partido se abre, {chaos_team} gana unos {vega_pts} puntos. A {other_team} le conviene ir despacio.",
            "body_analyst": "Vega {vega_pts} pts para {chaos_team} por +100% de ritmo. Inclinación reciente {chaos_team_tilt_pct}% de toques en último tercio. Marcador {score_home}-{score_away}.",
        },
        "ta": {
            "headline": "குழப்பம் {chaos_team} அணிக்கு சாதகம்",
            "body": "ஆட்டம் திறந்தால் {chaos_team} சுமார் {vega_pts} புள்ளிகள் பெறும். {other_team} மெதுவாக விளையாட விரும்பும்.",
            "body_analyst": "வேகா {vega_pts} புள்ளிகள் {chaos_team}. சமீபத்திய சாய்வு {chaos_team_tilt_pct}%. ஸ்கோர் {score_home}-{score_away}.",
        },
    },
    "bench_prompt": {
        "en": {
            "headline": "{action_headline}",
            "body": "{reason} Confidence {confidence_pct}%.",
            "body_analyst": "{reason} Confidence {confidence_pct}%.",
        },
        "es": {
            "headline": "{action_headline_es}",
            "body": "{reason_es} Confianza {confidence_pct}%.",
            "body_analyst": "{reason_es} Confianza {confidence_pct}%.",
        },
        "ta": {
            "headline": "{action_headline_ta}",
            "body": "{reason_ta} நம்பிக்கை {confidence_pct}%.",
            "body_analyst": "{reason_ta} நம்பிக்கை {confidence_pct}%.",
        },
    },
    "recap": {
        "en": {
            "headline": "Full time: {home_short} {score_home}-{score_away} {away_short}",
            "body": "The match turned on {biggest_player}'s goal at {biggest_label}, a {biggest_swing_pts}-point swing. It was most fragile at {fragile_label}, when the next goal was worth {fragile_pts} points.",
            "body_analyst": "Pre-match P(home) {pre_home_pct}%. Biggest swing {biggest_swing_pts} pts ({biggest_player}, {biggest_label}). Peak fragility {fragile_pts} pts at {fragile_label}. xG {xg_home} v {xg_away}.",
        },
        "es": {
            "headline": "Final: {home_short} {score_home}-{score_away} {away_short}",
            "body": "El partido giró con el gol de {biggest_player} en el {biggest_label}, un giro de {biggest_swing_pts} puntos. Fue más frágil en el {fragile_label}, cuando el próximo gol valía {fragile_pts} puntos.",
            "body_analyst": "P(local) previa {pre_home_pct}%. Mayor giro {biggest_swing_pts} pts ({biggest_player}, {biggest_label}). Fragilidad máxima {fragile_pts} pts en el {fragile_label}. xG {xg_home} - {xg_away}.",
        },
        "ta": {
            "headline": "முழு நேரம்: {home_short} {score_home}-{score_away} {away_short}",
            "body": "{biggest_label} நிமிடத்தில் {biggest_player} அடித்த கோல் ஆட்டத்தை மாற்றியது, {biggest_swing_pts} புள்ளிகள். {fragile_label} நிமிடத்தில் ஆட்டம் மிகவும் நிலையற்றதாக இருந்தது, அடுத்த கோல் {fragile_pts} புள்ளிகள் மதிப்பு.",
            "body_analyst": "ஆட்டத்திற்கு முன் P(ஹோம்) {pre_home_pct}%. பெரிய மாற்றம் {biggest_swing_pts} புள்ளிகள் ({biggest_player}, {biggest_label}). உச்ச நிலையற்ற தன்மை {fragile_pts} புள்ளிகள் {fragile_label}. xG {xg_home} - {xg_away}.",
        },
    },
}
# fmt: on

OUTCOME_WORDS = {
    "en": {"saved": "saved", "off_target": "off target", "blocked": "blocked", "post": "off the post", "goal": "goal"},
    "es": {"saved": "parada", "off_target": "fuera", "blocked": "bloqueado", "post": "al palo", "goal": "gol"},
    "ta": {"saved": "தடுக்கப்பட்டது", "off_target": "இலக்கு தவறியது", "blocked": "பிளாக்", "post": "போஸ்ட்", "goal": "கோல்"},
}


def render(kind: str, lang: str, audience: str, facts: Dict) -> tuple[str, str]:
    t = TEMPLATES[kind].get(lang) or TEMPLATES[kind]["en"]
    body_key = "body_analyst" if audience in ("analyst", "bench") and "body_analyst" in t else "body"
    headline = t["headline"].format(**facts)
    body = t[body_key].format(**facts)
    return headline, body
