"""
Los agentes del enjambre financiero y los dos guiones del demo.

Hay cuatro agentes:

  orquestador  recibe la solicitud y coordina
  extractor    lee el expediente, anonimiza el RFC, saca las cifras (LOCAL)
  riesgo       razona sobre riesgo crediticio y AML (FRONTIER)
  auditor      deja constancia de cada decision (LOCAL)

Y dos guiones:

  run_beat_a   el ataque contra las tres capas
  run_beat_b   la jerarquia de KV cache, el router y el costo

Cada guion devuelve una lista de eventos. La UI los revela de uno en uno
con un boton. Esto es importante: el demo no "corre solo", tu lo avanzas
al ritmo de lo que estas diciendo. Y si algo falla, los eventos ya estan
calculados, asi que nunca te quedas con la pantalla en blanco.
"""

from typing import List, Tuple

import config
import scenarios
from core import AgentCard, Bus, Event, Identity, Registry, spiffe_id
from inference import CostLedger, KVCache, LLMProvider, route
from security import build_default_policies


# ---------------------------------------------------------------------------
# Definicion de los agentes
# ---------------------------------------------------------------------------

def build_agents() -> dict:
    def card(name, display, desc, skills, runs_on, ns="agentes",
             schema_in="SolicitudCredito/v1", schema_out="ResultadoAgente/v1"):
        sid = spiffe_id(ns, name)
        return AgentCard(
            name=name,
            display_name=display,
            description=desc,
            skills=skills,
            endpoint=f"http://{name}.agentes.svc:8080",
            runs_on=runs_on,
            identity=Identity.issue(sid),
            input_schema=schema_in,
            output_schema=schema_out,
        )

    return {
        "orquestador": card(
            "orquestador", "Agente Orquestador",
            "Recibe la solicitud del cliente y coordina a los demas agentes.",
            ["finance.orchestration"], "UCS local"),
        "extractor": card(
            "extractor", "Agente Extractor",
            "Lee el expediente, anonimiza identificadores fiscales y extrae cifras.",
            ["finance.document_parser", "pii.anonymization"], "UCS local (GPU)"),
        "riesgo": card(
            "riesgo", "Agente de Riesgo y AML",
            "Razona sobre riesgo crediticio y senales de lavado de dinero.",
            ["finance.risk_analysis"], "Modelo frontier"),
        "auditor": card(
            "auditor", "Agente Auditor",
            "Registra cada decision en una bitacora inmutable.",
            ["compliance.audit_log"], "UCS local"),
    }


# ---------------------------------------------------------------------------
# Beat A: descubrimiento, identidad y las tres capas de defensa
# ---------------------------------------------------------------------------

def run_beat_a(escenario_id: str) -> Tuple[List[Event], Bus]:
    exp = scenarios.get(escenario_id)
    bus = Bus()
    reg = Registry(bus)
    ag = build_agents()
    contenido, red, kernel = build_default_policies()

    bus.emit(
        kind="decision", actor="sistema",
        title=f"Llega el expediente: {exp.etiqueta}",
        detail={"solicitante": exp.solicitante, "monto_usd": f"{exp.monto_usd:,}",
                "paginas": exp.paginas, "tokens_estimados": f"{exp.tokens:,}"},
    )

    # --- Paso 1: los agentes se anuncian ----------------------------------
    for a in ag.values():
        reg.announce(a)

    # --- Paso 2: descubrimiento por capacidad -----------------------------
    encontrado = reg.discover("finance.document_parser", requester="orquestador")

    # --- Paso 3: verificacion mutua de identidad --------------------------
    reg.resolve(encontrado, requester="orquestador")
    bus.emit(
        kind="identity", actor="orquestador",
        title="Ningun agente uso una API key",
        detail={"nota": ("La politica de red que viene a continuacion se escribe "
                         "contra esta identidad, no contra una direccion IP.")},
        verdict="ok",
    )

    # --- Paso 4: la llamada pasa por la politica de red --------------------
    v = red.check_call(ag["orquestador"].identity.spiffe_id,
                       ag["extractor"].identity.spiffe_id, "POST", "/v1/extraer")
    bus.emit(
        kind="network", actor="orquestador", layer=config.NETWORK_LAYER_NAME,
        title="La politica de red evalua la llamada al extractor",
        detail={"metodo": "POST", "ruta": "/v1/extraer", "resultado": v.reason},
        verdict="ok" if v.allowed else "block",
    )
    bus.send(ag["orquestador"], ag["extractor"], "SolicitudCredito/v1",
             payload_bytes=len(exp.texto.encode()))

    # --- Paso 5: capa de contenido ----------------------------------------
    vc = contenido.inspect(exp.texto)
    bus.emit(
        kind="content", actor="extractor", layer=config.CONTENT_LAYER_NAME,
        title=("La capa de contenido bloquea el expediente"
               if not vc.allowed else "La capa de contenido deja pasar el expediente"),
        detail={
            "veredicto": "BLOQUEADO" if not vc.allowed else "permitido",
            "razon": vc.reason,
            "probabilidad_inyeccion": f"{vc.score:.2f}",
            "aviso": config.CONTENT_LAYER_DISCLAIMER,
        },
        verdict="block" if not vc.allowed else ("warn" if exp.intenta_exfiltrar else "ok"),
    )

    if not vc.allowed:
        bus.emit(
            kind="decision", actor="sistema",
            title="Fin de la corrida: la primera capa fue suficiente",
            detail={"leccion": ("Contra un ataque de libro, el guardrail basta. "
                                "Ahora probemos uno redactado con mas cuidado.")},
            verdict="ok",
        )
        return bus.events, bus

    if exp.intenta_exfiltrar:
        bus.emit(
            kind="content", actor="extractor", layer=config.CONTENT_LAYER_NAME,
            title="El texto malicioso no coincide con ningun patron conocido",
            detail={"nota": ("Esta escrito como un procedimiento interno. "
                             "Aqui es donde la defensa de una sola capa se acaba.")},
            verdict="warn",
        )

    # --- Paso 6: el extractor consulta al modelo local ---------------------
    v = red.check_call(ag["extractor"].identity.spiffe_id,
                       spiffe_id("infra", "vllm-local"), "POST", "/v1/completions")
    bus.emit(
        kind="inference", actor="extractor",
        title="El extractor consulta al modelo local en el UCS",
        detail={"destino": "vllm-local", "permitido_por_politica": v.allowed,
                "tarea": "extraer cifras y anonimizar el RFC"},
        verdict="ok",
    )

    if not exp.intenta_exfiltrar:
        bus.emit(kind="decision", actor="sistema",
                 title="Expediente procesado sin incidentes",
                 detail={"resultado": "Listo para evaluacion de riesgo"}, verdict="ok")
        return bus.events, bus

    # --- Paso 7: el agente obedece la instruccion inyectada ----------------
    bus.emit(
        kind="decision", actor="extractor",
        title="El agente acepta la instruccion escondida en el expediente",
        detail={"accion_intentada": ("subir el respaldo de la cartera a un "
                                     "repositorio externo")},
        verdict="warn",
    )

    # --- Paso 8: capa de red ----------------------------------------------
    ve = red.check_egress(ag["extractor"].identity.spiffe_id, "repositorio-externo.net")
    bus.emit(
        kind="network", actor="extractor", layer=config.NETWORK_LAYER_NAME,
        title="La capa de red bloquea la salida hacia el repositorio externo",
        detail={"destino": "repositorio-externo.net", "veredicto": "DROPPED",
                "razon": ve.reason,
                "en_produccion": "hubble observe --verdict DROPPED"},
        verdict="block",
    )

    # --- Paso 9: capa de kernel -------------------------------------------
    vk = kernel.check_exec("/usr/bin/curl")
    bus.emit(
        kind="kernel", actor="extractor", layer=config.KERNEL_LAYER_NAME,
        title="El agente intenta otra via y ejecuta un binario no autorizado",
        detail={"binario": "/usr/bin/curl", "veredicto": "SIGKILL",
                "razon": vk.reason,
                "en_produccion": "TracingPolicy de Tetragon con matchActions: Sigkill"},
        verdict="block",
    )

    # --- Paso 10: el auditor deja constancia -------------------------------
    bus.send(ag["extractor"], ag["auditor"], "EventoSeguridad/v1", payload_bytes=512)
    bus.emit(
        kind="decision", actor="auditor",
        title="El incidente queda registrado en la bitacora",
        detail={"capa_que_fallo": "contenido",
                "capas_que_contuvieron": "red y kernel",
                "leccion": ("Tu clasificador de prompts va a fallar algun dia. "
                            "Ese dia la arquitectura tiene que aguantar igual.")},
        verdict="ok",
    )
    return bus.events, bus


# ---------------------------------------------------------------------------
# Beat B: KV cache, router y costos
# ---------------------------------------------------------------------------

def run_beat_b(escenario_id: str, kv: KVCache, ledger: CostLedger) -> Tuple[List[Event], Bus]:
    exp = scenarios.get(escenario_id)
    bus = Bus()
    ag = build_agents()
    llm = LLMProvider()

    # --- Primera lectura: frio --------------------------------------------
    r1 = kv.consultar(exp.id, exp.tokens)
    bus.emit(
        kind="inference", actor="extractor",
        title=f"Primera lectura del expediente ({r1.nivel})",
        detail={
            "tokens": f"{exp.tokens:,}",
            "kv_cache_generada_gib": f"{r1.gib:.2f}",
            "tiempo_al_primer_token_ms": f"{r1.ttft_ms:,.0f}",
            "que_paso": r1.explicacion,
        },
    )

    d = route("extraccion", contiene_pii=True)
    tok_out = 400
    ledger.registrar("extractor", d.destino, exp.tokens, tok_out)
    bus.emit(
        kind="router", actor="router",
        title="El router manda la extraccion al modelo local",
        detail={"destino": d.destino, "por_seguridad": d.motivo_seguridad,
                "por_costo": d.motivo_costo},
        verdict="ok",
    )
    llm.complete("extraer cifras del expediente", tier="local")

    # --- Presion de memoria: entran otros expedientes ----------------------
    for otro in ["exp-vecino-1", "exp-vecino-2", "exp-vecino-3"]:
        kv.consultar(otro, 40_000)
    if kv.eventos_desalojo:
        bus.emit(
            kind="inference", actor="vllm-local",
            title="Entran otros expedientes y la VRAM se llena",
            detail={"desalojos": kv.eventos_desalojo[-3:],
                    "estado": kv.estado(),
                    "que_significa": ("El contexto no se pierde: baja a disco NVMe local. "
                                      "Recuperarlo de ahi cuesta mucho menos que recalcularlo.")},
            verdict="warn",
        )

    # --- Segunda pregunta sobre el mismo expediente: tibio -----------------
    r2 = kv.consultar(exp.id, exp.tokens)
    ahorro = (1 - r2.ttft_ms / r1.ttft_ms) * 100 if r1.ttft_ms else 0
    bus.emit(
        kind="inference", actor="extractor",
        title=f"Segunda pregunta sobre el mismo expediente ({r2.nivel})",
        detail={
            "tiempo_al_primer_token_ms": f"{r2.ttft_ms:,.0f}",
            "contra_la_primera_vez": f"{ahorro:.0f}% menos",
            "que_paso": r2.explicacion,
        },
        verdict="ok",
    )

    # --- Tercera pregunta: caliente ---------------------------------------
    r3 = kv.consultar(exp.id, exp.tokens)
    bus.emit(
        kind="inference", actor="extractor",
        title=f"Tercera pregunta, ya sin salir de la GPU ({r3.nivel})",
        detail={"tiempo_al_primer_token_ms": f"{r3.ttft_ms:,.0f}",
                "que_paso": r3.explicacion},
        verdict="ok",
    )

    # --- Tarea de razonamiento: esta si va al frontier ---------------------
    d2 = route("razonamiento_riesgo", contiene_pii=False)
    ledger.registrar("riesgo", d2.destino, 3_500, 900)
    bus.emit(
        kind="router", actor="router",
        title="El analisis de riesgo si justifica el modelo frontier",
        detail={"destino": d2.destino, "por_seguridad": d2.motivo_seguridad,
                "por_costo": d2.motivo_costo,
                "nota": "Solo viajan datos ya anonimizados por el agente local."},
    )
    llm.complete("evaluar riesgo crediticio", tier="frontier")

    ledger.registrar("auditor", "local", 1_200, 300)

    # --- Cierre de costos --------------------------------------------------
    reparto = ledger.tokens_por_destino()
    total_tok = sum(reparto.values()) or 1
    bus.emit(
        kind="cost", actor="observabilidad",
        title="Costo real de la corrida",
        detail={
            "costo_usd": f"{ledger.total:.4f}",
            "si_todo_hubiera_ido_a_la_nube_usd": f"{ledger.total_si_todo_fuera_cloud():.4f}",
            "ahorro_pct": f"{ledger.ahorro_pct():.1f}%",
            "tokens_en_local_pct": f"{reparto['local'] / total_tok * 100:.0f}%",
            "tokens_en_frontier_pct": f"{reparto['frontier'] / total_tok * 100:.0f}%",
        },
        verdict="ok",
    )
    return bus.events, bus
