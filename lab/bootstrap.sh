#!/usr/bin/env bash
#
# Instala el lab completo sobre un Ubuntu 24.04 limpio.
#
# Este script es EL ARTEFACTO PORTABLE del proyecto. La maquina virtual es
# desechable: si se rompe, la borras y corres esto de nuevo. Y cuando pases
# a dCloud, corres exactamente este mismo archivo alla.
#
# Uso:
#   chmod +x bootstrap.sh
#   ./bootstrap.sh
#
# Es idempotente: puedes correrlo varias veces sin romper nada.

set -euo pipefail

log() { echo ""; echo "=== $1"; }

# ---------------------------------------------------------------------------
# 0. Verificacion previa: BTF
# ---------------------------------------------------------------------------
# BTF es informacion de depuracion que el kernel expone sobre si mismo.
# Tetragon la necesita para saber donde engancharse. Sin esto, la Fase 2
# no funciona, y es mejor enterarse ahora que la semana del evento.
log "Verificando soporte de BTF en el kernel"
if [ -f /sys/kernel/btf/vmlinux ]; then
  echo "BTF disponible. Tetragon va a poder correr."
else
  echo "ADVERTENCIA: este kernel no expone BTF en /sys/kernel/btf/vmlinux"
  echo "El lab de red va a funcionar, pero Tetragon no."
  echo "Si estas en WSL2, cambia a una VM de Ubuntu real."
fi
echo "Kernel: $(uname -r)"

# ---------------------------------------------------------------------------
# 0b. DNS de respaldo (solo si hace falta)
# ---------------------------------------------------------------------------
# En Windows, Multipass usa el "Default Switch" de Hyper-V, y su servidor DNS
# a veces deja de contestar aunque la VM sí tenga salida a internet por IP.
# Sin DNS no funciona apt, ni la descarga de imágenes, ni la de modelos.
#
# Por eso: si el DNS actual resuelve, NO tocamos nada (en dCloud puede haber
# un DNS interno que hay que respetar). Solo si falla, agregamos servidores
# públicos como respaldo a systemd-resolved, el servicio que resuelve nombres
# en Ubuntu. "Domains=~." le dice que los use para todos los dominios.
#
# Notas de lo que se aprendió probándolo en la VM:
# - Se verifica con "ahostsv4" (solo IPv4). Las consultas IPv6 siguen
#   colgándose contra el DNS del switch, pero apt, Docker y Ollama funcionan.
# - Justo después de reiniciar systemd-resolved la primera consulta puede
#   tardar; por eso se reintenta antes de declarar error.
# - No hace falta reiniciar Docker: los nodos de kind reenvían sus consultas
#   al resolvedor de la VM (127.0.0.53), así que heredan el respaldo.
dns_ok() {
  for _ in 1 2 3 4 5; do
    timeout 5 getent ahostsv4 github.com >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

log "Verificando DNS"
if dns_ok; then
  echo "El DNS resuelve. No se cambia nada."
else
  echo "El DNS no resuelve. Configurando respaldo 1.1.1.1 / 8.8.8.8"
  sudo mkdir -p /etc/systemd/resolved.conf.d
  printf '[Resolve]\nDNS=1.1.1.1 8.8.8.8\nFallbackDNS=1.0.0.1 8.8.4.4\nDomains=~.\n' \
    | sudo tee /etc/systemd/resolved.conf.d/10-respaldo-lab.conf >/dev/null
  sudo systemctl restart systemd-resolved
  if dns_ok; then
    echo "DNS de respaldo funcionando."
  else
    echo "ERROR: ni con DNS de respaldo se resuelven nombres. Revisa la red de la VM."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 1. Paquetes base
# ---------------------------------------------------------------------------
log "Instalando paquetes base"
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl gnupg jq git

# ---------------------------------------------------------------------------
# 2. Docker
# ---------------------------------------------------------------------------
# kind (el Kubernetes de mentiras que vamos a usar) corre cada nodo del
# cluster como un contenedor de Docker. Por eso Docker va primero.
if ! command -v docker >/dev/null 2>&1; then
  log "Instalando Docker"
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io
  sudo usermod -aG docker "$USER"
  echo "Docker instalado. Vas a necesitar cerrar y abrir la sesion para usarlo sin sudo."
else
  log "Docker ya estaba instalado"
fi

# ---------------------------------------------------------------------------
# 3. kubectl
# ---------------------------------------------------------------------------
# kubectl es el control remoto de Kubernetes. Todo lo que hagas contra el
# cluster pasa por aqui.
if ! command -v kubectl >/dev/null 2>&1; then
  log "Instalando kubectl"
  KVER="$(curl -L -s https://dl.k8s.io/release/stable.txt)"
  curl -sLO "https://dl.k8s.io/release/${KVER}/bin/linux/amd64/kubectl"
  sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
  rm -f kubectl
else
  log "kubectl ya estaba instalado"
fi

# ---------------------------------------------------------------------------
# 4. kind
# ---------------------------------------------------------------------------
# kind = Kubernetes IN Docker. Levanta un cluster completo en tu maquina
# usando contenedores como si fueran servidores.
if ! command -v kind >/dev/null 2>&1; then
  log "Instalando kind"
  curl -sLo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
  chmod +x ./kind
  sudo mv ./kind /usr/local/bin/kind
else
  log "kind ya estaba instalado"
fi

# ---------------------------------------------------------------------------
# 5. CLI de Cilium
# ---------------------------------------------------------------------------
if ! command -v cilium >/dev/null 2>&1; then
  log "Instalando la CLI de Cilium"
  CVER="$(curl -s https://raw.githubusercontent.com/cilium/cilium-cli/main/stable.txt)"
  curl -sL --fail --remote-name-all \
    "https://github.com/cilium/cilium-cli/releases/download/${CVER}/cilium-linux-amd64.tar.gz"
  sudo tar xzf cilium-linux-amd64.tar.gz -C /usr/local/bin
  rm -f cilium-linux-amd64.tar.gz
else
  log "La CLI de Cilium ya estaba instalada"
fi

# ---------------------------------------------------------------------------
# 6. CLI de Hubble
# ---------------------------------------------------------------------------
# Ojo: 'cilium' y 'hubble' son DOS PROGRAMAS DISTINTOS.
#   cilium  -> instala y administra la red del cluster
#   hubble  -> consulta el trafico que Cilium esta viendo
# Instalar uno no instala el otro. Y hubble es el que te deja VER los bloqueos,
# que es la mitad de la demo.
if ! command -v hubble >/dev/null 2>&1; then
  log "Instalando la CLI de Hubble"
  HVER="$(curl -s https://raw.githubusercontent.com/cilium/hubble/master/stable.txt)"
  curl -sL --fail --remote-name-all \
    "https://github.com/cilium/hubble/releases/download/${HVER}/hubble-linux-amd64.tar.gz"
  sudo tar xzf hubble-linux-amd64.tar.gz -C /usr/local/bin
  rm -f hubble-linux-amd64.tar.gz
else
  log "La CLI de Hubble ya estaba instalada"
fi

log "Listo"
echo ""
echo "Herramientas instaladas:"
for cmd in docker kubectl kind cilium hubble; do
  if command -v "$cmd" >/dev/null 2>&1; then echo "  ok   $cmd"; else echo "  FALTA $cmd"; fi
done
echo ""
echo "Siguiente paso:  ./cluster-up.sh"
echo "Si Docker se acaba de instalar, primero cierra sesion y vuelve a entrar."
