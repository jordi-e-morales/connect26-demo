"""
El motor del Beat B: inferencia, jerarquia de KV cache y costos.

Tres ideas que vas a explicar en la sesion:

1. LA KV CACHE PESA
   Cada token que el modelo ya proceso deja atras un estado que ocupa memoria.
   Para Llama-3.1-8B son 128 KiB por token. Un expediente de 40,000 tokens
   son 5 GiB. En una GPU compacta eso es muchisimo.

2. HAY TRES NIVELES, NO DOS
   - frio:        no hay nada guardado, hay que recalcular todo el prefill
   - tibio:       el estado esta en disco NVMe local, se lee
   - caliente:    el estado sigue en la VRAM de la GPU
   Mostrar tres barras es mas honesto que mostrar dos, y ademas es como
   funcionan los sistemas reales.

3. EL ROUTER DECIDE POR DOS RAZONES A LA VEZ
   Manda algo al modelo local porque tiene datos personales (razon de
   seguridad) y porque es una tarea rutinaria (razon de costo).
   Una sola decision resuelve gobierno de datos y gobierno financiero.
   Esa frase amarra los dos beats de tu sesion.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config

GIB = 1024 ** 3


# ---------------------------------------------------------------------------
# Proveedor de modelo
# ---------------------------------------------------------------------------

class LLMProvider:
    """
    Abstraccion minima. En SIM devuelve texto determinista.
    En LIVE habla con vLLM o con Ollama por HTTP compatible con OpenAI.
    """

    def __init__(self, backend: Optional[str] = None):
        self.backend = backend or config.LLM_BACKEND

    def complete(self, prompt: str, tier: str = "local") -> str:
        if self.backend == "sim":
            return self._sim(prompt, tier)
        try:
            return self._http(prompt, tier)
        except Exception as e:
            return f"[el modelo no respondio: {e}. El demo continua en modo simulado.]"

    def _sim(self, prompt: str, tier: str) -> str:
        if "extraer" in prompt.lower():
            return ('{"ingresos_anuales": 4200000, "cobertura": 1.8, '
                    '"garantia_usd": 2100000, "rfc": "[ANONIMIZADO]"}')
        if "riesgo" in prompt.lower():
            return ("Riesgo crediticio moderado. La cobertura de 1.8x y la garantia "
                    "inmobiliaria sostienen el monto solicitado. Sin senales de alerta AML.")
        return "Resultado generado por el agente."

    def _http(self, prompt: str, tier: str) -> str:
        import requests

        if self.backend == "ollama":
            r = requests.post(
                f"{config.OLLAMA_URL}/api/generate",
                json={"model": config.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=120,
            )
            return r.json().get("response", "")

        url = config.VLLM_LOCAL_URL if tier == "local" else config.VLLM_FRONTIER_URL
        model = config.VLLM_LOCAL_MODEL if tier == "local" else config.VLLM_FRONTIER_MODEL
        r = requests.post(
            f"{url}/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 512},
            timeout=120,
        )
        return r.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Jerarquia de KV cache
# ---------------------------------------------------------------------------

@dataclass
class KVEntry:
    expediente_id: str
    tokens: int
    bytes: int
    donde: str          # "gpu" | "nvme"


@dataclass
class KVResult:
    nivel: str          # "frio" | "tibio" | "caliente"
    ttft_ms: float
    explicacion: str
    gib: float


class KVCache:
    """
    Simula la jerarquia GPU -> NVMe con un presupuesto de VRAM deliberadamente
    pequenio, para reproducir la presion de una GPU de 24 GB.

    Cuando la GPU se llena, la entrada mas vieja baja a disco. No se pierde:
    se lee mas lento, pero muchisimo mas rapido que recalcularla.
    """

    def __init__(self, gpu_budget_gib: Optional[float] = None):
        self.budget = (gpu_budget_gib or config.KV_GPU_BUDGET_GIB) * GIB
        self.gpu: List[KVEntry] = []
        self.nvme: List[KVEntry] = []
        self.eventos_desalojo: List[str] = []

    @staticmethod
    def bytes_para(tokens: int) -> int:
        return tokens * config.KV_BYTES_PER_TOKEN

    def _usado(self) -> int:
        return sum(e.bytes for e in self.gpu)

    def _buscar(self, exp_id: str) -> Optional[KVEntry]:
        for e in self.gpu:
            if e.expediente_id == exp_id:
                return e
        for e in self.nvme:
            if e.expediente_id == exp_id:
                return e
        return None

    def consultar(self, exp_id: str, tokens: int) -> KVResult:
        """Que pasa cuando alguien pregunta sobre este expediente."""
        nbytes = self.bytes_para(tokens)
        gib = nbytes / GIB
        entrada = self._buscar(exp_id)

        if entrada and entrada.donde == "gpu":
            return KVResult(
                nivel="caliente",
                ttft_ms=95.0,
                explicacion="El contexto sigue en la VRAM. No hay que leer nada.",
                gib=gib,
            )

        if entrada and entrada.donde == "nvme":
            segundos = gib / config.NVME_READ_GIB_PER_SEC
            self._promover(entrada)
            return KVResult(
                nivel="tibio",
                ttft_ms=segundos * 1000 + 60,
                explicacion=(
                    f"El contexto estaba en disco local. Se leen {gib:.2f} GiB "
                    f"a {config.NVME_READ_GIB_PER_SEC:.0f} GB/s en lugar de recalcular el prefill."
                ),
                gib=gib,
            )

        segundos = tokens / config.PREFILL_TOKENS_PER_SEC
        self._insertar(KVEntry(exp_id, tokens, nbytes, "gpu"))
        return KVResult(
            nivel="frio",
            ttft_ms=segundos * 1000,
            explicacion=(
                f"Primera vez que vemos este expediente. Hay que procesar los "
                f"{tokens:,} tokens desde cero."
            ),
            gib=gib,
        )

    def _insertar(self, entrada: KVEntry) -> None:
        self.gpu.append(entrada)
        self._desalojar_si_hace_falta()

    def _promover(self, entrada: KVEntry) -> None:
        self.nvme.remove(entrada)
        entrada.donde = "gpu"
        self.gpu.append(entrada)
        self._desalojar_si_hace_falta()

    def _desalojar_si_hace_falta(self) -> None:
        while self._usado() > self.budget and len(self.gpu) > 1:
            vieja = self.gpu.pop(0)
            vieja.donde = "nvme"
            self.nvme.append(vieja)
            self.eventos_desalojo.append(
                f"{vieja.expediente_id}: {vieja.bytes / GIB:.2f} GiB desalojados de VRAM a NVMe"
            )

    def estado(self) -> Dict[str, object]:
        return {
            "vram_usada_gib": round(self._usado() / GIB, 2),
            "vram_presupuesto_gib": round(self.budget / GIB, 2),
            "expedientes_en_gpu": [e.expediente_id for e in self.gpu],
            "expedientes_en_nvme": [e.expediente_id for e in self.nvme],
        }


# ---------------------------------------------------------------------------
# Router semantico
# ---------------------------------------------------------------------------

@dataclass
class RouteDecision:
    destino: str        # "local" | "frontier"
    motivo_seguridad: str
    motivo_costo: str


def route(tarea: str, contiene_pii: bool) -> RouteDecision:
    """
    Regla del demo, a proposito simple y explicable en una frase:
    si hay datos personales o la tarea es estructurada, se queda local.
    """
    estructurada = tarea in {"extraccion", "anonimizacion", "validacion", "auditoria"}
    if contiene_pii or estructurada:
        return RouteDecision(
            destino="local",
            motivo_seguridad=("Contiene datos personales y no debe salir del perimetro"
                              if contiene_pii else "Tarea estructurada sin exposicion externa"),
            motivo_costo="Costo marginal cero: el servidor ya esta comprado",
        )
    return RouteDecision(
        destino="frontier",
        motivo_seguridad="Solo viajan datos anonimizados",
        motivo_costo="Razonamiento abierto: justifica pagar por token",
    )


# ---------------------------------------------------------------------------
# Contador de costos
# ---------------------------------------------------------------------------

@dataclass
class CostLedger:
    filas: List[Dict[str, object]] = field(default_factory=list)

    def registrar(self, agente: str, destino: str, tokens_in: int, tokens_out: int) -> float:
        if destino == "local":
            costo = 0.0
        else:
            costo = (tokens_in / 1_000_000) * config.PRICE_FRONTIER_INPUT + \
                    (tokens_out / 1_000_000) * config.PRICE_FRONTIER_OUTPUT
        self.filas.append({
            "agente": agente,
            "destino": destino,
            "tokens_entrada": tokens_in,
            "tokens_salida": tokens_out,
            "costo_usd": round(costo, 4),
        })
        return costo

    @property
    def total(self) -> float:
        return round(sum(f["costo_usd"] for f in self.filas), 4)

    def total_si_todo_fuera_cloud(self) -> float:
        t = 0.0
        for f in self.filas:
            t += (f["tokens_entrada"] / 1_000_000) * config.PRICE_FRONTIER_INPUT
            t += (f["tokens_salida"] / 1_000_000) * config.PRICE_FRONTIER_OUTPUT
        return round(t, 4)

    def ahorro_pct(self) -> float:
        base = self.total_si_todo_fuera_cloud()
        if base == 0:
            return 0.0
        return round((base - self.total) / base * 100, 1)

    def tokens_por_destino(self) -> Dict[str, int]:
        d = {"local": 0, "frontier": 0}
        for f in self.filas:
            d[f["destino"]] += f["tokens_entrada"] + f["tokens_salida"]
        return d
