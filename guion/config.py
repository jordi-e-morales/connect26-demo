"""
Configuracion central del demo.

Todo el demo tiene DOS MODOS:

  SIM  -> todo corre en tu laptop, sin GPU, sin Kubernetes, sin internet.
          Las capas de seguridad y la inferencia usan logica local.
          Sirve para ensayar el guion completo.

  LIVE -> la UI es la misma, pero los datos vienen de componentes reales
          (vLLM en el servidor con GPU, Cilium/Hubble, Tetragon).
          Esto se activa en la Fase 3 y 4.

La idea es que NUNCA cambies la UI. Solo cambias de donde salen los datos.
"""

import os

# ---------------------------------------------------------------------------
# Modo de ejecucion
# ---------------------------------------------------------------------------
# Valores posibles: "SIM" o "LIVE"
MODE = os.getenv("DEMO_MODE", "SIM")

# ---------------------------------------------------------------------------
# Inferencia
# ---------------------------------------------------------------------------
# En SIM no se usa ningun modelo: las respuestas son deterministas.
# En LIVE apuntamos a vLLM (o a Ollama si estas probando en la laptop).
#
# LLM_BACKEND: "sim" | "ollama" | "vllm"
LLM_BACKEND = os.getenv("LLM_BACKEND", "sim")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Instancia "local" (la que representa al agente on-prem en el UCS)
VLLM_LOCAL_URL = os.getenv("VLLM_LOCAL_URL", "http://localhost:8000/v1")
VLLM_LOCAL_MODEL = os.getenv("VLLM_LOCAL_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct")

# Instancia "frontier" (modelo mas grande, tambien local, para no depender del WiFi)
VLLM_FRONTIER_URL = os.getenv("VLLM_FRONTIER_URL", "http://localhost:8001/v1")
VLLM_FRONTIER_MODEL = os.getenv("VLLM_FRONTIER_MODEL", "Qwen/Qwen2.5-32B-Instruct")

# ---------------------------------------------------------------------------
# Precios para el calculo de costos (USD por 1M de tokens)
# ---------------------------------------------------------------------------
# El modelo local tiene costo marginal cero: el servidor ya esta comprado.
# El frontier se cobra por token. Estos numeros son de ejemplo: ajustalos a
# los precios que quieras citar en la sesion.
PRICE_LOCAL_INPUT = 0.0
PRICE_LOCAL_OUTPUT = 0.0
PRICE_FRONTIER_INPUT = 2.50
PRICE_FRONTIER_OUTPUT = 10.00

# ---------------------------------------------------------------------------
# Caracteristicas del hardware que estamos contando (para el Beat B)
# ---------------------------------------------------------------------------
# Llama-3.1-8B: 32 capas, 8 KV heads (GQA), head_dim 128, bf16 (2 bytes)
# KV por token = 2 (K y V) * 8 heads * 128 dim * 2 bytes * 32 capas = 131072 B = 128 KiB
KV_BYTES_PER_TOKEN = 2 * 8 * 128 * 2 * 32  # 131072 bytes = 128 KiB

# Presupuesto de VRAM que le damos a la KV cache (GiB).
# Lo ponemos bajo a proposito para reproducir la presion de una GPU de 24 GB.
KV_GPU_BUDGET_GIB = float(os.getenv("KV_GPU_BUDGET_GIB", "3.0"))

# Velocidades para estimar tiempos en modo SIM.
PREFILL_TOKENS_PER_SEC = 4000.0   # velocidad de prefill de la GPU
NVME_READ_GIB_PER_SEC = 3.0       # lectura de la KV cache desde disco local

# ---------------------------------------------------------------------------
# Etiquetas que se muestran en pantalla
# ---------------------------------------------------------------------------
# Importante: la capa de contenido en una arquitectura real es Cisco AI Defense.
# En este lab no la tenemos, y lo decimos en pantalla en lugar de fingirlo.
CONTENT_LAYER_NAME = "Guardrail abierto (sustituto de Cisco AI Defense)"
NETWORK_LAYER_NAME = "Isovalent Enterprise Platform (Cilium)"
KERNEL_LAYER_NAME = "Isovalent Enterprise Runtime Security (Tetragon)"

CONTENT_LAYER_DISCLAIMER = (
    "En la arquitectura de referencia esta capa es Cisco AI Defense. "
    "Este lab esta aislado, asi que usamos un clasificador abierto equivalente."
)
