"""
La interfaz del demo.

Como funciona: cada guion (Beat A y Beat B) se ejecuta completo al presionar
"Preparar", pero los eventos se revelan de UNO EN UNO con el boton "Siguiente".
Tu controlas el ritmo mientras hablas.

Ventaja para la sesion en vivo: los eventos ya estan calculados antes de que
empieces a avanzar. Si algo del backend falla, falla al preparar, no a media
narracion frente a la audiencia.

Para correrlo:
    streamlit run app.py
"""

import streamlit as st

import config
import scenarios
from agents import build_agents, run_beat_a, run_beat_b
from inference import CostLedger, KVCache

st.set_page_config(page_title="Multi-agentes bajo control", layout="wide")

COLORES = {
    "ok": "#1D9E75",
    "warn": "#BA7517",
    "block": "#A32D2D",
    "info": "#5F5E5A",
}

ETIQUETA_TIPO = {
    "registry": "Directorio",
    "identity": "Identidad",
    "message": "Mensaje",
    "content": "Capa de contenido",
    "network": "Capa de red",
    "kernel": "Capa de kernel",
    "inference": "Inferencia",
    "router": "Router",
    "cost": "Costos",
    "decision": "Decision",
}

st.markdown("""
<style>
  .ev { border-left: 4px solid #ccc; padding: 10px 16px; margin-bottom: 10px;
        background: rgba(128,128,128,0.06); }
  .ev-tipo { font-size: 12px; letter-spacing: .04em; opacity: .75; }
  .ev-titulo { font-size: 19px; font-weight: 500; margin-top: 2px; }
  .ev-capa { font-size: 13px; opacity: .7; margin-top: 2px; }
  .kv { font-size: 15px; margin-top: 8px; }
  .kv b { font-weight: 500; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

def init_state():
    st.session_state.setdefault("a_events", [])
    st.session_state.setdefault("a_idx", 0)
    st.session_state.setdefault("b_events", [])
    st.session_state.setdefault("b_idx", 0)
    st.session_state.setdefault("kv", KVCache())
    st.session_state.setdefault("ledger", CostLedger())


init_state()


def render_event(ev):
    color = COLORES.get(ev.verdict, COLORES["info"])
    capa = f'<div class="ev-capa">{ev.layer}</div>' if ev.layer else ""
    filas = "".join(
        f'<div class="kv"><b>{k.replace("_", " ")}:</b> {v}</div>'
        for k, v in ev.detail.items()
    )
    st.markdown(
        f'<div class="ev" style="border-left-color:{color}">'
        f'<div class="ev-tipo">{ETIQUETA_TIPO.get(ev.kind, ev.kind)} · paso {ev.seq}</div>'
        f'<div class="ev-titulo">{ev.title}</div>{capa}{filas}</div>',
        unsafe_allow_html=True,
    )


def stepper(clave_events, clave_idx, etiqueta):
    eventos = st.session_state[clave_events]
    idx = st.session_state[clave_idx]
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("Siguiente paso", key=f"next_{clave_idx}", disabled=idx >= len(eventos)):
        st.session_state[clave_idx] = min(idx + 1, len(eventos))
        st.rerun()
    if c2.button("Mostrar todo", key=f"all_{clave_idx}"):
        st.session_state[clave_idx] = len(eventos)
        st.rerun()
    c3.caption(f"{idx} de {len(eventos)} pasos de {etiqueta}")
    for ev in eventos[:idx]:
        render_event(ev)


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Control del demo")
    modo = "SIM · local" if config.MODE == "SIM" else "LIVE · servidor"
    st.success(f"Modo: {modo}") if config.MODE == "SIM" else st.info(f"Modo: {modo}")
    st.caption(f"Motor de inferencia: {config.LLM_BACKEND}")

    st.divider()
    opciones = {e.etiqueta: e.id for e in scenarios.ESCENARIOS}
    etiqueta_sel = st.radio("Expediente", list(opciones.keys()))
    escenario_id = opciones[etiqueta_sel]
    st.caption(scenarios.get(escenario_id).descripcion)

    st.divider()
    if st.button("Reiniciar todo"):
        for k in ["a_events", "a_idx", "b_events", "b_idx"]:
            st.session_state.pop(k, None)
        st.session_state["kv"] = KVCache()
        st.session_state["ledger"] = CostLedger()
        init_state()
        st.rerun()

st.title("Multi-agentes bajo control")
st.caption("Conectarlos, asegurarlos y escalarlos sin sorpresas · Cisco Connect")

tab_malla, tab_a, tab_b, tab_guion = st.tabs(
    ["Malla de agentes", "Beat A · seguridad", "Beat B · inferencia y costos", "Guion"]
)


# ---------------------------------------------------------------------------
# Pestania 1: la malla
# ---------------------------------------------------------------------------

with tab_malla:
    st.subheader("Quien es quien en el enjambre")
    st.write(
        "Cada agente publica una tarjeta con lo que sabe hacer y con su identidad "
        "criptografica. Otro agente lo encuentra por capacidad, no por direccion IP."
    )
    agentes = build_agents()
    cols = st.columns(2)
    for i, a in enumerate(agentes.values()):
        with cols[i % 2]:
            st.markdown(f"**{a.display_name}**")
            st.caption(a.description)
            st.code(a.identity.spiffe_id, language=None)
            st.write("Capacidades: " + ", ".join(a.skills))
            st.write(f"Corre en: {a.runs_on}")
            st.divider()


# ---------------------------------------------------------------------------
# Pestania 2: Beat A
# ---------------------------------------------------------------------------

with tab_a:
    st.subheader("Tres capas, porque la primera va a fallar")
    st.caption(config.CONTENT_LAYER_DISCLAIMER)

    if st.button("Preparar la corrida", type="primary", key="prep_a"):
        eventos, _ = run_beat_a(escenario_id)
        st.session_state["a_events"] = eventos
        st.session_state["a_idx"] = 0
        st.rerun()

    if st.session_state["a_events"]:
        stepper("a_events", "a_idx", "seguridad")
    else:
        st.info("Elige un expediente en la barra lateral y presiona Preparar la corrida.")


# ---------------------------------------------------------------------------
# Pestania 3: Beat B
# ---------------------------------------------------------------------------

with tab_b:
    st.subheader("Jerarquia de cache, enrutamiento y costo")
    kv = st.session_state["kv"]
    ledger = st.session_state["ledger"]

    m1, m2, m3 = st.columns(3)
    estado = kv.estado()
    m1.metric("VRAM usada por la cache",
              f"{estado['vram_usada_gib']} GiB",
              f"de {estado['vram_presupuesto_gib']} GiB")
    m2.metric("Costo de la corrida", f"US$ {ledger.total:.4f}")
    m3.metric("Ahorro contra todo en la nube", f"{ledger.ahorro_pct():.0f}%")

    if st.button("Preparar la corrida", type="primary", key="prep_b"):
        eventos, _ = run_beat_b(escenario_id, kv, ledger)
        st.session_state["b_events"] = eventos
        st.session_state["b_idx"] = 0
        st.rerun()

    if st.session_state["b_events"]:
        stepper("b_events", "b_idx", "inferencia")
        if ledger.filas:
            st.divider()
            st.write("Desglose de tokens y costo")
            st.dataframe(ledger.filas, use_container_width=True)
    else:
        st.info("Presiona Preparar la corrida. Corre el mismo expediente dos veces "
                "para ver el efecto de la cache.")


# ---------------------------------------------------------------------------
# Pestania 4: el guion
# ---------------------------------------------------------------------------

with tab_guion:
    st.subheader("Que decir en cada paso")
    st.markdown("""
**Beat A, al abrir** — "Vamos a mandar un expediente de credito de 50 paginas.
Trae escondida una instruccion maliciosa. Quiero que vean cuantas cosas tienen
que salir bien para que no pase nada."

**Al bloquear la inyeccion directa** — "Esa era la version de libro. Ahora
veamos una escrita con mas cuidado."

**Cuando la ofuscada pasa el guardrail** — "Aqui es donde se acaba la defensa de
una sola capa. El clasificador no vio nada raro, porque esta redactada como un
procedimiento interno."

**Al bloquear la salida en la red** — "El agente ya decidio obedecer. Pero solo
tiene permiso de hablar con dos servicios del cluster. La politica se escribe
contra su identidad, no contra su IP."

**En el SIGKILL** — quedate callado dos segundos. Deja que lo vean.

**Cierre del Beat A** — "Tu clasificador de prompts va a fallar algun dia. Ese
dia la arquitectura tiene que aguantar de todos modos."

---

**Beat B, al abrir** — "Ahora el otro tipo de sorpresa: la factura."

**En la primera lectura** — "40,000 tokens generan 5 GiB de estado. En una GPU
compacta eso es muchisimo."

**En el desalojo** — "El contexto no se pierde. Baja a disco local. Recuperarlo
de ahi cuesta segundos; recalcularlo cuesta mucho mas."

**En el router** — la frase que amarra la sesion: "Esta decision resuelve dos
problemas a la vez. Se queda local porque trae datos personales, y porque es una
tarea rutinaria que no tiene por que pagarse por token."
    """)
