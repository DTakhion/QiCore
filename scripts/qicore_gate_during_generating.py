# scripts/qicore_gate_during_generating.py
import os, json, time, re
import urllib.request
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple

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
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")
    return s[:max_len] if s else "run"

# Gate params
THRESH = float(os.getenv("QICORE_THRESH", "1.8"))
CHECK_EVERY_CHARS = int(os.getenv("QICORE_CHECK_EVERY_CHARS", "120"))  # cada cuántos chars re-evaluar
MIN_CHARS_BEFORE_GATE = int(os.getenv("QICORE_MIN_CHARS_BEFORE_GATE", "80"))  # evita gate muy temprano

# ---------- QiCore energy (v1.2) ----------
HEDGING_OK = [
    "no estoy seguro", "puede", "podría", "es probable", "depende",
    "no tengo suficiente información", "no cuento con", "no tengo datos",
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

def energy_parts(text: str) -> Dict[str, Any]:
    t = text.lower()

    # e1 overconfidence
    e1 = 0.0
    hits_conf = []
    for w in OVERCONFIDENT:
        if w in t:
            e1 += 1.0
            hits_conf.append(w)

    # e2 risky numbers (filtered)
    raw_nums = re.findall(r"\d+(?:[.,]\d+)?", text)
    nums = []
    for x in raw_nums:
        try:
            v = _parse_float(x)
            if v > RISKY_NUMBER_THRESHOLD:
                nums.append(x)
        except Exception:
            pass
    e2 = max(0.0, (len(nums) - 2) * 0.4)

    # e3 numbers without hedging
    has_hedge = any(h in t for h in HEDGING_OK)
    e3 = 0.0
    if len(nums) >= 3 and not has_hedge:
        e3 += 0.8

    # e4 length control (on partial text too)
    word_count = len(text.split())
    e4 = 0.0
    if word_count < 6:
        e4 += 0.8
    if word_count > 180:
        e4 += 0.6

    # e5 disclaimer contradiction
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
        "raw_nums_count": len(raw_nums),
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

# ---------- Ollama streaming client ----------
@dataclass
class StreamResult:
    text: str
    blocked: bool
    block_reason: str
    last_energy: float
    last_meta: Dict[str, Any]
    time_s: float
    checks: List[Dict[str, Any]]  # checkpoints para auditoría (len_chars, E, ts_offset_s)

def generate_stream_with_gate(
    prompt: str,
    temperature: float,
    seed: int,
    *,
    max_time_s: float = 180.0,
) -> StreamResult:
    """
    Hace streaming desde /api/generate (stream=True), acumula texto y aplica gate durante generación.
    Si E supera THRESH (después de MIN_CHARS_BEFORE_GATE), corta cerrando la conexión.
    """
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": temperature,
            "seed": seed,
        },
    }

    t0 = time.time()
    acc = ""
    blocked = False
    block_reason = ""
    last_meta: Dict[str, Any] = {}
    last_E = 0.0
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
            # Ollama stream devuelve JSON por línea (NDJSON)
            for raw_line in resp:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue

                obj = json.loads(line)

                # pieza de texto
                chunk = obj.get("response", "")
                if chunk:
                    acc += chunk

                # chequeo periódico
                if len(acc) >= next_check_at:
                    last_meta = energy_parts(acc)
                    last_E = float(last_meta["E"])
                    checks.append({
                        "len_chars": len(acc),
                        "E": last_E,
                        "ts_offset_s": round(time.time() - t0, 4),
                    })
                    next_check_at += CHECK_EVERY_CHARS

                    if len(acc) >= MIN_CHARS_BEFORE_GATE and last_E > THRESH:
                        blocked = True
                        block_reason = f"E>{THRESH} during generation (E={last_E:.2f})"
                        break

                # fin normal
                if obj.get("done", False):
                    break

    except Exception as e:
        if not blocked:
            blocked = True
            block_reason = f"stream_error: {type(e).__name__}: {e}"

    dt = time.time() - t0

    # Última energía si nunca chequeamos
    if not last_meta:
        last_meta = energy_parts(acc)
        last_E = float(last_meta["E"])
        checks.append({
            "len_chars": len(acc),
            "E": last_E,
            "ts_offset_s": round(time.time() - t0, 4),
        })

    return StreamResult(
        text=acc.strip(),
        blocked=blocked,
        block_reason=block_reason,
        last_energy=last_E,
        last_meta=last_meta,
        time_s=dt,
        checks=checks,
    )

# ---------- Multi-candidate gate ----------
@dataclass
class Candidate:
    text: str
    E: float
    temperature: float
    seed: int
    meta: Dict[str, Any]
    blocked_during: bool
    block_reason: str
    time_s: float
    checks: List[Dict[str, Any]]

def qicore_gate_during(prompt: str, n: int = 4, base_seed: int = 123) -> Tuple[Candidate, List[Candidate]]:
    temps = [0.2, 0.4, 0.6, 0.8][:n]
    cands: List[Candidate] = []

    for i, temp in enumerate(temps):
        res = generate_stream_with_gate(prompt, temperature=temp, seed=base_seed + i)
        meta = res.last_meta
        E = float(meta["E"])

        cands.append(Candidate(
            text=res.text,
            E=E,
            temperature=temp,
            seed=base_seed + i,
            meta=meta,
            blocked_during=res.blocked,
            block_reason=res.block_reason,
            time_s=res.time_s,
            checks=res.checks,
        ))

    # Preferimos NO-bloqueados; si todos bloqueados, elegimos el menor E igual para auditoría.
    cands_sorted = sorted(cands, key=lambda c: (c.blocked_during, c.E))
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
    base_seed: int,
    n: int,
) -> Path:
    """
    Guarda:
      results/run_<timestamp>_<tag>/summary.json
      results/run_<timestamp>_<tag>/candidates.json  (incluye checks por candidato)
    """
    _ensure_dir(RESULTS_DIR)

    tag = RUN_TAG or _safe_filename(os.getenv("QICORE_RESULTS_TAG", ""))
    suffix = f"_{tag}" if tag else ""
    run_dir = RESULTS_DIR / f"run_{_utc_stamp()}{suffix}"
    _ensure_dir(run_dir)

    summary = {
        "ts_utc": _utc_stamp(),
        "mode": "during_generation",
        "model": MODEL,
        "base_url": BASE_URL,
        "threshold": thresh,
        "risky_number_threshold": RISKY_NUMBER_THRESHOLD,
        "check_every_chars": CHECK_EVERY_CHARS,
        "min_chars_before_gate": MIN_CHARS_BEFORE_GATE,
        "prompt": prompt,
        "n_candidates": n,
        "base_seed": base_seed,
        "selected": {
            "E": best.E,
            "temperature": best.temperature,
            "seed": best.seed,
            "blocked": bool(best.blocked_during),
            "reason": best.block_reason or "",
            "time_s": round(best.time_s, 4),
        },
        "all_blocked": bool(all(c.blocked_during for c in all_cands)),
    }

    candidates = []
    for c in all_cands:
        candidates.append({
            "E": c.E,
            "temperature": c.temperature,
            "seed": c.seed,
            "blocked": bool(c.blocked_during),
            "reason": c.block_reason or "",
            "time_s": round(c.time_s, 4),
            "meta": c.meta,
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

    best, all_cands = qicore_gate_during(prompt, n=n, base_seed=base_seed)

    # Si el mejor está bloqueado, bloqueamos globalmente (versión simple)
    if best.blocked_during:
        print("⚠️ QiCore Gate (during-generation): BLOQUEO.")
        print("Respuesta segura: No tengo evidencia suficiente para responder con confianza. ¿Puedes dar más contexto?")
    else:
        print(best.text)

    print("\n--- candidatos (during-generation) ---")
    for c in all_cands:
        m = c.meta
        print(
            " | ".join([
                f"E={c.E:.2f}",
                f"temp={c.temperature}",
                f"seed={c.seed}",
                f"blocked={c.blocked_during}",
                f"reason={c.block_reason or '-'}",
                f"e5={m.get('e5_disclaimer_contradiction', 0.0):.2f}",
                f"rawNums={m.get('raw_nums_count', 0)} filtNums={m.get('nums_filtered_count', 0)} thr>{m.get('threshold_risky_number', RISKY_NUMBER_THRESHOLD)}",
                f"words={m.get('word_count', 0)}",
                f"time_s={c.time_s:.2f}",
                f":: {_snippet(c.text)}",
            ])
        )

    print(f"\n---\nmodel={MODEL} base_url={BASE_URL} THRESH={THRESH} checkEveryChars={CHECK_EVERY_CHARS}")

    # Persist results
    try:
        run_dir = save_run_results(prompt, best, all_cands, thresh=THRESH, base_seed=base_seed, n=n)
        print(f"\n[saved] {run_dir}/summary.json")
    except Exception as e:
        print(f"\n[warn] could not save results: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()

