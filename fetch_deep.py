#!/usr/bin/env python3
"""
Reconstruccion del Top 1-2000 de Liga Leyenda (aproximado).

La API oficial solo publica el Top 200 en vivo. Para llegar mas hondo, nos
construimos nuestra propia clasificacion:

  1. LISTA DE CANDIDATOS (data/pool.json): tags de jugadores que suelen andar
     arriba. Se siembra con la clasificacion FINAL de las ultimas temporadas
     cerradas (eso si lo da la API oficial, y en profundidad) y se va ampliando
     sola cada dia con quien veamos por arriba.
  2. SONDEO DIARIO: en el reset, consultamos las copas actuales de todos esos
     jugadores, los ordenamos y leemos los cortes en los puestos objetivo.
  3. El Top 200 lo tomamos EXACTO de la API oficial y lo fusionamos, para clavar
     la parte alta y medir la calidad de la cobertura.

Escribe data/deep.json. NO toca nada del proceso del Top 200 (latest.json).
Pensado para correr una vez al dia, en el reset (04:58 UTC). La foto se congela
en la 1a ejecucion del dia de leyenda; las siguientes no la pisan.

Variables de entorno: COC_EMAIL, COC_PASSWORD.
Opcional: FORCE_CAPTURE=1 recongela; FORCE_POOL=1 rehace la lista de candidatos.
"""

import asyncio
import datetime as dt
import json
import os
import pathlib
import statistics
import sys

import coc

DEEP_RANKS = [1, 10, 25, 50, 100, 150, 200, 350, 500, 750, 1000, 1250, 1500, 2000]
MAX_RANK = 2000

LEAGUE_ID = 29000022          # Liga Leyenda
LEGEND_MIN = 5000             # copas minimas para estar en leyenda
POOL_SEASONS = 2             # cuantas temporadas cerradas sembrar
POOL_PER_SEASON = 6000       # cuantos tags coger de cada temporada
POLL_CONCURRENCY = 60        # sondeos simultaneos

RESET_DELTA = dt.timedelta(hours=4, minutes=58)

BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HIST_DIR = DATA_DIR / "history_deep"
POOL_FILE = DATA_DIR / "pool.json"

MESES_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic"]


def etiqueta_fecha(d): return f"{d.day} {MESES_ES[d.month]} {d.year}"
def iso_z(m): return m.replace(microsecond=0).isoformat().replace("+00:00", "Z")
def dia_leyenda(m): return (m - RESET_DELTA).date()


def cutoff(trophies_sorted, rank):
    """Copas del puesto 'rank' (1-indexado) en una lista ya ordenada desc."""
    if not trophies_sorted:
        return None
    i = min(rank, len(trophies_sorted)) - 1
    return trophies_sorted[i]


def reset_previo(dia_iso):
    if not HIST_DIR.exists():
        return None, {}
    ficheros = sorted(p.name for p in HIST_DIR.glob("*.json"))
    previas = [f for f in ficheros if f[:-5] < dia_iso]
    if not previas:
        return None, {}
    with open(HIST_DIR / previas[-1], encoding="utf-8") as fh:
        datos = json.load(fh)
    top = datos.get("top_trophies", [])
    mapa = {r: (top[r - 1] if r <= len(top) else None) for r in DEEP_RANKS}
    return previas[-1][:-5], mapa


def tendencia(rank, series):
    diffs = []
    for i in range(1, len(series)):
        a = series[i - 1][rank - 1] if rank <= len(series[i - 1]) else None
        b = series[i][rank - 1] if rank <= len(series[i]) else None
        if a is not None and b is not None:
            diffs.append(b - a)
    diffs = diffs[-7:]
    return statistics.median(diffs) if diffs else 0


# ---------- Lista de candidatos (pool) ----------

def cargar_pool():
    if POOL_FILE.exists():
        try:
            with open(POOL_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {"seasons": [], "tags": []}


async def sembrar_pool(client, pool):
    """Anade tags de las ultimas temporadas cerradas si aun no estan sembradas."""
    try:
        seasons = await client.get_seasons(LEAGUE_ID)
    except Exception as e:
        print("Aviso: no pude listar temporadas:", e)
        return pool
    seasons = sorted(seasons)[-POOL_SEASONS:]
    ya = set(pool.get("seasons", []))
    forzar = os.environ.get("FORCE_POOL") == "1"
    tags = set(pool.get("tags", []))
    nuevas = []
    for s in seasons:
        if s in ya and not forzar:
            continue
        n = 0
        try:
            it = await client.get_season_rankings(LEAGUE_ID, s)
            async for rp in it:
                tags.add(rp.tag)
                n += 1
                if n >= POOL_PER_SEASON:
                    break
        except Exception as e:
            print(f"Aviso: temporada {s} fallo:", e)
            continue
        nuevas.append(s)
        print(f"Temporada {s}: +{n} tags sembrados.")
    pool["seasons"] = sorted(ya.union(nuevas))
    pool["tags"] = sorted(tags)
    return pool


async def sondear(client, tags):
    """Devuelve {tag: trofeos} de los que estan en leyenda ahora mismo."""
    res = {}
    sem = asyncio.Semaphore(POLL_CONCURRENCY)

    async def uno(tag):
        async with sem:
            try:
                p = await client.get_player(tag)
                if p.trophies is not None and p.trophies >= LEGEND_MIN:
                    res[tag] = p.trophies
            except Exception:
                pass

    await asyncio.gather(*(uno(t) for t in tags))
    return res


async def construir(client):
    # Top 200 oficial (exacto)
    oficiales = await client.get_location_players("global", limit=200)
    oficial_map = {p.tag: p.trophies for p in oficiales}
    oficial_sorted = sorted((p.trophies for p in oficiales), reverse=True)

    # Lista de candidatos
    pool = cargar_pool()
    pool = await sembrar_pool(client, pool)
    tags = set(pool.get("tags", []))
    tags.update(oficial_map.keys())          # acumula la parte alta

    # Sondeo
    sondeo = await sondear(client, list(tags))
    # Fusionamos: la parte alta la fijamos con el dato oficial
    sondeo.update(oficial_map)

    # Acumulamos en el pool cualquiera que este en leyenda
    pool["tags"] = sorted(set(pool.get("tags", [])).union(sondeo.keys()))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(POOL_FILE, "w", encoding="utf-8") as fh:
        json.dump(pool, fh, ensure_ascii=False)

    trophies_sorted = sorted(sondeo.values(), reverse=True)[:MAX_RANK]
    return trophies_sorted, len(pool["tags"]), oficial_sorted


def main():
    email = os.environ.get("COC_EMAIL")
    password = os.environ.get("COC_PASSWORD")
    if not email or not password:
        sys.exit("ERROR: define COC_EMAIL y COC_PASSWORD.")

    ahora = dt.datetime.now(dt.timezone.utc)
    now_iso = iso_z(ahora)
    ld = dia_leyenda(ahora)
    ld_iso = ld.isoformat()
    reset_file = HIST_DIR / f"{ld_iso}.json"
    forzar = os.environ.get("FORCE_CAPTURE") == "1"
    corte = dt.datetime(ld.year, ld.month, ld.day, 4, 58, tzinfo=dt.timezone.utc)

    async def run():
        client = coc.Client(key_names="legend-deep", key_count=1)
        await client.login(email, password)
        try:
            return await construir(client)
        finally:
            await client.close()

    trophies_sorted, pool_size, oficial_sorted = asyncio.run(run())
    if not trophies_sorted:
        sys.exit("ERROR: sondeo vacio.")

    HIST_DIR.mkdir(parents=True, exist_ok=True)

    # Congelar la foto del reset (1a ejecucion del dia de leyenda)
    if reset_file.exists() and not forzar:
        with open(reset_file, encoding="utf-8") as fh:
            rd = json.load(fh)
        top = rd["top_trophies"]
        reset_at = rd.get("reset_at", now_iso)
        pool_size = rd.get("pool_size", pool_size)
        congelada = False
    else:
        top = trophies_sorted
        reset_at = now_iso
        with open(reset_file, "w", encoding="utf-8") as fh:
            json.dump({"legend_day": ld_iso, "reset_at": reset_at,
                       "pool_size": pool_size, "top_trophies": top},
                      fh, ensure_ascii=False)
        congelada = True

    cap = dt.datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
    reset_lag = max(0, round((cap - corte).total_seconds() / 60))

    prev_date, prev_map = reset_previo(ld_iso)

    # Serie historica para la tendencia
    series = []
    for f in sorted(HIST_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                series.append(json.load(fh).get("top_trophies", []))
        except Exception:
            pass
    trend_samples = min(max(len(series) - 1, 0), 7)

    cutoffs = []
    for rank in DEEP_RANKS:
        reset_v = cutoff(top, rank)
        prev = prev_map.get(rank)
        delta = (reset_v - prev) if (reset_v is not None and prev is not None) else None
        pred = round(reset_v + tendencia(rank, series)) if reset_v is not None else None
        cutoffs.append({"rank": rank, "reset": reset_v, "delta": delta, "pred": pred})

    # Calidad: comparamos nuestro puesto 200 reconstruido con el oficial
    recon200 = cutoff(top, 200)
    oficial200 = cutoff(oficial_sorted, 200)
    quality = {"recon200": recon200, "oficial200": oficial200,
               "diff": (recon200 - oficial200) if (recon200 and oficial200) else None}

    salida = {
        "reset_at": reset_at,
        "reset_lag_min": reset_lag,
        "legend_day": ld_iso,
        "reset_label": etiqueta_fecha(ld),
        "previous_reset_date": prev_date,
        "trend_samples": trend_samples,
        "pool_size": pool_size,
        "ranked_now": len(trophies_sorted),
        "quality": quality,
        "deep_ranks": DEEP_RANKS,
        "cutoffs": cutoffs,
    }
    with open(DATA_DIR / "deep.json", "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)

    print(f"OK deep. Dia {ld_iso}. Reset {'CONGELADO' if congelada else 'existente'} "
          f"({reset_at}, {reset_lag} min). Pool {pool_size}, en leyenda {len(trophies_sorted)}. "
          f"Calidad #200 recon {recon200} vs oficial {oficial200}.")
    for c in cutoffs:
        d = "n/d" if c["delta"] is None else f"{c['delta']:+d}"
        print(f"  Top {c['rank']:>4}: reset {c['reset']} ({d}) | prev.prox {c['pred']}")


if __name__ == "__main__":
    main()
