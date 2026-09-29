# Victus Habit Tracker

Tracker local-first de hábitos y timers personales. La fuente de verdad es SQLite; los archivos en `/dev/shm` son solo salida para Waybar u otra UI.

## Requisitos

- Python 3.10+
- zsh

No depende de Timewarrior.

## Instalación recomendada

Desde la carpeta del proyecto:

```bash
python -m pip install -e .
```

Después deberías poder usar:

```bash
habit init
habit create work
habit start work
habit add work 1.5 --date 2026-07-08
habit status
habit today work
habit stop
```

## Instalación sin pip editable

Si quieres correrlo directo desde zsh sin instalar el paquete, agrega esto a tu `~/.zshrc` cambiando la ruta al lugar donde dejaste el repo:

```zsh
export PYTHONPATH="$HOME/path/to/victus-habit-tracker/src:$PYTHONPATH"
export PATH="$HOME/path/to/victus-habit-tracker/scripts:$PATH"
```

Luego recarga zsh:

```zsh
source ~/.zshrc
```

Y prueba:

```bash
habit init
habit create work
habit start work
```

## Ruta de la base de datos

Por defecto usa:

```text
./data/tracker.db
```

Puedes cambiarla con:

```zsh
export VICTUS_HABITS_DB="$HOME/Documents/01-Proyects/personal-os/data/tracker.db"
```

`data/` queda fuera de Git porque contiene estado local de runtime.

## Chuleta diaria

```bash
# Ver tiempo en curso y de hoy
habit status
habit today

# Iniciar / detener / cambiar hábito
habit start work
habit stop
habit switch reading

# Registrar hábitos y métricas de hoy
habit workout --yes
habit steps 8500
habit stream --yes

# Traer los pasos del iPhone por Taildrop
habit import health

# Ver resúmenes
habit week
habit month
```

Para otro día, agrega `--date YYYY-MM-DD`; por ejemplo:

```bash
habit steps 8500 --date 2026-08-11
```

## Comandos

```bash
habit init
habit create <habit_name> [--category <category>]
habit start <habit_name> [--obs]
habit stop [habit_name] [--obs]
habit <habit_name> stop [--obs]
habit switch <habit_name> [--obs]
habit add <habit_name> <hours> --date <YYYY-MM-DD> [--note <note>]
habit delete <habit_name>
habit workout --yes|--no [--date <YYYY-MM-DD>] [--note <note>]
habit steps <count> [--date <YYYY-MM-DD>]
habit stream --yes|--no [--date <YYYY-MM-DD>]
habit fill week|month [--work-habit <habit_name>] [--all]
habit import health
habit import obsidian <habits-folder> --from <YYYY-MM-DD> --to <YYYY-MM-DD> [--work-habit work] [--dry-run]
habit export json <vault-habits-data-folder> [--month <YYYY-MM>]
habit export obsidian <vault-habits-folder> [--month <YYYY-MM>]
habit update obsidian [--month <YYYY-MM>]
habit sync google-sheets [--authorize]
habit status
habit today
habit today <habit_name>
habit week
habit week <habit_name>
habit semana [habit_name]
habit month
habit month <habit_name>
habit mes [habit_name]
habit list
```

## Google Sheets: horas de trabajo para ChatGPT

La fuente de verdad sigue siendo SQLite. La integración exporta solamente el hábito
`work` a una spreadsheet que ChatGPT puede leer desde Google Drive; no sincroniza la
base de datos ni escribe otros hábitos.

Instala las dependencias actualizadas y crea en Google Cloud un cliente OAuth de tipo
**Desktop app**, con la Google Sheets API habilitada. Guarda el JSON de cliente en
`data/google/client.google-oauth.json`; `data/` está ignorada por Git y contiene el
estado local del proyecto. Luego configura el ID en el archivo local `.env`:

```zsh
cp .env.example .env
# Edita .env y pega solo el ID de la spreadsheet, no la URL completa.
source .env
```

El ID es la parte de la URL situada entre `/d/` y `/edit`. Carga `.env` en cada
terminal donde uses `habit`, o incorpora sus variables a tu configuración de shell.
Autoriza una vez desde tu PC —se abre el navegador y el token se guarda con permisos
privados— y realiza la primera carga completa:

```bash
uv sync
habit sync google-sheets --authorize
```

La spreadsheet recibe dos pestañas gestionadas por el tracker:

- `work_sessions`: historial global de todas las sesiones `work`.
- `work_today`: total del día, sesiones completadas y la sesión activa. La fórmula se
  recalcula cada minuto mientras haya una sesión activa.

Después de configurar las variables, `habit start work`, `habit stop`, `habit switch`
cuando afecte a `work`, y `habit add work ...` sincronizan automáticamente. Si Google
no está disponible, el comando local se completa igual y muestra una advertencia; usa
`habit sync google-sheets` para reintentar. No edites manualmente esas dos pestañas:
la siguiente sincronización reemplaza solo sus datos.

Mientras `work` esté activo, `habit start work` mantiene además un proceso local que
repite la sincronización cada 10 minutos. `habit stop` o cambiar a otro hábito lo
detiene. El PID y el log viven en `data/google/work-sync.pid` y
`data/google/work-sync.log`.

Ejemplos:

```bash
habit create work
habit create reading --category learning
habit create exercise --category health
habit start work
habit start work --obs
habit work stop --obs
habit switch reading
habit switch exercise
habit add work 1.5 --date 2026-07-08
habit add reading 0.75 --date 2026-07-08 --note "manual catch-up"
habit workout --yes --note "upper body"
habit steps 8500
habit stream --yes
habit fill week
habit fill week --work-habit "deep work"
habit import health
habit import obsidian /home/carlos/Documents/03-Obsidian/01-Proyects/Vida --from 2026-03-01 --to 2026-06-30 --work-habit work
habit export json /home/carlos/Documents/03-Obsidian/01-Proyects/Vida/data --month 2026-07
habit update obsidian
habit today
habit week
habit month work
habit stop
habit delete work
```

Los hábitos se crean explícitamente con `habit create`. `habit start`, `habit switch` y `habit add` solo aceptan hábitos ya creados; si escribes mal el nombre, por ejemplo `habit start woek`, el comando falla y no crea un hábito accidental.

Solo puede existir un hábito corriendo a la vez. Si ya hay uno activo, `habit start <habit_name>` falla; usa `habit stop` para detenerlo o `habit switch <habit_name>` para cambiar al siguiente hábito en un solo comando.

`habit add` agrega horas manuales al día local indicado. Usa horas decimales:

```bash
habit add work 1.5 --date 2026-07-08
```

Eso registra 1 hora y 30 minutos para `work` el `2026-07-08`, y aparece automáticamente en `habit today`, `habit week` y `habit month` cuando el rango corresponda.

En la importación histórica desde Obsidian, `deep_work` usa el formato `horas.minutos`: por ejemplo, `3.55` equivale a 3 horas y 55 minutos.

## Métricas diarias

Además de sesiones por tiempo, puedes registrar métricas de día completo:

```bash
habit workout --yes --date 2026-07-08 --note "legs"
habit workout --no --date 2026-07-09
habit steps 12000 --date 2026-07-08
habit stream --yes --date 2026-07-08
```

Para rellenar datos faltantes de forma secuencial, incluyendo horas del hábito `work`:

```bash
habit fill week
habit fill month
```

Por defecto `fill` solo pregunta por campos faltantes: días con 0 horas de `work`, workout sin valor, pasos sin valor y stream sin valor. Si tu hábito de trabajo se llama distinto, usa:

```bash
habit fill week --work-habit "deep work"
```

Usa `--all` para volver a pasar por todos los campos.

### Importar pasos desde Health Auto Export

```bash
habit import health
```

La primera vez, permite que tu usuario retire archivos de Taildrop (requiere tu
contraseña de administrador):

```bash
sudo tailscale set --operator="$USER"
```

El comando recibe los archivos pendientes de Taildrop en `data/imports/taildrop/`,
conservándolos allí, y usa el archivo `HealthAutoExport-*.json` más reciente. Solo
importa la métrica de pasos y actualiza los días cuyo total haya cambiado; al repetirlo,
los días sin cambios se dejan intactos.

`habit delete <habit_name>` borra el hábito completo y todas sus sesiones registradas:

```bash
habit delete woek
```

## Export a Obsidian

Export recomendado: un JSON mensual para usar como fuente de datos del dashboard.

```bash
habit export json /home/carlos/Documents/03-Obsidian/01-Proyects/Vida/data --month 2026-07
```

Atajo para tu vault configurado:

```bash
habit update obsidian
```

Eso escribe:

```text
/home/carlos/Documents/03-Obsidian/01-Proyects/Vida/data/habits-2026-07.json
```

Cuando exportas el mes actual, el archivo llega solo hasta ayer. Por ejemplo, el `2026-07-12` exporta hasta `2026-07-11`, porque el día actual todavía no está completo.

Cada fila del JSON tiene:

- `gym`: booleano de workout.
- `daily_note`: nota libre del día.
- `steps`: pasos del día.
- `streamed`: booleano de stream.
- Un campo por hábito con horas reales como número; por ejemplo el hábito `deep work` exporta `deep_work: 1.5`.

Ejemplo DataviewJS:

```dataviewjs
const month = "2026-07";
const raw = await dv.io.load(`01-Proyects/Vida/data/habits-${month}.json`);
const rows = JSON.parse(raw);

function num(val) {
  return Number(val) || 0;
}

function formatHours(hours) {
  const totalMinutes = Math.round(hours * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${h}h ${m}m`;
}

const days = rows.length;
const totalWork = rows.reduce((sum, r) => sum + num(r.work), 0);
const avgWork = days > 0 ? totalWork / days : 0;
const totalSteps = rows.reduce((sum, r) => sum + num(r.steps), 0);
const avgSteps = days > 0 ? totalSteps / days : 0;
const gymDays = rows.filter(r => r.gym === true).length;
const streamDays = rows.filter(r => r.streamed === true).length;

dv.header(3, `Stats ${month}`);
dv.list([
  `Work: ${formatHours(totalWork)} (avg ${formatHours(avgWork)} / dia)`,
  `Steps: ${totalSteps} (avg ${Math.round(avgSteps)} / dia)`,
  `Gym: ${gymDays} dias`,
  `Streams: ${streamDays} dias`,
  `Dias registrados: ${days}`,
]);
```

Si tu hábito se llama `deep work`, cambia `r.work` por `r.deep_work`.

También existe el export a notas Markdown diarias:

```bash
habit export obsidian /home/carlos/Documents/03-Obsidian/01-Proyects/Vida --month 2026-07
```

## Timer visual

Para dejar un texto persistente y vivo para OBS:

```bash
habit start work --obs
habit work stop --obs
```

Eso escribe por defecto en:

```text
./data/obs/work.txt
```

Puedes elegir otra ruta:

```bash
habit start work --obs --obs-file /tmp/work.txt
```

`habit start work --obs` escribe el primer texto y deja un renderer en background que actualiza el archivo segundo a segundo. `habit work stop --obs` detiene la sesión, corta ese renderer y deja el texto final.

Si quieres correr el renderer manualmente:

Para escribir el timer de work:

```bash
habit-timer work /dev/shm/habits/work.txt
```

Salida esperada:

```text
Work Hoy 03:42:11 | Session ● 00:38:05
```

Si no está activo:

```text
Work Hoy 03:42:11 | Session ⏸ 00:00:00
```

Para probar una sola vez:

```bash
habit-timer work /dev/shm/habits/work.txt --once
```

## Waybar

Para mostrar solo el estado global del timer, agrega este módulo a Waybar. Muestra `󱎫` cuando hay un hábito activo y `󱎪` cuando no lo hay; el tooltip indica el nombre del hábito activo.

```json
"modules-right": ["pulseaudio", "battery", "custom/habit_timer", "tray", "clock", "custom/power"],

"custom/habit_timer": {
  "exec": "zsh -lc 'output=\"$(UV_CACHE_DIR=/tmp/victus-uv-cache /home/carlos/.local/share/mise/installs/uv/latest/uv-x86_64-unknown-linux-musl/uv run --directory /home/carlos/Documents/01-Proyects/personal-os --no-sync habit status 2>/dev/null)\"; if [[ \"$output\" == Active:* ]]; then habit_name=\"${output#Active: }\"; habit_name=\"${habit_name%% since *}\"; printf \"{\\\"text\\\":\\\"󱎫\\\",\\\"tooltip\\\":\\\"Habit timer activo: %s\\\",\\\"class\\\":\\\"active\\\"}\\n\" \"$habit_name\"; else printf \"{\\\"text\\\":\\\"󱎪\\\",\\\"tooltip\\\":\\\"Habit timer detenido\\\",\\\"class\\\":\\\"inactive\\\"}\\n\"; fi'",
  "return-type": "json",
  "interval": 2
}
```

Y en `style.css`:

```css
#custom-habit_timer {
  margin: 6px 0 6px 8px;
  padding: 0 10px;
}

#custom-habit_timer.active { color: #a6e3a1; }
#custom-habit_timer.inactive { color: @wb_muted; }
```

Este indicador consulta directamente el tracker, por lo que no requiere mantener un renderer en segundo plano. El renderer `habit-timer` sigue siendo útil si además quieres mostrar el tiempo transcurrido.

Ejemplo simple en Hyprland:

```ini
exec-once = zsh -lc 'habit-timer work /dev/shm/habits/work.txt'
```

## Modelo conceptual

- `habits`: definición estable del hábito.
- `habit_sessions`: eventos temporales de inicio/fin.
- Los totales diarios, semanales y mensuales se calculan desde sesiones usando el día local del sistema; no se guardan como fuente de verdad.

Esta base está pensada para después sincronizar con Victus/Postgres/Event Capture.
