# scripts/qicore_gate_hamiltonian_post.py
#
# QiCore (Nivel 1): Post-generation gating usando Hamiltoniano v2 piecewise
# - Genera N candidatos (temp/seed)
# - Extrae "features" heurísticas del texto -> (mu, sigma, v_risk)
# - Evalúa H con services/qicore_engine_piecewise.py
# - Selecciona el menor H (energía) y aplica threshold del engine
# - Guarda results/run_<ts>/summary.json + candidates.json
#
# Requisitos:
#   - Ollama corriendo (BASE_URL)
#   - MODEL descargado en Ollama
#   - services/qicore_engine_piecewise.py disponible
#
# Cambios v1.1 (quirúrgicos):
#   ✅ Fix datetime utcnow() deprecated -> timezone-aware UTC
#   ✅ Detectores anti "fuente inventada":
#        - has_url / has_bare_domain
#        - source_without_trace (menciona fuente pero no entrega enlace/cita)
#        - suspicious_org_mix (patrones típicos de alucinación de instituciones)
#        - report_like_claim (dice "informe/reporte" + año/título genérico sin trazabilidad)
#   ✅ Ajuste de mapeo features -> (mu, sigma, v_risk):
#        - sube sigma y v_risk fuerte en "source hallucination" patterns
#        - castiga mu en esos casos
#
# Nota: no toca el engine piecewise; solo mejora el "puente" texto->(mu,sigma,v_risk).

# --- Path fix: asegura root del proyecto ---
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os, json, time, re
import urllib.request
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any
from pathlib import Path
from datetime import datetime, timezone

from services.qicore_engine_piecewise import QiCoreEnginePiecewise


BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

# Results
RESULTS_DIR = Path(os.getenv("QICORE_RESULTS_DIR", "results"))
RUN_TAG = os.getenv("QICORE_RUN_TAG", "").strip()


def _utc_stamp() -> str:
    # timezone-aware UTC (evita DeprecationWarning)
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_filename(s: str, max_len: int = 64) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")
    return s[:max_len] if s else "run"


# ---------- Ollama client ----------
def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate(prompt: str, temperature: float, seed: int) -> str:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "seed": seed},
    }
    out = post_json(f"{BASE_URL}/api/generate", payload)
    return (out.get("response") or "").strip()


# ---------- Text -> (mu, sigma, v_risk) ----------
# Nota: Aquí está el “puente” heurístico desde texto a GP-like (mu, sigma).
# Luego podemos cambiarlo por un GP real sin tocar el gate.

HEDGING_OK = [
    "no estoy seguro", "puede", "podría", "es probable", "depende",
    "no tengo suficiente información", "no cuento con", "no tengo datos",
    "no tengo acceso", "no puedo", "no pude encontrar", "no puedo proporcionar",
]
OVERCONFIDENT = [
    "siempre", "nunca", "100%", "definitivamente", "sin duda",
    "garantizado", "completamente seguro",
]
DISCLAIMERS = [
    "no tengo acceso", "no tengo información", "no tengo datos",
    "no puedo encontrar", "no pude encontrar", "no puedo proporcionar",
    "no puedo brindar", "no cuento con información",
]
SOURCE_MARKERS = [
    "fuente:", "según el", "según la", "según", "de acuerdo con",
]

# Umbral: ignora números típicos "pequeños" (1,2,3...) de definiciones matemáticas
RISKY_NUMBER_THRESHOLD = float(os.getenv("QICORE_RISKY_NUMBER_THRESHOLD", "12"))

# Si hay "según/fuente" pero no hay URL ni un "dominio pelado", castigamos
SOURCE_TRACE_REQUIRED = os.getenv("QICORE_SOURCE_TRACE_REQUIRED", "1").strip() != "0"

# boosts (ajustables por env)
SIGMA_BOOST_SOURCE_NO_TRACE = float(os.getenv("QICORE_SIGMA_BOOST_SOURCE_NO_TRACE", "0.25"))
RISK_BOOST_SOURCE_NO_TRACE = float(os.getenv("QICORE_RISK_BOOST_SOURCE_NO_TRACE", "0.10"))
MU_PENALTY_SOURCE_NO_TRACE = float(os.getenv("QICORE_MU_PENALTY_SOURCE_NO_TRACE", "0.70"))

SIGMA_BOOST_SUSPICIOUS_ORG = float(os.getenv("QICORE_SIGMA_BOOST_SUSPICIOUS_ORG", "0.20"))
RISK_BOOST_SUSPICIOUS_ORG = float(os.getenv("QICORE_RISK_BOOST_SUSPICIOUS_ORG", "0.08"))
MU_PENALTY_SUSPICIOUS_ORG = float(os.getenv("QICORE_MU_PENALTY_SUSPICIOUS_ORG", "0.50"))

SIGMA_BOOST_REPORT_LIKE = float(os.getenv("QICORE_SIGMA_BOOST_REPORT_LIKE", "0.15"))
RISK_BOOST_REPORT_LIKE = float(os.getenv("QICORE_RISK_BOOST_REPORT_LIKE", "0.05"))
MU_PENALTY_REPORT_LIKE = float(os.getenv("QICORE_MU_PENALTY_REPORT_LIKE", "0.25"))


def _parse_float(s: str) -> float:
    return float(s.replace(",", "."))


def extract_features(text: str) -> Dict[str, Any]:
    """
    Extrae señales (auditables) desde el texto:
      - nums_filtered_count: números > threshold (riesgo de precisión)
      - has_disclaimer / has_source_marker / has_percent / has_decimal
      - has_hedge / overconf_hits
      - word_count
      - has_url / has_bare_domain
      - source_without_trace (fuente/según + NO trazabilidad)
      - suspicious_org_mix (patrones sospechosos)
      - report_like_claim (informe/reporte + año/título sin trazabilidad)
    """
    t = text.lower()

    raw_nums = re.findall(r"\d+(?:[.,]\d+)?", text)
    nums_filtered = []
    for x in raw_nums:
        try:
            if _parse_float(x) > RISKY_NUMBER_THRESHOLD:
                nums_filtered.append(x)
        except Exception:
            pass

    has_hedge = any(h in t for h in HEDGING_OK)
    overconf_hits = [w for w in OVERCONFIDENT if w in t]

    has_disclaimer = any(d in t for d in DISCLAIMERS)
    has_source_marker = any(s in t for s in SOURCE_MARKERS)
    has_percent = "%" in text
    has_decimal = bool(re.search(r"\d+[.,]\d+", text))
    word_count = len(text.split())

    contradiction = bool(has_disclaimer and (has_source_marker or has_percent or has_decimal))

    # --- trazabilidad de fuente ---
    has_url = bool(re.search(r"https?://|www\.", text, flags=re.IGNORECASE))
    # dominio "pelado" tipo ine.cl / oecd.org / worldbank.org
    has_bare_domain = bool(re.search(r"\b[a-z0-9-]+\.(cl|org|com|gov|edu|net)\b", text, flags=re.IGNORECASE))

    source_without_trace = bool(
        SOURCE_TRACE_REQUIRED
        and has_source_marker
        and not has_url
        and not has_bare_domain
    )

    # --- report-like claims (sin trazabilidad) ---
    # Ej: "Informe 2023", "reporte 2022", "publicó en su informe 'X' en 2023"
    report_words = ["informe", "reporte", "boletín", "memoria", "anuario", "documento"]
    has_report_word = any(w in t for w in report_words)
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", text))
    has_quoted_title = '"' in text or "“" in text or "”" in text
    report_like_claim = bool(has_report_word and (has_year or has_quoted_title) and not (has_url or has_bare_domain))

    # --- mezcla sospechosa de organismos (heurística simple) ---
    # Casos típicos: "INE y Censos", "ONU para la Educación, la Salud y el Desarrollo", etc.
    suspicious_patterns = [
        r"instituto\s+nacional\s+de\s+estad[ií]stica\s+y\s+censos",  # INE+... (mezcla)
        r"onu\s+para\s+la\s+educaci[oó]n.*(salud|desarrollo)",       # descripción rara ONU
        r"pnud.*(educaci[oó]n|salud)",                               # PNUD con educación/salud
        r"desaf[ií]os\s+globales",                                    # título genérico sospechoso
    ]
    suspicious_org_mix = any(re.search(p, t) for p in suspicious_patterns)

    return {
        "raw_nums": raw_nums,
        "raw_nums_count": len(raw_nums),
        "nums_filtered": nums_filtered,
        "nums_filtered_count": len(nums_filtered),
        "risky_number_threshold": RISKY_NUMBER_THRESHOLD,

        "has_hedge": has_hedge,
        "overconf_hits": overconf_hits,
        "overconf_count": len(overconf_hits),

        "has_disclaimer": has_disclaimer,
        "has_source_marker": has_source_marker,
        "has_percent": has_percent,
        "has_decimal": has_decimal,
        "contradiction": contradiction,

        "has_url": has_url,
        "has_bare_domain": has_bare_domain,
        "source_without_trace": source_without_trace,
        "report_like_claim": report_like_claim,
        "suspicious_org_mix": suspicious_org_mix,

        "word_count": word_count,
    }


def features_to_gp_like(features: Dict[str, Any]) -> Tuple[float, float, float, Dict[str, Any]]:
    """
    Mapea features -> (mu, sigma, v_risk)

    Heurística v1.1:
      - mu: premia prudencia REAL, castiga señales de "fuente inventada"
      - sigma: sube fuerte con "source_without_trace" / "suspicious_org_mix"
      - v_risk: sube con señales de inventar fuente y con precisión numérica
    """
    nums = int(features["nums_filtered_count"])
    overconf = int(features["overconf_count"])
    contradiction = bool(features["contradiction"])
    has_hedge = bool(features["has_hedge"])
    wc = int(features["word_count"])

    source_no_trace = bool(features.get("source_without_trace", False))
    suspicious_org = bool(features.get("suspicious_org_mix", False))
    report_like = bool(features.get("report_like_claim", False))

    # -------- mu (utilidad) --------
    mu = 0.0
    if has_hedge:
        mu += 0.8
    if features["has_disclaimer"] and not contradiction:
        mu += 0.4

    # castigos base
    mu -= 0.6 * nums
    mu -= 0.8 * overconf
    if contradiction:
        mu -= 1.2

    # castigos específicos "fuente inventada"
    if source_no_trace:
        mu -= MU_PENALTY_SOURCE_NO_TRACE
    if suspicious_org:
        mu -= MU_PENALTY_SUSPICIOUS_ORG
    if report_like:
        mu -= MU_PENALTY_REPORT_LIKE

    # forma
    if wc < 6:
        mu -= 0.3
    if wc > 180:
        mu -= 0.2

    # -------- sigma (incertidumbre / riesgo epistemológico) --------
    sigma = 0.05
    sigma += 0.06 * nums
    sigma += 0.05 * overconf
    if contradiction:
        sigma += 0.25
    if not has_hedge and nums >= 1:
        sigma += 0.08

    # boosts por "fuente inventada"
    if source_no_trace:
        sigma += SIGMA_BOOST_SOURCE_NO_TRACE
    if suspicious_org:
        sigma += SIGMA_BOOST_SUSPICIOUS_ORG
    if report_like:
        sigma += SIGMA_BOOST_REPORT_LIKE

    sigma = max(0.0, min(0.95, sigma))

    # -------- v_risk --------
    v_risk = 0.05
    v_risk += 0.02 * nums
    v_risk += 0.02 * overconf
    if contradiction:
        v_risk += 0.08

    if source_no_trace:
        v_risk += RISK_BOOST_SOURCE_NO_TRACE
    if suspicious_org:
        v_risk += RISK_BOOST_SUSPICIOUS_ORG
    if report_like:
        v_risk += RISK_BOOST_REPORT_LIKE

    v_risk = max(0.0, min(0.5, v_risk))

    meta = {
        "mu": float(mu),
        "sigma": float(sigma),
        "v_risk": float(v_risk),

        # auditoría
        "source_without_trace": bool(source_no_trace),
        "suspicious_org_mix": bool(suspicious_org),
        "report_like_claim": bool(report_like),
    }
    return float(mu), float(sigma), float(v_risk), meta


# ---------- Candidate / Gate ----------
@dataclass
class Candidate:
    text: str
    temperature: float
    seed: int
    features: Dict[str, Any]
    gp: Dict[str, Any]
    H: float
    terms: Dict[str, Any]


def qicore_gate_hamiltonian_post(
    prompt: str,
    *,
    n: int = 4,
    base_seed: int = 123,
) -> Tuple[Candidate, List[Candidate]]:
    temps = [0.2, 0.4, 0.6, 0.8][:n]

    engine = QiCoreEnginePiecewise(
        eta=float(os.getenv("QICORE_ETA", "0.5")),
        lambda_2=float(os.getenv("QICORE_LAMBDA2", "2.0")),
        threshold=float(os.getenv("QICORE_H_THRESHOLD", os.getenv("QICORE_THRESH", "1.0"))),
        sigma_known=float(os.getenv("QICORE_SIGMA_KNOWN", "0.08")),
        sigma_border=float(os.getenv("QICORE_SIGMA_BORDER", "0.30")),
        beta_neg_border=float(os.getenv("QICORE_BETA_NEG_BORDER", "0.20")),
        mission_weight_ood=float(os.getenv("QICORE_MISSION_WEIGHT_OOD", "0.0")),
    )

    cands: List[Candidate] = []
    for i, temp in enumerate(temps):
        txt = generate(prompt, temperature=temp, seed=base_seed + i)

        feats = extract_features(txt)
        mu, sigma, v_risk, gp_meta = features_to_gp_like(feats)

        H, terms = engine.hamiltonian_energy_from_gp(
            mu=mu, sigma=sigma, v_risk=v_risk, return_terms=True
        )

        cands.append(Candidate(
            text=txt,
            temperature=temp,
            seed=base_seed + i,
            features=feats,
            gp=gp_meta,
            H=float(H),
            terms=terms,
        ))

    cands_sorted = sorted(cands, key=lambda c: c.H)
    return cands_sorted[0], cands_sorted


def _snippet(s: str, n: int = 90) -> str:
    s = s.replace("\n", " ").strip()
    return s[:n] + ("..." if len(s) > n else "")


def save_run_results(
    prompt: str,
    best: Candidate,
    all_cands: List[Candidate],
    *,
    time_s: float,
    base_seed: int,
    n: int,
) -> Path:
    _ensure_dir(RESULTS_DIR)

    tag = RUN_TAG or _safe_filename(os.getenv("QICORE_RESULTS_TAG", ""))
    suffix = f"_{tag}" if tag else ""
    run_dir = RESULTS_DIR / f"run_{_utc_stamp()}{suffix}"
    _ensure_dir(run_dir)

    summary = {
        "ts_utc": _utc_stamp(),
        "mode": "post_generation_hamiltonian_piecewise",
        "model": MODEL,
        "base_url": BASE_URL,
        "prompt": prompt,
        "n_candidates": n,
        "base_seed": base_seed,
        "time_s": round(time_s, 4),
        "engine": {
            "type": "QiCoreEnginePiecewise",
            "eta": float(os.getenv("QICORE_ETA", "0.5")),
            "lambda_2": float(os.getenv("QICORE_LAMBDA2", "2.0")),
            "H_threshold": float(os.getenv("QICORE_H_THRESHOLD", os.getenv("QICORE_THRESH", "1.0"))),
            "sigma_known": float(os.getenv("QICORE_SIGMA_KNOWN", "0.08")),
            "sigma_border": float(os.getenv("QICORE_SIGMA_BORDER", "0.30")),
            "beta_neg_border": float(os.getenv("QICORE_BETA_NEG_BORDER", "0.20")),
            "mission_weight_ood": float(os.getenv("QICORE_MISSION_WEIGHT_OOD", "0.0")),
        },
        "selected": {
            "H": best.H,
            "temperature": best.temperature,
            "seed": best.seed,
            "blocked": bool(best.terms.get("blocked", False)),
            "regime": best.terms.get("regime", ""),
            "mu": best.terms.get("mu"),
            "sigma": best.terms.get("sigma"),
            "v_risk": best.gp.get("v_risk"),
            "flags": {
                "source_without_trace": bool(best.gp.get("source_without_trace", False)),
                "suspicious_org_mix": bool(best.gp.get("suspicious_org_mix", False)),
                "report_like_claim": bool(best.gp.get("report_like_claim", False)),
            }
        },
    }

    candidates = []
    for c in all_cands:
        candidates.append({
            "H": c.H,
            "temperature": c.temperature,
            "seed": c.seed,
            "terms": c.terms,
            "gp": c.gp,
            "features": c.features,
            "text": c.text,
        })

    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "candidates.json", {"prompt": prompt, "candidates": candidates})
    return run_dir


def main():
    prompt = os.getenv("QICORE_PROMPT") or "Explica en 3 líneas qué es un número primo."

    base_seed = int(os.getenv("QICORE_BASE_SEED", "123"))
    n = int(os.getenv("QICORE_N", "4"))

    t0 = time.time()
    best, all_cands = qicore_gate_hamiltonian_post(prompt, n=n, base_seed=base_seed)
    dt = time.time() - t0

    if best.terms.get("blocked", False):
        print("⚠️ QiCore Gate (Hamiltonian v2 piecewise): BLOQUEO.")
        print("Respuesta segura: No tengo evidencia suficiente para responder con confianza. ¿Puedes dar más contexto?")
    else:
        print(best.text)

    print("\n--- candidatos (H menor es mejor) ---")
    for c in all_cands:
        terms = c.terms
        flags = c.gp or {}
        print(
            " | ".join([
                f"H={c.H:.3f}",
                f"temp={c.temperature}",
                f"seed={c.seed}",
                f"reg={terms.get('regime')}",
                f"mu={terms.get('mu'):.3f}",
                f"sigma={terms.get('sigma'):.3f}",
                f"U={terms.get('U_tanh'):.3f}",
                f"m={terms.get('term_mission'):.3f}",
                f"r={terms.get('term_risk'):.3f}",
                f"u={terms.get('term_uncertainty'):.3f}",
                f"blocked={terms.get('blocked')}",
                f"srcNoTrace={bool(flags.get('source_without_trace', False))}",
                f"suspOrg={bool(flags.get('suspicious_org_mix', False))}",
                f"repLike={bool(flags.get('report_like_claim', False))}",
                f":: {_snippet(c.text)}",
            ])
        )

    print(f"\n---\nmodel={MODEL} base_url={BASE_URL} time_s={dt:.2f}")

    try:
        run_dir = save_run_results(prompt, best, all_cands, time_s=dt, base_seed=base_seed, n=n)
        print(f"\n[saved] {run_dir}/summary.json")
    except Exception as e:
        print(f"\n[warn] could not save results: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
