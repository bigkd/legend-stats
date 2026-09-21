#!/usr/bin/env python3
"""
Recolector del ranking global de Liga Leyenda (Top 1-200) de Clash of Clans.

Produce, por cada posicion objetivo, tres datos:
  - copas ACTUALES   (se refrescan en cada ejecucion)
  - copas AL RESET    (foto congelada del inicio del dia de leyenda)
  - +/- RESET ANTERIOR (foto de hoy menos la de ayer)

El dia de leyenda empieza/acaba a las 04:58 UTC. La foto del reset se "congela"
en la PRIMERA ejecucion de cada dia de leyenda (justo tras las 04:58 UTC); las
ejecuciones posteriores del mismo dia solo actualizan las copas actuales, sin
tocar la foto del reset.

Conexion: API OFICIAL de Clash of Clans (developer.clashofclans.com), login por
email/contrasena (gestiona la clave para la IP actual, ideal en GitHub Actions).

Variables de entorno: COC_EMAIL y COC_PASSWORD.
Opcional: FORCE_CAPTURE=1 vuelve a congelar la foto del reset de hoy (uso manual).
"""

import asyncio
import datetime as dt
import json
import os
import pathlib
import statistics
import sys

import coc

# Posiciones cuyo corte de copas queremos mostrar.
TARGET_RANKS = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
                110, 120, 130, 140, 150, 160, 170, 180, 190, 200]

# El dia de leyenda arranca a esta hora UTC (04:58).
RESET_DELTA = dt.timedelta(hours=4, minutes=58)

BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HIST_DIR = DATA_DIR / "history"

MESES_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic"]


def etiqueta_fecha(d: dt.date) -> str:
    return f"{d.day} {MESES_ES[d.month]} {d.year}"


def iso_z(momento: dt.datetime) -> str:
    return momento.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def dia_leyenda(momento: dt.datetime) -> dt.date:
    """Fecha del dia de leyenda al que pertenece 'momento' (cambia a las 04:58 UTC)."""
    return (momento - RESET_DELTA).date()


def trofeos_en_puesto(top, rank):
    """Copas del jugador en 'rank'. Si ese puesto exacto no esta, coge el mas cercano."""
    exacto = next((p for p in top if p["rank"] == rank), None)
    if exacto:
        return exacto["trophies"]
    return min(top, key=lambda p: abs(p["rank"] - rank))["trophies"]


def reset_previo(dia_iso: str):
    """(fecha_iso, {rank: trofeos}) de la foto del reset mas reciente anterior a
    'dia_iso'. Si no hay ninguna, (None, {})."""
    if not HIST_DIR.exists():
        return None, {}
    ficheros = sorted(p.name for p in HIST_DIR.glob("*.json"))
    previas = [f for f in ficheros if f[:-5] < dia_iso]
    if not previas:
        return None, {}
    with open(HIST_DIR / previas[-1], encoding="utf-8") as fh:
        datos = json.load(fh)
    mapa = {p["rank"]: p["trophies"] for p in datos.get("top200", [])}
    return previas[-1][:-5], mapa


async def descargar_top200():
    email = os.environ.get("COC_EMAIL")
    password = os.environ.get("COC_PASSWORD")
    if not email or not password:
        sys.exit("ERROR: define las variables de entorno COC_EMAIL y COC_PASSWORD.")

    client = coc.Client(key_names="legend-tracker", key_count=1)
    await client.login(email, password)
    try:
        jugadores = await client.get_location_players("global", limit=200)
    finally:
        await client.close()

    top = [{"rank": p.rank, "name": p.name, "tag": p.tag, "trophies": p.trophies}
           for p in jugadores]
    top.sort(key=lambda p: p["rank"])
    return top


def main():
    ahora = dt.datetime.now(dt.timezone.utc)
    now_iso = iso_z(ahora)
    ld = dia_leyenda(ahora)
    ld_iso = ld.isoformat()
    reset_file = HIST_DIR / f"{ld_iso}.json"
    forzar = os.environ.get("FORCE_CAPTURE") == "1"

    # Copas ACTUALES: siempre se descargan.
    current_top = asyncio.run(descargar_top200())
    if not current_top:
        sys.exit("ERROR: la API no devolvio jugadores.")

    HIST_DIR.mkdir(parents=True, exist_ok=True)

    # Momento exacto del corte (04:58 UTC de ese dia de leyenda) para medir
    # cuanto tardo en tomarse la foto respecto al reset.
    corte = dt.datetime(ld.year, ld.month, ld.day, 4, 58, tzinfo=dt.timezone.utc)

    def minutos_tras_corte(cap_iso):
        cap = dt.datetime.fromisoformat(cap_iso.replace("Z", "+00:00"))
        return max(0, round((cap - corte).total_seconds() / 60))

    # Foto del RESET: se congela en la 1a ejecucion del dia de leyenda.
    if reset_file.exists() and not forzar:
        with open(reset_file, encoding="utf-8") as fh:
            reset_data = json.load(fh)
        reset_top = reset_data["top200"]
        reset_at = reset_data.get("reset_at", now_iso)
        reset_lag = reset_data.get("reset_lag_min")
        if reset_lag is None:
            reset_lag = minutos_tras_corte(reset_at)
        congelada = False
    else:
        reset_top = current_top
        reset_at = now_iso
        reset_lag = minutos_tras_corte(reset_at)
        with open(reset_file, "w", encoding="utf-8") as fh:
            json.dump({"legend_day": ld_iso, "reset_at": reset_at,
                       "reset_lag_min": reset_lag, "top200": reset_top},
                      fh, ensure_ascii=False, indent=2)
        congelada = True

    prev_date, prev_map = reset_previo(ld_iso)

    # --- Tendencia y prediccion del proximo reset ---
    # Cargamos todas las fotos de reset guardadas (incluida la de hoy) y, para
    # cada puesto, calculamos cuanto suele subir su corte de un reset al siguiente
    # (mediana de los ultimos 7 cambios diarios -> robusta ante el reset de temporada).
    series = []
    for f in sorted(HIST_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                dd = json.load(fh)
        except Exception:
            continue
        series.append({p["rank"]: p["trophies"] for p in dd.get("top200", [])})

    def tendencia(rank):
        diffs = []
        for i in range(1, len(series)):
            a, b = series[i - 1].get(rank), series[i].get(rank)
            if a is not None and b is not None:
                diffs.append(b - a)
        diffs = diffs[-7:]
        return statistics.median(diffs) if diffs else 0

    trend_samples = min(max(len(series) - 1, 0), 7)
    reset_top200 = [{"rank": p["rank"], "trophies": p["trophies"]} for p in reset_top]
    pred_top200 = [{"rank": p["rank"], "trophies": round(p["trophies"] + tendencia(p["rank"]))}
                   for p in reset_top]

    cutoffs = []
    for rank in TARGET_RANKS:
        actual = trofeos_en_puesto(current_top, rank)
        reset = trofeos_en_puesto(reset_top, rank)
        prev = prev_map.get(rank)
        delta = (reset - prev) if prev is not None else None
        cutoffs.append({"rank": rank, "current": actual, "reset": reset, "delta": delta})

    salida = {
        "current_at": now_iso,
        "reset_at": reset_at,
        "legend_day": ld_iso,
        "reset_label": etiqueta_fecha(ld),
        "reset_lag_min": reset_lag,
        "previous_reset_date": prev_date,
        "trend_samples": trend_samples,
        "target_ranks": TARGET_RANKS,
        "cutoffs": cutoffs,
        "top200": current_top,
        "reset_top200": reset_top200,
        "pred_top200": pred_top200,
    }
    with open(DATA_DIR / "latest.json", "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)

    print(f"OK. Dia de leyenda {ld_iso}. Foto del reset {'CONGELADA ahora' if congelada else 'ya existia'} "
          f"({reset_at}, {reset_lag} min tras el corte). Copas actuales a {now_iso}. Reset previo: {prev_date}.")
    for c in cutoffs:
        d = "n/d" if c["delta"] is None else f"{c['delta']:+d}"
        print(f"  Top {c['rank']:>4}: actual {c['current']} | reset {c['reset']} ({d})")


if __name__ == "__main__":
    main()
