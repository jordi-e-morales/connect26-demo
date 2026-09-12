# Demo: multi-agentes bajo control

Demo didáctico para la sesión de Cisco Connect. Muestra un enjambre de agentes
financieros y las tres capas de defensa que lo contienen, más la jerarquía de
caché y el control de costos.

Está pensado para que lo entiendas mientras lo construyes. Cada archivo hace una
sola cosa y está comentado en español.

---

## Fase 0: correrlo hoy en tu laptop

No necesitas GPU, ni Kubernetes, ni internet, ni API keys.

### Paso 1 — abre una terminal en la carpeta del proyecto

```bash
cd cisco-connect-demo
```

### Paso 2 — crea un entorno virtual

Un entorno virtual es una carpeta aislada con las librerías de este proyecto,
para no ensuciar tu Python del sistema.

```bash
python3 -m venv .venv
```

Actívalo. En macOS o Linux:

```bash
source .venv/bin/activate
```

En Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Sabrás que funcionó porque tu prompt ahora empieza con `(.venv)`.

### Paso 3 — instala las dos librerías que hacen falta

```bash
pip install -r requirements.txt
```

### Paso 4 — levanta la aplicación

```bash
streamlit run app.py
```

Se abre solo en `http://localhost:8501`.

### Paso 5 — recorre el demo

1. En la barra lateral elige **Inyección directa** y ve a la pestaña
   **Beat A**. Presiona *Preparar la corrida* y luego *Siguiente paso* varias
   veces. La capa de contenido detiene el ataque.
2. Cambia a **Inyección ofuscada** y vuelve a preparar. Ahora la capa de
   contenido no lo detecta, y son la red y el kernel las que contienen el daño.
   Ese contraste es el corazón de la sesión.
3. Ve a la pestaña **Beat B** y prepara la corrida. Vas a ver los tres niveles
   de caché y el contador de costos.
4. La pestaña **Guion** tiene qué decir en cada paso.

Si todo esto funciona, ya tienes el 70% del trabajo hecho. Lo que falta es
cambiar de dónde vienen los datos, no cómo se ven.

---

## Qué hace cada archivo

| Archivo | Qué contiene | Cuándo lo vas a tocar |
|---|---|---|
| `config.py` | Modo SIM o LIVE, endpoints, precios, tamaño de la KV caché | Fase 3, al apuntar al servidor |
| `core.py` | Identidad, directorio de agentes, bus de mensajes y eventos | Fase 2, al conectar AGNTCY real |
| `security.py` | Las tres capas: contenido, red, kernel | Fase 2 y 3 |
| `scenarios.py` | Los tres expedientes de crédito | Cuando quieras más variedad para el booth |
| `inference.py` | Proveedor de modelo, jerarquía de KV caché, router y costos | Fase 3 |
| `agents.py` | Los cuatro agentes y los dos guiones ejecutables | Al ajustar el ritmo de los beats |
| `app.py` | La interfaz | Al preparar los presets del booth |

### La idea que sostiene todo

La interfaz nunca cambia. Lo único que cambia entre tu laptop y el servidor con
GPU es **de dónde salen los eventos**. Por eso puedes ensayar el guion completo
en un avión y el día del evento solo cambiar una variable.

### Por qué los eventos se revelan de uno en uno

Cuando presionas *Preparar la corrida*, el guion completo se ejecuta y se
guardan todos los pasos. Después los revelas con el botón mientras hablas.

Esto tiene una ventaja importante para una sesión en vivo: si algo del backend
falla, falla al preparar, no a media narración frente a 200 personas.

---

## Las fases que siguen

### Fase 1 — ensayar (esta semana, sin tocar código)

Corre el demo con cronómetro en mano. Cada beat debe caber en 5 minutos
hablando en voz alta. Si no cabe, el problema es de guion, no de código.
Ajusta los textos en `agents.py` y en la pestaña Guion.

**Opcional:** conecta Ollama para que los agentes usen un modelo real en tu
laptop. Instala Ollama, corre `ollama pull llama3.2`, y arranca así:

```bash
LLM_BACKEND=ollama streamlit run app.py
```

### Fase 2 — seguridad real en una máquina virtual Linux

Aquí es donde Cilium y Tetragon dejan de ser simulados.

Advertencia importante: **Tetragon necesita un kernel Linux con BTF**. Si
trabajas en macOS, el kernel de Docker Desktop normalmente no lo tiene y esto
va a fallar. Usa una máquina virtual Ubuntu 24.04 (con Multipass, UTM o Lima),
no Docker Desktop directamente.

Pasos, en orden:

1. Levanta la VM Ubuntu con al menos 4 vCPU y 8 GB de RAM.
2. Verifica BTF: `ls /sys/kernel/btf/vmlinux` debe existir.
3. Instala `kind` y crea un cluster sin CNI por defecto.
4. Instala Cilium con Hubble habilitado.
5. Instala Tetragon.
6. Despliega los cuatro agentes como pods.
7. Escribe la `CiliumNetworkPolicy` y la `TracingPolicy`.

Las reglas ya están escritas en Python dentro de `security.py`, en
`build_default_policies()`. Ese diccionario es la traducción directa de lo que
va en el YAML, así que léelo antes de escribir los manifiestos.

### Fase 3 — inferencia real en el servidor con GPU

Sobre dCloud, con el L40S. Dos instancias de vLLM en puertos distintos: una
"local" limitada con `--gpu-memory-utilization 0.3` y una "frontier" con el
resto. Luego cambia `LLM_BACKEND=vllm` y apunta los endpoints en `config.py`.

Todo corre dentro de dCloud. Tu laptop solo abre el navegador. Si la interfaz
corre en tu laptop y el modelo en el servidor, cada medición de tiempo incluye
la latencia de la VPN y el número que muestras deja de ser honesto.

### Fase 4 — presets del booth

Tres modos de presentación sobre el mismo código: un bucle corto de atracción,
una versión guiada de 4 minutos con solo el Beat A, y la versión completa.

---

## Lo que este demo simula y lo que no

Sé explícito en la sesión. La honestidad aquí te da credibilidad, no te la quita.

| Componente | Fase 0 (hoy) | Producción |
|---|---|---|
| Capa de contenido | Heurística de patrones | Cisco AI Defense |
| Capa de red | Diccionario de reglas en Python | Isovalent Enterprise Platform (Cilium) |
| Capa de kernel | Lista de binarios permitidos | Isovalent Enterprise Runtime Security (Tetragon) |
| Identidad | Cadena estilo SPIFFE | SPIRE con certificados x509 rotativos |
| Directorio | Diccionario en memoria | AGNTCY Directory con registros OASF |
| Inferencia | Respuestas deterministas | vLLM en Cisco UCS con GPU |

La capa de contenido no la vas a tener con el producto real en este lab, y está
bien: en el guion esa capa **falla a propósito**. Ponlo en pantalla una vez, con
naturalidad, y sigue adelante.

---

## Si algo no funciona

- **`streamlit: command not found`** — no activaste el entorno virtual. Repite
  el paso 2.
- **La página se abre en blanco** — mira la terminal, Streamlit imprime el error
  completo ahí.
- **Cambié un archivo y no se actualiza** — Streamlit recarga solo al guardar;
  si no, presiona la tecla `R` en el navegador.
- **Quiero empezar de cero** — botón *Reiniciar todo* en la barra lateral.
