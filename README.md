# Tu Briefing diario de IA & Geopolítica 📰

Una "app" que cada mañana recoge lo nuevo de todas tus fuentes (YouTube, blogs y
newsletters), **agrupa las noticias repetidas en un solo resumen** y te lo deja
**todo en castellano** en una página que abres desde el móvil o el PC.

Funciona **solo, en la nube y gratis**: no necesitas tener el ordenador encendido
ni saber programar. Sigue los pasos de abajo una vez y ya está.

---

## Lo que necesitas (todo gratis)

1. Una cuenta de **GitHub** (donde vive el proyecto y se ejecuta solo).
2. Una **clave de API de Gemini** (la IA que resume y traduce).

Ninguna de las dos cuesta dinero para este uso.

---

## Puesta en marcha (una sola vez, ~1 hora con calma)

### Paso 1 · Crear la cuenta de GitHub
1. Entra en https://github.com y pulsa **Sign up**.
2. Crea tu usuario (apunta el **nombre de usuario**, lo usaremos luego).

### Paso 2 · Subir este proyecto a un repositorio
1. Arriba a la derecha, pulsa **+** → **New repository**.
2. Nombre: por ejemplo `briefing`. Déjalo en **Public**. Pulsa **Create repository**.
3. En la página del repo vacío, pulsa **uploading an existing file**.
4. **Arrastra TODA la carpeta del proyecto** (todos los archivos y carpetas que te
   he dado) a la ventana y pulsa **Commit changes**.

### Paso 3 · Conseguir tu clave de Gemini (gratis)
1. Entra en https://aistudio.google.com con tu cuenta de Google.
2. Pulsa **Get API key** (arriba a la izquierda) → **Create API key**.
3. Copia la clave (una cadena larga). **No la compartas con nadie.**

### Paso 4 · Guardar la clave en el repositorio (de forma segura)
1. En tu repo, ve a **Settings** → (menú izquierdo) **Secrets and variables** → **Actions**.
2. Pulsa **New repository secret**.
3. En **Name** escribe exactamente: `GEMINI_API_KEY`
4. En **Secret** pega tu clave. Pulsa **Add secret**.

> La clave queda oculta. Nunca aparece en la web ni en el código.

### Paso 5 · Dar permiso de escritura a la automatización
1. **Settings** → **Actions** → **General**.
2. Baja hasta **Workflow permissions**.
3. Marca **Read and write permissions** y pulsa **Save**.

### Paso 6 · Lanzar el primer briefing a mano
1. Ve a la pestaña **Actions** (arriba).
2. Si te pide habilitar los workflows, acepta.
3. En la izquierda elige **Briefing diario** → botón **Run workflow** → **Run workflow**.
4. Espera unos minutos (verás un círculo girando y luego un ✅). Recoge y resume todo;
   la primera vez tarda más porque mira el último día entero.

### Paso 7 · Publicar la página (GitHub Pages)
1. **Settings** → **Pages**.
2. En **Source** elige **Deploy from a branch**.
3. Branch: **main** y carpeta **/docs**. Pulsa **Save**.
4. Espera 1-2 minutos. Arriba aparecerá tu dirección, del tipo:
   `https://TU-USUARIO.github.io/briefing/`

### Paso 8 · Abrirlo e instalarlo como app en el móvil
1. Abre esa dirección en el navegador del móvil.
2. **iPhone (Safari):** botón Compartir → **Añadir a pantalla de inicio**.
   **Android (Chrome):** menú ⋮ → **Instalar app** / **Añadir a pantalla de inicio**.
3. Te queda un icono que se abre como una app de verdad. ✅

¡Listo! A partir de ahora se actualiza **solo cada mañana**.

---

## Uso del día a día

### Añadir o quitar fuentes
Edita el archivo **`sources.yaml`** (puedes hacerlo desde el móvil):
1. En tu repo, abre `sources.yaml` y pulsa el lápiz ✏️ (**Edit**).
2. Para **añadir**: copia una línea parecida y cámbiala.
   - YouTube: `- {name: "Mi Canal", type: youtube, topic: ia, handle: "@elhandle"}`
   - Blog/newsletter: `- {name: "Mi Web", type: blog, topic: geo, url: "https://laweb.com"}`
   - `topic` es `ia` o `geo` (solo una pista; cada noticia se reclasifica sola).
3. Para **quitar**: borra su línea.
4. Abajo, pulsa **Commit changes**. En la próxima actualización ya lo tiene en cuenta.

> ¿Cómo saco el `@handle` de un canal de YouTube? Entra en el canal y mira la URL:
> `youtube.com/@LoQueSea` → el handle es `@LoQueSea`.

### Cambiar la hora de actualización
En `.github/workflows/daily.yml`, la línea `- cron: "0 6 * * *"` marca las 06:00 UTC
(~08:00 en España). Cambia el `6` por otra hora **en UTC**.

### Lanzarlo cuando quieras
Pestaña **Actions** → **Briefing diario** → **Run workflow**.

---

## Si algo no funciona
- **Falla en "Generar el briefing"**: revisa que el secret se llame exactamente
  `GEMINI_API_KEY` y que la clave sea válida.
- **No se publica / no se actualiza la web**: comprueba el Paso 5 (permisos de
  escritura) y el Paso 7 (Pages en `main` `/docs`).
- **Una fuente no aparece**: puede que esa web no tenga RSS o esté de pago (en ese
  caso solo se ve el titular). No pasa nada: el resto sigue funcionando.
- Cualquier duda, pásame el mensaje de error de la pestaña **Actions** y lo vemos.

---

## Cómo está montado (por curiosidad)
- `sources.yaml` — tus fuentes y ajustes (lo único que tocas).
- `main.py` — orquesta todo el proceso.
- `aggregator/fetch.py` — recoge RSS, YouTube y transcripciones.
- `aggregator/summarize.py` — agrupa duplicados y resume en español con Gemini.
- `aggregator/render.py` — genera la página `docs/index.html`.
- `templates/index.html` — el diseño del briefing.
- `.github/workflows/daily.yml` — la automatización diaria.
- `docs/` — lo que se publica (web + iconos + PWA).
- `state/` — memoria de lo ya visto (para no repetir).
