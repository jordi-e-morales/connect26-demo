"""
El nucleo del demo: identidad, directorio de agentes, bus de mensajes y eventos.

Tres conceptos, y conviene tenerlos claros porque son los que vas a explicar
en la sesion:

1. IDENTIDAD (estilo SPIFFE)
   Cada agente tiene un identificador criptografico, no una API key.
   Se ve asi:  spiffe://cisco-connect.demo/ns/agentes/sa/extractor
   En produccion lo emite SPIRE como un certificado x509 rotativo (un SVID).

2. DIRECTORIO (estilo AGNTCY / OASF)
   Cada agente publica una "Agent Card": que sabe hacer, que recibe, que
   devuelve. Otro agente lo BUSCA POR CAPACIDAD, no por IP ni por URL fija.

3. BUS DE MENSAJES (estilo SLIM)
   Cada mensaje entre agentes viaja en un sobre con emisor, receptor, esquema
   del payload, si va cifrado y si la identidad fue verificada.

Todo lo que pasa se registra como un EVENTO en una linea de tiempo. La UI
simplemente dibuja esa linea de tiempo. Esa es la clave del demo didactico:
no mostramos magia, mostramos la bitacora.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

TRUST_DOMAIN = "cisco-connect.demo"


# ---------------------------------------------------------------------------
# Identidad
# ---------------------------------------------------------------------------

def spiffe_id(namespace: str, service: str) -> str:
    """Construye un identificador de carga de trabajo estilo SPIFFE."""
    return f"spiffe://{TRUST_DOMAIN}/ns/{namespace}/sa/{service}"


@dataclass
class Identity:
    """Representa el SVID (el certificado) de un agente."""
    spiffe_id: str
    serial: str
    issued_at: str
    expires_in_s: int = 3600

    @staticmethod
    def issue(sid: str) -> "Identity":
        return Identity(
            spiffe_id=sid,
            serial=uuid.uuid4().hex[:16].upper(),
            issued_at=datetime.now().strftime("%H:%M:%S"),
        )


# ---------------------------------------------------------------------------
# Agent Card (estilo OASF)
# ---------------------------------------------------------------------------

@dataclass
class AgentCard:
    name: str
    display_name: str
    description: str
    skills: List[str]
    endpoint: str
    runs_on: str              # donde corre: "UCS local (GPU)" o "Frontier"
    identity: Identity
    input_schema: str
    output_schema: str

    def to_record(self) -> Dict[str, Any]:
        """Como se veria el registro publicado en el directorio."""
        return {
            "name": self.name,
            "skills": self.skills,
            "endpoint": self.endpoint,
            "identity": self.identity.spiffe_id,
            "schemas": {"input": self.input_schema, "output": self.output_schema},
            "runs_on": self.runs_on,
        }


# ---------------------------------------------------------------------------
# Directorio de agentes
# ---------------------------------------------------------------------------

class Registry:
    """Directorio donde los agentes se anuncian y se descubren por capacidad."""

    def __init__(self, bus: "Bus"):
        self.bus = bus
        self.cards: Dict[str, AgentCard] = {}

    def announce(self, card: AgentCard) -> None:
        self.cards[card.name] = card
        self.bus.emit(
            kind="registry",
            actor=card.name,
            title=f"{card.display_name} se anuncia en el directorio",
            detail={
                "operacion": "announce",
                "capacidades": card.skills,
                "identidad": card.identity.spiffe_id,
            },
        )

    def discover(self, skill: str, requester: str) -> Optional[AgentCard]:
        """Busca un agente que tenga una capacidad concreta."""
        found = [c for c in self.cards.values() if skill in c.skills]
        self.bus.emit(
            kind="registry",
            actor=requester,
            title=f"Busca en el directorio un agente con la capacidad '{skill}'",
            detail={
                "operacion": "discover",
                "capacidad_buscada": skill,
                "resultados": [c.name for c in found] or "ninguno",
            },
        )
        return found[0] if found else None

    def resolve(self, card: AgentCard, requester: str) -> bool:
        """Verifica criptograficamente la identidad antes de hablar."""
        self.bus.emit(
            kind="identity",
            actor=requester,
            title=f"Verifica el certificado de {card.display_name}",
            detail={
                "operacion": "resolve",
                "identidad_presentada": card.identity.spiffe_id,
                "serie_certificado": card.identity.serial,
                "emitido": card.identity.issued_at,
                "verificacion_mutua": "correcta",
            },
            verdict="ok",
        )
        return True


# ---------------------------------------------------------------------------
# Eventos y bus
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """Una linea en la bitacora. Es lo unico que la UI necesita dibujar."""
    seq: int
    kind: str                       # registry | identity | message | content |
                                    # network | kernel | inference | router | cost | decision
    actor: str
    title: str
    detail: Dict[str, Any] = field(default_factory=dict)
    verdict: str = "info"           # info | ok | warn | block
    layer: Optional[str] = None     # nombre de la capa de seguridad, si aplica


@dataclass
class Envelope:
    """Sobre de mensaje entre agentes, estilo SLIM."""
    message_id: str
    session_id: str
    from_id: str
    to_id: str
    payload_schema: str
    payload_bytes: int
    encrypted: bool
    identity_verified: bool


class Bus:
    """Recolecta todos los eventos y todos los sobres de la corrida."""

    def __init__(self):
        self.events: List[Event] = []
        self.envelopes: List[Envelope] = []
        self.session_id = "sess-" + uuid.uuid4().hex[:8]
        self._seq = 0

    def emit(self, kind: str, actor: str, title: str,
             detail: Optional[Dict[str, Any]] = None,
             verdict: str = "info", layer: Optional[str] = None) -> Event:
        self._seq += 1
        ev = Event(
            seq=self._seq,
            kind=kind,
            actor=actor,
            title=title,
            detail=detail or {},
            verdict=verdict,
            layer=layer,
        )
        self.events.append(ev)
        return ev

    def send(self, sender: AgentCard, receiver: AgentCard, schema: str,
             payload_bytes: int, verified: bool = True) -> Envelope:
        env = Envelope(
            message_id="msg-" + uuid.uuid4().hex[:8],
            session_id=self.session_id,
            from_id=sender.identity.spiffe_id,
            to_id=receiver.identity.spiffe_id,
            payload_schema=schema,
            payload_bytes=payload_bytes,
            encrypted=True,
            identity_verified=verified,
        )
        self.envelopes.append(env)
        self.emit(
            kind="message",
            actor=sender.name,
            title=f"{sender.display_name} envia un mensaje a {receiver.display_name}",
            detail={
                "id_mensaje": env.message_id,
                "esquema": schema,
                "tamano_bytes": payload_bytes,
                "cifrado": "si",
                "identidad_verificada": "si" if verified else "NO",
            },
        )
        return env
