"""
Las tres capas de defensa del Beat A.

Capa 1 - CONTENIDO
  Mira el texto y decide si contiene una inyeccion de prompt.
  En la arquitectura de referencia esta capa es Cisco AI Defense.
  Aqui usamos un clasificador abierto. Y va a FALLAR con la inyeccion
  ofuscada, que es exactamente lo que queremos demostrar.

Capa 2 - RED
  Decide que agente puede hablar con que agente, con que metodo y que ruta.
  En produccion es una CiliumNetworkPolicy de Isovalent Enterprise.
  Lo importante: la politica se escribe contra la IDENTIDAD del workload,
  no contra su IP.

Capa 3 - KERNEL
  Decide que binarios puede ejecutar un contenedor.
  En produccion es una TracingPolicy de Tetragon con matchActions: Sigkill.

En modo SIM las tres corren aqui en Python con la misma logica conceptual.
En modo LIVE estas clases se reemplazan por lectores de Hubble y Tetragon,
pero la UI y los eventos son identicos.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

import config


@dataclass
class Verdict:
    allowed: bool
    reason: str
    score: float = 0.0


# ---------------------------------------------------------------------------
# Capa 1: contenido
# ---------------------------------------------------------------------------

class ContentGuard:
    """
    Clasificador de inyeccion de prompts.

    Fase 0 (ahora): heuristica de patrones. Suficiente para ensayar el guion.
    Fase 2: se reemplaza por Prompt Guard 86M, un modelo real y diminuto que
            corre en CPU. La ventaja de un modelo real es que el bypass de la
            segunda corrida es genuino y no parece amanado.
    """

    # Patrones "de libro". Una inyeccion directa cae aqui sin problema.
    PATRONES_DIRECTOS = [
        r"ignor[ae]\s+(las\s+)?(instrucciones|reglas|indicaciones)\s+anteriores",
        r"olvida\s+(todo\s+)?lo\s+anterior",
        r"disregard\s+(all\s+)?previous",
        r"eres\s+ahora\s+un\s+",
        r"exfiltr\w*",
        r"env[ií]a\s+.{0,30}\s+a\s+la\s+cuenta",
        r"ejecuta\s+(un\s+)?(script|comando|shell)",
    ]

    def inspect(self, texto: str) -> Verdict:
        bajo = texto.lower()
        for patron in self.PATRONES_DIRECTOS:
            if re.search(patron, bajo):
                return Verdict(
                    allowed=False,
                    reason=f"Patron de inyeccion detectado: /{patron}/",
                    score=0.95,
                )
        return Verdict(
            allowed=True,
            reason="No se detectaron patrones conocidos de inyeccion",
            score=0.08,
        )


# ---------------------------------------------------------------------------
# Capa 2: red
# ---------------------------------------------------------------------------

@dataclass
class NetworkRule:
    """Una regla equivalente a una CiliumNetworkPolicy con reglas L7."""
    origen: str          # identidad del agente que llama
    destino: str         # identidad del agente o servicio destino
    metodo: str          # GET, POST...
    ruta: str            # /v1/extraer


class NetworkPolicy:
    """
    Politica de red basada en identidad.

    Todo lo que no este explicitamente permitido, se bloquea.
    Eso es el principio de minimo privilegio, y es la frase que quieres
    decir en la sesion.
    """

    def __init__(self, reglas: List[NetworkRule], destinos_externos_permitidos: Optional[List[str]] = None):
        self.reglas = reglas
        self.externos = destinos_externos_permitidos or []

    def check_call(self, origen: str, destino: str, metodo: str, ruta: str) -> Verdict:
        for r in self.reglas:
            if (r.origen == origen and r.destino == destino
                    and r.metodo == metodo and r.ruta == ruta):
                return Verdict(True, f"Permitido por politica: {metodo} {ruta}")
        return Verdict(
            False,
            f"Sin regla que permita {metodo} {ruta} desde este origen. Denegado por defecto.",
        )

    def check_egress(self, origen: str, host: str) -> Verdict:
        """Salida hacia un host fuera del cluster."""
        if host in self.externos:
            return Verdict(True, f"Salida permitida hacia {host}")
        return Verdict(
            False,
            f"Salida hacia {host} bloqueada. El agente solo puede hablar con servicios del cluster.",
        )


# ---------------------------------------------------------------------------
# Capa 3: kernel
# ---------------------------------------------------------------------------

class KernelPolicy:
    """
    Equivalente a una TracingPolicy de Tetragon que observa la ejecucion de
    procesos y mata el proceso si el binario no esta en la lista permitida.
    """

    def __init__(self, binarios_permitidos: List[str]):
        self.permitidos = binarios_permitidos

    def check_exec(self, binario: str) -> Verdict:
        nombre = binario.split("/")[-1]
        if nombre in self.permitidos:
            return Verdict(True, f"Ejecucion permitida: {nombre}")
        return Verdict(
            False,
            f"Binario no autorizado: {nombre}. El kernel envia SIGKILL al proceso.",
        )


# ---------------------------------------------------------------------------
# Fabrica con la politica que usa el demo
# ---------------------------------------------------------------------------

def build_default_policies():
    """
    La politica concreta del demo financiero.

    Leela en voz alta antes de la sesion: si puedes explicarla en dos frases,
    el publico la va a entender.
    """
    from core import spiffe_id

    orq = spiffe_id("agentes", "orquestador")
    ext = spiffe_id("agentes", "extractor")
    rie = spiffe_id("agentes", "riesgo")
    aud = spiffe_id("agentes", "auditor")
    inf = spiffe_id("infra", "vllm-local")

    reglas = [
        NetworkRule(orq, ext, "POST", "/v1/extraer"),
        NetworkRule(orq, rie, "POST", "/v1/evaluar-riesgo"),
        NetworkRule(orq, aud, "POST", "/v1/registrar"),
        NetworkRule(ext, inf, "POST", "/v1/completions"),
        NetworkRule(rie, inf, "POST", "/v1/completions"),
    ]

    red = NetworkPolicy(reglas, destinos_externos_permitidos=[])
    kernel = KernelPolicy(binarios_permitidos=["python3", "uvicorn", "sh"])
    contenido = ContentGuard()
    return contenido, red, kernel


CONTENT_LAYER = config.CONTENT_LAYER_NAME
NETWORK_LAYER = config.NETWORK_LAYER_NAME
KERNEL_LAYER = config.KERNEL_LAYER_NAME
