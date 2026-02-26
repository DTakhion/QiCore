# scripts/qicore_gate.py
import os, json, time, re
import urllib.request
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any
from pathlib import Path
from datetime import datetime

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

# Output (results/)
RESULTS_DIR = Path(os.getenv("QICORE_RESULTS_DIR", "results"))
RUN_TAG = os.getenv("QICORE_RUN_TAG", "").strip()  # opcional: etiqueta para agrupar runs

def _utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def _safe_filename(s: str, max_len: int = 64) -> str:
    # deja solo caracteres seguros para nombre de carpeta/archivo
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
        "options": {
            "temperature": temperature,
            "seed": seed,
        },
    }
    out = post_json(f"{BASE_URL}/api/generate", payload)
    return (out.get("response") or "").strip()

# ---------- QiCore energy (v1.2 heuristics) ----------
HEDGING_OK = [
    "no estoy seguro", "puede", "podría", "es probable", "depende",
    "no tengo suficiente información", "no cuento con", "no tengo datos",
]
OVERCONFIDENT = [
    "siempre", "nunca", "100%", "definitivamente", "sin duda",
    "garantizado", "completamente seguro",
]

# Penaliza autocontradicción: "no tengo acceso" + (fuente/cifra específica)
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

def _parse_float(s: str) -> float:
    return float(s.replace(",", "."))

def energy_parts(text: str) -> Dict[str, Any]:
    """
    Retorna energía total + desglose auditable:
      - e1: overconfidence (y hits)
      - e2: densidad de números "riesgosos" (filtrados por umbral)
      - e3: números riesgosos + sin hedging
      - e4: control de longitud
      - e5: contradicción "no tengo acceso" + (fuente o cifra específica)
    """
    t = text.lower()

    # 1) overconfidence penalty
    e1 = 0.0
    hits_conf = []
    for w in OVERCONFIDENT:
        if w in t:
            e1 += 1.0
            hits_conf.append(w)

    # 2) risky specificity: números (filtrados)
    raw_nums = re.findall(r"\d+(?:[.,]\d+)?", text)

    nums = []
    for x in raw_nums:
        try:
            v = _parse_float(x)
            if v > RISKY_NUMBER_THRESHOLD:
                nums.append(x)
        except Exception:
            pass

    e2 = max(0.0, (len(nums) - 2) * 0.4)  # tolera hasta 2 números riesgosos sin castigo

    # 3) lack of hedging when numeric (sobre nums filtrados)
    has_hedge = any(h in t for h in HEDGING_OK)
    e3 = 0.0
    if len(nums) >= 3 and not has_hedge:
        e3 += 0.8

    # 4) length control
    word_count = len(text.split())
    e4 = 0.0
    if word_count < 6:
        e4 += 0.8
    if word_count > 180:
        e4 += 0.6

    # 5) contradiction penalty: disclaimer + (fuente o cifra específica)
    e5 = 0.0
    has_disclaimer = any(d in t for d in DISCLAIMERS)
    has_source_marker = any(s in t for s in SOURCE_MARKERS)
    has_percent = "%" in text
    has_decimal = bool(re.search(r"\d+[.,]\d+", text))

    if has_disclaimer and (has_source_marker or has_percent or has_decimal):
        e5 += 2.2

    E = e1 + e2 + e3 + e4 + e5
    return {
        "E": E,
        "threshold_risky_number": RISKY_NUMBER_THRESHOLD,

        "e1_overconfidence": e1,
        "e1_hits": hits_conf,

        "e2_numbers": e2,
        "raw_nums": raw_nums,
        "raw_nums_count": len(raw_nums),
        "nums_filtered": nums,
        "nums_filtered_count": len(nums),

        "e3_nohedge_when_numeric": e3,
        "has_hedge": has_hedge,

        "e4_length": e4,
        "word_count": word_count,

        "e5_disclaimer_contradiction": e5,
        "has_disclaimer": has_disclaimer,
        "has_source_marker": has_source_marker,
        "has_percent": has_percent,
        "has_decimal": has_decimal,
    }

@dataclass
class Candidate:
    text: str
    E: float
    temperature: float
    seed: int
    meta: Dict[str, Any]

def qicore_gate(prompt: str, n: int = 4, base_seed: int = 42) -> Tuple[Candidate, List[Candidate]]:
    temps = [0.2, 0.4, 0.6, 0.8][:n]
    cands: List[Candidate] = []
    for i, temp in enumerate(temps):
        txt = generate(prompt, temperature=temp, seed=base_seed + i)
        parts = energy_parts(txt)
        cands.append(
            Candidate(
                text=txt,
                E=float(parts["E"]),
                temperature=temp,
                seed=base_seed + i,
                meta=parts,
            )
        )

    cands_sorted = sorted(cands, key=lambda c: c.E)
    return cands_sorted[0], cands_sorted

def _snippet(s: str, n: int = 90) -> str:
    s = s.replace("\n", " ").strip()
    return s[:n] + ("..." if len(s) > n else "")

def save_run_results(
    prompt: str,
    best: Candidate,
    all_cands: List[Candidate],
    *,
    thresh: float,
    time_s: float,
    base_seed: int,
) -> Path:
    """
    Guarda un resumen auditable del run en:
      results/run_<timestamp>_<tag>/summary.json
      results/run_<timestamp>_<tag>/candidates.json
    """
    _ensure_dir(RESULTS_DIR)

    tag = RUN_TAG or _safe_filename(os.getenv("QICORE_RESULTS_TAG", ""))  # alias opcional
    suffix = f"_{tag}" if tag else ""
    run_dir = RESULTS_DIR / f"run_{_utc_stamp()}{suffix}"
    _ensure_dir(run_dir)

    summary = {
        "ts_utc": _utc_stamp(),
        "mode": "post_generation",
        "model": MODEL,
        "base_url": BASE_URL,
        "threshold": thresh,
        "risky_number_threshold": RISKY_NUMBER_THRESHOLD,
        "time_s": round(time_s, 4),
        "prompt": prompt,
        "n_candidates": len(all_cands),
        "base_seed": base_seed,
        "selected": {
            "E": best.E,
            "temperature": best.temperature,
            "seed": best.seed,
        },
        "blocked": bool(best.E > thresh),
    }

    candidates = []
    for c in all_cands:
        candidates.append({
            "E": c.E,
            "temperature": c.temperature,
            "seed": c.seed,
            "meta": c.meta,
            "text": c.text,
        })

    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "candidates.json", {"prompt": prompt, "candidates": candidates})
    return run_dir

def main():
    prompt = os.getenv("QICORE_PROMPT") or "Explica en 3 líneas qué es un número primo."

    base_seed = int(os.getenv("QICORE_BASE_SEED", "123"))
    n = int(os.getenv("QICORE_N", "4"))
    THRESH = float(os.getenv("QICORE_THRESH", "1.8"))

    t0 = time.time()
    best, all_cands = qicore_gate(prompt, n=n, base_seed=base_seed)
    dt = time.time() - t0

    if best.E > THRESH:
        print("⚠️ QiCore Gate: BLOQUEO (energía alta).")
        print("Respuesta segura: No tengo evidencia suficiente para responder con confianza. ¿Puedes dar más contexto?")
    else:
        print(best.text)

    print("\n--- candidatos (E menor es mejor) ---")
    for c in all_cands:
        m = c.meta
        print(
            " | ".join([
                f"E={c.E:.2f}",
                f"temp={c.temperature}",
                f"seed={c.seed}",
                f"e1={m['e1_overconfidence']:.2f} hits={m['e1_hits']}",
                f"e2={m['e2_numbers']:.2f} rawNums={m['raw_nums_count']} filtNums={m['nums_filtered_count']} thr>{m['threshold_risky_number']}",
                f"e3={m['e3_nohedge_when_numeric']:.2f} hedge={m['has_hedge']}",
                f"e4={m['e4_length']:.2f} words={m['word_count']}",
                f"e5={m['e5_disclaimer_contradiction']:.2f} disc={m['has_disclaimer']} src={m['has_source_marker']} pct={m['has_percent']} dec={m['has_decimal']}",
                f":: {_snippet(c.text)}",
            ])
        )

    print(f"\n---\nmodel={MODEL} time_s={dt:.2f}")

    # Persist results
    try:
        run_dir = save_run_results(prompt, best, all_cands, thresh=THRESH, time_s=dt, base_seed=base_seed)
        print(f"\n[saved] {run_dir}/summary.json")
    except Exception as e:
        print(f"\n[warn] could not save results: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
