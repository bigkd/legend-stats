# Ranking Liga Leyenda (Top 1–200) — Clash of Clans

Web que muestra el **corte de copas por posición** (Top 1, 10, 20, 50, 100 y 200) del
ranking global de Liga Leyenda, tal como estaba **en el reset diario**, con el **+/-**
respecto al día anterior. Incluye una calculadora de "cuántas copas necesito para subir
puestos".

Todo funciona **gratis** sobre GitHub: una tarea programada descarga los datos una vez al
día y GitHub Pages sirve la web. No necesitas ningún servidor.

> **Nota sobre la profundidad:** la API oficial de Clash of Clans solo publica el **Top 200**
> mundial en vivo. Por eso la tabla llega hasta el puesto 200. Los rangos más profundos
> (500, 1000, … 12.500) no están disponibles a diario de forma gratuita hoy en día.

---

## Qué hay en el repo

| Archivo | Para qué sirve |
|---|---|
| `index.html` | La web (dashboard). La sirve GitHub Pages. |
| `fetch_legend.py` | Script que descarga el Top 200 y calcula cortes y +/-. |
| `requirements.txt` | Dependencia de Python (`coc.py`). |
| `.github/workflows/update.yml` | Tarea programada diaria que ejecuta el script. |
| `data/latest.json` | Lo genera el script; es lo que lee la web. |
| `data/history/` | Una foto por día (histórico). |

---

## Puesta en marcha (una sola vez)

### 1. Cuenta de desarrollador de Clash of Clans
1. Entra en **https://developer.clashofclans.com** y regístrate (es gratis; usa un email
   y una contraseña que recuerdes: el script los usará).
2. No hace falta que crees ninguna clave a mano: el script genera y renueva la clave solo,
   con la IP correcta, cada vez que se ejecuta.

### 2. Sube este proyecto a un repositorio de GitHub
Crea un repositorio nuevo (público o privado) y sube estos archivos tal cual.

### 3. Guarda tus credenciales como *secrets*
En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
Crea dos:

| Nombre | Valor |
|---|---|
| `COC_EMAIL` | el email de tu cuenta de developer.clashofclans.com |
| `COC_PASSWORD` | la contraseña de esa cuenta |

*(Los secrets van cifrados; nadie que vea el repo puede leerlos.)*

### 4. Activa la tarea programada
En **Actions**, si te pide habilitar los workflows, acéptalo. Luego abre
**"Actualizar ranking de leyenda"** y pulsa **Run workflow** para lanzarlo a mano la primera
vez. Debería terminar en verde y crear `data/latest.json`.

### 5. Activa GitHub Pages
En **Settings → Pages**: en *Source* elige **Deploy from a branch**, rama `main` y
carpeta `/ (root)`. Guarda. En un minuto tendrás tu web en una URL tipo
`https://TUUSUARIO.github.io/TUREPO/`.

¡Listo! A partir de ahí, cada día a las **05:10 UTC** (~después del reset) la tarea se
ejecuta sola, guarda la foto del día y la web se actualiza con el nuevo +/-.

---

## Detalles

- **Horario del reset:** el reset diario de leyenda es a las **05:00 UTC**, que en España
  son las **07:00 en verano** y las **06:00 en invierno**. La tarea captura a las 05:10 UTC
  para coger la clasificación recién reseteada.
- **El +/-** de cada día compara la foto de hoy con la del día anterior. El primer día no
  habrá comparación (aparecerá `n/d`); a partir del segundo día ya verás las variaciones.
- **Cambiar las posiciones** que se muestran: edita la lista `TARGET_RANKS` en
  `fetch_legend.py` y `TARGETS` en `index.html` (deben coincidir).
- **Si en el futuro quieres profundidad (hasta el 12.500):** habría que montar una
  recolección propia o engancharse a un agregador cuando su API de leyenda vuelva a estar
  disponible. Escríbeme y lo ampliamos.

---

## Solución de problemas

- **El workflow falla al hacer login:** revisa que `COC_EMAIL` y `COC_PASSWORD` son
  correctos y que puedes entrar con ellos en developer.clashofclans.com.
- **La web muestra "Datos de ejemplo":** aún no existe `data/latest.json`. Lanza el workflow
  a mano (paso 4) y espera a que termine.
- **`coc.py` da un error de versión:** fija una versión concreta en `requirements.txt`
  (por ejemplo `coc.py==3.9.1`).
