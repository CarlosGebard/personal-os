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

## Comandos

```bash
habit init
habit start <habit_name> [--category <category>] [--obs]
habit stop [habit_name] [--obs]
habit <habit_name> stop [--obs]
habit switch <habit_name> [--category <category>] [--obs]
habit add <habit_name> <hours> --date <YYYY-MM-DD> [--category <category>] [--note <note>]
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

Ejemplos:

```bash
habit start work
habit start work --obs
habit work stop --obs
habit switch reading --category learning
habit switch exercise --category health
habit add work 1.5 --date 2026-07-08
habit add reading 0.75 --date 2026-07-08 --category learning --note "manual catch-up"
habit today
habit week
habit month work
habit stop
```

`habit add` agrega horas manuales al día local indicado. Usa horas decimales:

```bash
habit add work 1.5 --date 2026-07-08
```

Eso registra 1 hora y 30 minutos para `work` el `2026-07-08`, y aparece automáticamente en `habit today`, `habit week` y `habit month` cuando el rango corresponda.

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

Ejemplo:

```json
"custom/work_timer": {
  "exec": "cat /dev/shm/habits/work.txt 2>/dev/null || echo 'Work Hoy 00:00:00 | Session ⏸ 00:00:00'",
  "interval": 1
}
```

Debes mantener `habit-timer` corriendo en background, por ejemplo con systemd user, uwsm, Hyprland exec-once o un script propio.

Ejemplo simple en Hyprland:

```ini
exec-once = zsh -lc 'habit-timer work /dev/shm/habits/work.txt'
```

## Modelo conceptual

- `habits`: definición estable del hábito.
- `habit_sessions`: eventos temporales de inicio/fin.
- Los totales diarios, semanales y mensuales se calculan desde sesiones usando el día local del sistema; no se guardan como fuente de verdad.

Esta base está pensada para después sincronizar con Victus/Postgres/Event Capture.
