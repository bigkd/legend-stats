#!/usr/bin/env python3
"""
Recolector del ranking global de Liga Leyenda (Top 1-200) de Clash of Clans.

Cada ejecucion:
  1. Se conecta a la API OFICIAL de Clash of Clans (developer.clashofclans.com).
     Usa login por email/contrasena, que crea/renueva automaticamente la clave
     de API para la IP actual -> funciona en GitHub Actions aunque la IP cambie.
  2. Descarga el Top 200 mundial por copas.
  3. Calcula los cortes de copas en las posiciones objetivo (1, 10, 20, 50, 100, 200).
  4. Los compara con la foto del reset ANTERIOR para sacar el +/-.
  5. Guarda:
       - data/history/AAAA-MM-DD.json  (foto completa del dia)
       - data/latest.json              (lo que lee el dashboard)

Pensado para ejecutarse una vez al dia, justo despues del reset diario de leyenda
(05:00 UTC). Variables de entorno necesarias: COC_EMAIL y COC_PASSWORD.
"""

import asyncio
import datetime as dt
import json
import os
import pathlib
import sys

import coc

# Posiciones cuyo corte de copas queremos mostrar en la tabla.
TARGET_RANKS = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200]

BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HIST_DIR = DATA_DIR / "history"

MESES_ES = [
    "", "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


def etiqueta_fecha(d: dt.date) -> str:
    return f"{d.day} {MESES_ES[d.month]} {d.year}"


def trofeos_en_puesto(top, rank):
    """Copas del jugador en 'rank'. Si ese puesto exacto no esta, coge el mas cercano."""
    exacto = next((p for p in top if p["rank"] == rank), None)
    if exacto:
        return exacto["trophies"]
    cercano = min(top, key=lambda p: abs(p["rank"] - rank))
    return cercano["trophies"]


def foto_previa(hoy_iso: str):
    """Devuelve (fecha_iso, {rank: trofeos}) de la foto guardada mas reciente
    anterior a hoy. Si no hay ninguna, devuelve (None, {})."""
    if not HIST_DIR.exists():
        return None, {}
    ficheros = sorted(p.name for p in HIST_DIR.glob("*.json"))
    previas = [f for f in ficheros if f[:-5] < hoy_iso]
    if not previas:
        return None, {}
    ultima = previas[-1]
    with open(HIST_DIR / ultima, encoding="utf-8") as fh:
        datos = json.load(fh)
    mapa = {p["rank"]: p["trophies"] for p in datos.get("top200", [])}
    return ultima[:-5], mapa


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

    top = [
        {"rank": p.rank, "name": p.name, "tag": p.tag, "trophies": p.trophies}
        for p in jugadores
    ]
    top.sort(key=lambda p: p["rank"])
    return top


def main():
    top = asyncio.run(descargar_top200())
    if not top:
        sys.exit("ERROR: la API no devolvio jugadores.")

    ahora = dt.datetime.now(dt.timezone.utc)
    hoy_iso = ahora.date().isoformat()

    prev_fecha, prev_mapa = foto_previa(hoy_iso)

    cutoffs = []
    for rank in TARGET_RANKS:
        trofeos = trofeos_en_puesto(top, rank)
        prev = prev_mapa.get(rank)
        delta = (trofeos - prev) if prev is not None else None
        cutoffs.append({"rank": rank, "trophies": trofeos, "delta": delta})

    salida = {
        "captured_at": ahora.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reset_label": etiqueta_fecha(ahora.date()),
        "previous_date": prev_fecha,
        "target_ranks": TARGET_RANKS,
        "cutoffs": cutoffs,
        "top200": top,
    }

    HIST_DIR.mkdir(parents=True, exist_ok=True)
    with open(HIST_DIR / f"{hoy_iso}.json", "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)
    with open(DATA_DIR / "latest.json", "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)

    print(f"OK: {len(top)} jugadores. Foto {hoy_iso}. Reset previo: {prev_fecha}.")
    for c in cutoffs:
        d = "n/d" if c["delta"] is None else f"{c['delta']:+d}"
        print(f"  Top {c['rank']:>4}: {c['trophies']} copas ({d})")


if __name__ == "__main__":
    main()
