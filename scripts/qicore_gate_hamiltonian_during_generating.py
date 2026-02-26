# scripts/qicore_gate_hamiltonian_during_generating.py
#
# QiCore (Nivel 2): During-generation gating usando Hamiltoniano v2 piecewise
# - Stream desde Ollama (/api/generate stream=True)
# - Cada CHECK_EVERY_CHARS evalúa features -> (mu, sigma, v_risk) -> H (engine piecewise)
# - Si H > threshold (después de MIN_CHARS_BEFORE_GATE), corta generación (bloqueo)
# - Multi-candidato (temp/seed) + selección por menor H y preferencia NO-bloqueados
# - Guarda results/run_<ts>_<tag>/summary.json + candidates.json (incluye checkpoints)
#
# Requisitos:
#   - Ollama corriendo (BASE_URL)
#   - MODEL descargado
#   - services/qicore_engine_piecewise.py disponible
#
# Ejecutar:
#   source .env
#   QICORE_PROMPT='...' python scripts/qicore_gate_during_generating.py
#
# Env útiles:
#   OLLAMA_BASE_URL=http://localhost:11434
#   OLLAMA_MODEL=llama3.2:latest
#   QICORE_RESULTS_DIR=results
#   QICORE_RUN_TAG=run
#   QICORE_N=4
#   QICORE_BASE_SEED=123
#
#   # Hamiltoniano / engine
#   QICORE_H_THRESHOLD=1.0        # threshold del Hamiltoniano (no confundir con heurístico viejo)
#   QICORE_ETA=0.5
#   QICORE_LAMBDA2=2.0
#   QICORE_SIGMA_KNOWN=0.08
#   QICORE_SIGMA_BORDER=0.30
#   QICORE_BETA_NEG_BORDER=0.20
#   QICORE_MISSION_WEIGHT_OOD=0.0
#
#   # Gate streaming
#   QICORE_CHECK_EVERY_CHARS=120
#   QICORE_MIN_CHARS_BEFORE_GATE=80
#
#   # Features
#   QICORE_RISKY_NUMBER_THRESHOLD=12
#

# --- Path fix: asegura root del proyecto ---
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os, json, time, re
import urllib.request
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from datetime import datetime

from services.qicore_engine_piecewise import QiCoreEnginePiecewise

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

# Output (results/)
RESULTS_DIR = Path(os.getenv("QICORE_RESULTS_DIR", "results"))
RUN_TAG = os.getenv("QICORE_RUN_TAG", "").strip()

def _utc_stamp() -> str:
    # Nota: utcnow() está deprecado en py3.13+, pero funciona; preferimos timezone-aware.
    try:
        from datetime import timezone
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def _safe_filename(s: str, max_len: int = 64) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")
    return s[:max_len] if s else "run"

# Gate params (streaming cadence)
CHECK_EVERY_CHARS = int(os.getenv("QICORE_CHECK_EVERY_CHARS", "120"))
MIN_CHARS_BEFORE_GATE = int(os.getenv("QICORE_MIN_CHARS_BEFORE_GATE", "80"))

# ---------- Text -> features (auditables) ----------
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

RISKY_NUMBER_THRESHOLD = float(os.getenv("QICORE_RISKY_NUMBER_THRESHOLD", "12"))

def _parse_float(s: str) -> float:
    return float(s.replace(",", "."))

def extract_features(text: str) -> Dict[str, Any]:
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

    # Señales extra (opcionales) para empujar OOD en casos “fuente sin traza”
    # - srcNoTrace: menciona "según..." o "fuente:" pero NO hay url/doi/arxiv/etc.
    has_url = bool(re.search(r"https?://|www\.", text))
    src_no_trace = bool((has_source_marker or "según" in t) and not has_url)

    # - suspicious_org: mezcla organizaciones raras o inconsistencia típica (heurística muy simple)
    susp_org = bool("censos" in t and "ine" in t)  # ej: "Instituto Nacional de Estadística y Censos (INE)" en Chile

    # - report_like: dice "informe" + año + nombre genérico (sin link)
    report_like = bool("informe" in t and bool(re.search(r"\b20\d{2}\b", text)) and not has_url)

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

        "src_no_trace": src_no_trace,
        "suspicious_org": susp_org,
        "report_like": report_like,

        "has_url": has_url,
        "word_count": word_count,
    }

def features_to_gp_like(features: Dict[str, Any]) -> Tuple[float, float, float, Dict[str, Any]]:
    """
    Mapea features -> (mu, sigma, v_risk) para el Hamiltoniano piecewise.
    Esta es la heurística “puente”; después la reemplazas por GP real sin tocar el gate.
    """
    nums = int(features["nums_filtered_count"])
    overconf = int(features["overconf_count"])
    contradiction = bool(features["contradiction"])
    has_hedge = bool(features["has_hedge"])
    wc = int(features["word_count"])

    src_no_trace = bool(features.get("src_no_trace", False))
    susp_org = bool(features.get("suspicious_org", False))
    report_like = bool(features.get("report_like", False))

    # -------- mu (utilidad) --------
    mu = 0.0
    if has_hedge:
        mu += 0.8
    if features["has_disclaimer"] and not contradiction:
        mu += 0.4

    mu -= 0.6 * nums
    mu -= 0.8 * overconf
    if contradiction:
        mu -= 1.2

    # Señales de “autoridad sin traza” bajan utilidad
    if src_no_trace:
        mu -= 0.9
    if report_like:
        mu -= 0.5
    if susp_org:
        mu -= 0.6

    if wc < 6:
        mu -= 0.3
    if wc > 180:
        mu -= 0.2

    # -------- sigma (incertidumbre epistemológica) --------
    sigma = 0.05
    sigma += 0.06 * nums
    sigma += 0.05 * overconf
    if contradiction:
        sigma += 0.25
    if not has_hedge and nums >= 1:
        sigma += 0.08

    # Señales de “sin traza” empujan sigma fuerte (esto te manda a border/ood)
    if src_no_trace:
        sigma += 0.22
    if report_like:
        sigma += 0.10
    if susp_org:
        sigma += 0.12

    sigma = max(0.0, min(0.95, sigma))

    # -------- v_risk --------
    v_risk = 0.05
    v_risk += 0.02 * nums
    v_risk += 0.02 * overconf
    if contradiction:
        v_risk += 0.08

    if src_no_trace:
        v_risk += 0.08
    if report_like:
        v_risk += 0.04
    if susp_org:
        v_risk += 0.06

    v_risk = max(0.0, min(0.5, v_risk))

    meta = {"mu": float(mu), "sigma": float(sigma), "v_risk": float(v_risk)}
    return float(mu), float(sigma), float(v_risk), meta

# ---------- Engine (Hamiltoniano piecewise) ----------
def build_engine() -> QiCoreEnginePiecewise:
    return QiCoreEnginePiecewise(
        eta=float(os.getenv("QICORE_ETA", "0.5")),
        lambda_2=float(os.getenv("QICORE_LAMBDA2", "2.0")),
        threshold=float(os.getenv("QICORE_H_THRESHOLD", os.getenv("QICORE_THRESH", "1.0"))),
        sigma_known=float(os.getenv("QICORE_SIGMA_KNOWN", "0.08")),
        sigma_border=float(os.getenv("QICORE_SIGMA_BORDER", "0.30")),
        beta_neg_border=float(os.getenv("QICORE_BETA_NEG_BORDER", "0.20")),
        mission_weight_ood=float(os.getenv("QICORE_MISSION_WEIGHT_OOD", "0.0")),
    )

# ---------- Ollama streaming client ----------
@dataclass
class StreamResult:
    text: str
    blocked: bool
    block_reason: str
    last_H: float
    last_meta: Dict[str, Any]          # features
    last_gp: Dict[str, Any]            # mu/sigma/v_risk
    last_terms: Dict[str, Any]         # engine terms
    time_s: float
    checks: List[Dict[str, Any]]       # auditoría (len_chars, H, regime, mu, sigma, v_risk, ts_offset_s, flags)

def generate_stream_with_hamiltonian_gate(
    prompt: str,
    temperature: float,
    seed: int,
    engine: QiCoreEnginePiecewise,
    *,
    max_time_s: float = 180.0,
) -> StreamResult:
    """
    Streaming con gate por Hamiltoniano:
      - acumula texto
      - cada CHECK_EVERY_CHARS evalúa H sobre texto parcial
      - si H>threshold y len(acc)>=MIN_CHARS_BEFORE_GATE: corta
    """
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": temperature, "seed": seed},
    }

    t0 = time.time()
    acc = ""
    blocked = False
    block_reason = ""

    last_features: Dict[str, Any] = {}
    last_gp: Dict[str, Any] = {}
    last_terms: Dict[str, Any] = {}
    last_H = 0.0

    next_check_at = MIN_CHARS_BEFORE_GATE
    checks: List[Dict[str, Any]] = []

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=max_time_s) as resp:
            for raw_line in resp:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue

                obj = json.loads(line)
                chunk = obj.get("response", "")
                if chunk:
                    acc += chunk

                if len(acc) >= next_check_at:
                    last_features = extract_features(acc)
                    mu, sigma, v_risk, gp_meta = features_to_gp_like(last_features)
                    last_gp = gp_meta
                    last_H, last_terms = engine.hamiltonian_energy_from_gp(
                        mu=mu, sigma=sigma, v_risk=v_risk, return_terms=True
                    )

                    checks.append({
                        "len_chars": len(acc),
                        "H": round(float(last_H), 6),
                        "ts_offset_s": round(time.time() - t0, 4),
                        "regime": last_terms.get("regime", ""),
                        "mu": round(float(mu), 6),
                        "sigma": round(float(sigma), 6),
                        "v_risk": round(float(v_risk), 6),
                        "blocked_now": bool(last_terms.get("blocked", False)),
                        "srcNoTrace": bool(last_features.get("src_no_trace", False)),
                        "suspOrg": bool(last_features.get("suspicious_org", False)),
                        "repLike": bool(last_features.get("report_like", False)),
                    })

                    next_check_at += CHECK_EVERY_CHARS

                    if len(acc) >= MIN_CHARS_BEFORE_GATE and bool(last_terms.get("blocked", False)):
                        blocked = True
                        block_reason = f"H>{engine.threshold} during generation (H={float(last_H):.3f}, reg={last_terms.get('regime')})"
                        break

                if obj.get("done", False):
                    break

    except Exception as e:
        if not blocked:
            blocked = True
            block_reason = f"stream_error: {type(e).__name__}: {e}"

    dt = time.time() - t0

    # Si nunca chequeamos, evaluamos al final
    if not last_features:
        last_features = extract_features(acc)
        mu, sigma, v_risk, gp_meta = features_to_gp_like(last_features)
        last_gp = gp_meta
        last_H, last_terms = engine.hamiltonian_energy_from_gp(
            mu=mu, sigma=sigma, v_risk=v_risk, return_terms=True
        )
        checks.append({
            "len_chars": len(acc),
            "H": round(float(last_H), 6),
            "ts_offset_s": round(time.time() - t0, 4),
            "regime": last_terms.get("regime", ""),
            "mu": round(float(mu), 6),
            "sigma": round(float(sigma), 6),
            "v_risk": round(float(v_risk), 6),
            "blocked_now": bool(last_terms.get("blocked", False)),
            "srcNoTrace": bool(last_features.get("src_no_trace", False)),
            "suspOrg": bool(last_features.get("suspicious_org", False)),
            "repLike": bool(last_features.get("report_like", False)),
        })

    return StreamResult(
        text=acc.strip(),
        blocked=blocked,
        block_reason=block_reason,
        last_H=float(last_H),
        last_meta=last_features,
        last_gp=last_gp,
        last_terms=last_terms,
        time_s=dt,
        checks=checks,
    )

# ---------- Multi-candidate gate ----------
@dataclass
class Candidate:
    text: str
    H: float
    temperature: float
    seed: int
    features: Dict[str, Any]
    gp: Dict[str, Any]
    terms: Dict[str, Any]
    blocked_during: bool
    block_reason: str
    time_s: float
    checks: List[Dict[str, Any]]

def qicore_gate_during_hamiltonian(
    prompt: str,
    *,
    n: int = 4,
    base_seed: int = 123,
) -> Tuple[Candidate, List[Candidate], QiCoreEnginePiecewise]:
    temps = [0.2, 0.4, 0.6, 0.8][:n]
    engine = build_engine()

    cands: List[Candidate] = []
    for i, temp in enumerate(temps):
        res = generate_stream_with_hamiltonian_gate(prompt, temperature=temp, seed=base_seed + i, engine=engine)

        cands.append(Candidate(
            text=res.text,
            H=float(res.last_H),
            temperature=temp,
            seed=base_seed + i,
            features=res.last_meta,
            gp=res.last_gp,
            terms=res.last_terms,
            blocked_during=res.blocked,
            block_reason=res.block_reason,
            time_s=res.time_s,
            checks=res.checks,
        ))

    # Preferimos NO-bloqueados; luego menor H
    cands_sorted = sorted(cands, key=lambda c: (c.blocked_during, c.H))
    return cands_sorted[0], cands_sorted, engine

def _snippet(s: str, n: int = 90) -> str:
    s = s.replace("\n", " ").strip()
    return s[:n] + ("..." if len(s) > n else "")

def save_run_results(
    prompt: str,
    best: Candidate,
    all_cands: List[Candidate],
    *,
    engine: QiCoreEnginePiecewise,
    base_seed: int,
    n: int,
    time_s_total: float,
) -> Path:
    _ensure_dir(RESULTS_DIR)

    tag = RUN_TAG or _safe_filename(os.getenv("QICORE_RESULTS_TAG", ""))
    suffix = f"_{tag}" if tag else ""
    run_dir = RESULTS_DIR / f"run_{_utc_stamp()}{suffix}"
    _ensure_dir(run_dir)

    summary = {
        "ts_utc": _utc_stamp(),
        "mode": "during_generation_hamiltonian_piecewise",
        "model": MODEL,
        "base_url": BASE_URL,
        "prompt": prompt,
        "n_candidates": n,
        "base_seed": base_seed,
        "time_s_total": round(time_s_total, 4),
        "streaming": {
            "check_every_chars": CHECK_EVERY_CHARS,
            "min_chars_before_gate": MIN_CHARS_BEFORE_GATE,
        },
        "engine": {
            "type": "QiCoreEnginePiecewise",
            "eta": float(os.getenv("QICORE_ETA", str(engine.eta))),
            "lambda_2": float(os.getenv("QICORE_LAMBDA2", str(engine.lambda_2))),
            "H_threshold": float(os.getenv("QICORE_H_THRESHOLD", str(engine.threshold))),
            "sigma_known": float(os.getenv("QICORE_SIGMA_KNOWN", str(engine.sigma_known))),
            "sigma_border": float(os.getenv("QICORE_SIGMA_BORDER", str(engine.sigma_border))),
            "beta_neg_border": float(os.getenv("QICORE_BETA_NEG_BORDER", str(engine.beta_neg_border))),
            "mission_weight_ood": float(os.getenv("QICORE_MISSION_WEIGHT_OOD", str(engine.mission_weight_ood))),
        },
        "selected": {
            "H": best.H,
            "temperature": best.temperature,
            "seed": best.seed,
            "blocked": bool(best.blocked_during),
            "reason": best.block_reason or "",
            "regime": best.terms.get("regime", ""),
            "mu": best.gp.get("mu"),
            "sigma": best.gp.get("sigma"),
            "v_risk": best.gp.get("v_risk"),
            "time_s": round(best.time_s, 4),
        },
        "all_blocked": bool(all(c.blocked_during for c in all_cands)),
    }

    candidates = []
    for c in all_cands:
        candidates.append({
            "H": c.H,
            "temperature": c.temperature,
            "seed": c.seed,
            "blocked": bool(c.blocked_during),
            "reason": c.block_reason or "",
            "time_s": round(c.time_s, 4),
            "terms": c.terms,
            "gp": c.gp,
            "features": c.features,
            "checks": c.checks,
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
    best, all_cands, engine = qicore_gate_during_hamiltonian(prompt, n=n, base_seed=base_seed)
    dt_total = time.time() - t0

    if best.blocked_during or bool(best.terms.get("blocked", False)):
        print("⚠️ QiCore Gate (during-generation, Hamiltonian v2 piecewise): BLOQUEO.")
        print("Respuesta segura: No tengo evidencia suficiente para responder con confianza. ¿Puedes dar más contexto?")
    else:
        print(best.text)

    print("\n--- candidatos (during-generation, H menor es mejor) ---")
    for c in all_cands:
        terms = c.terms or {}
        print(
            " | ".join([
                f"H={c.H:.3f}",
                f"temp={c.temperature}",
                f"seed={c.seed}",
                f"reg={terms.get('regime')}",
                f"mu={terms.get('mu', 0.0):.3f}",
                f"sigma={terms.get('sigma', 0.0):.3f}",
                f"U={terms.get('U_tanh', 0.0):.3f}",
                f"m={terms.get('term_mission', 0.0):.3f}",
                f"r={terms.get('term_risk', 0.0):.3f}",
                f"u={terms.get('term_uncertainty', 0.0):.3f}",
                f"blocked={c.blocked_during}",
                f"reason={c.block_reason or '-'}",
                f"srcNoTrace={bool(c.features.get('src_no_trace', False))}",
                f"suspOrg={bool(c.features.get('suspicious_org', False))}",
                f"repLike={bool(c.features.get('report_like', False))}",
                f"time_s={c.time_s:.2f}",
                f":: {_snippet(c.text)}",
            ])
        )

    print(
        f"\n---\nmodel={MODEL} base_url={BASE_URL} "
        f"H_THRESHOLD={engine.threshold} checkEveryChars={CHECK_EVERY_CHARS} minChars={MIN_CHARS_BEFORE_GATE} "
        f"time_total_s={dt_total:.2f}"
    )

    try:
        run_dir = save_run_results(prompt, best, all_cands, engine=engine, base_seed=base_seed, n=n, time_s_total=dt_total)
        print(f"\n[saved] {run_dir}/summary.json")
    except Exception as e:
        print(f"\n[warn] could not save results: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
