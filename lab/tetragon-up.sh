#!/usr/bin/env bash
#
# Instala Tetragon en el cluster: el control de KERNEL del Demo 2.
#
# Que es: un DaemonSet (un pod por nodo) que usa eBPF para observar procesos,
# archivos y red desde el kernel. Con una TracingPolicy puede ademas ACTUAR:
# matar con SIGKILL un proceso que intenta algo prohibido, antes de que lo haga.
# Eso es lo que el Demo 2 muestra cuando el agente comprometido intenta ejecutar
# un binario. Necesita BTF en el kernel (lo verifica bootstrap.sh).
#
# Version fija: el dia del evento debe correr lo mismo que se ensayo.
# Idempotente: si ya esta instalado con esta version, no hace nada.
#
# Uso:  ./tetragon-up.sh

set -euo pipefail

TETRAGON_VER=1.7.1
NS=kube-system

log() { echo ""; echo "=== $1"; }

command -v helm >/dev/null || { echo "Falta helm: corre ./bootstrap.sh"; exit 1; }

log "Repositorio de charts de Cilium"
helm repo add cilium https://helm.cilium.io >/dev/null 2>&1 || true
helm repo update cilium

actual=$(helm list -n "$NS" -f '^tetragon$' -o json | jq -r '.[0].app_version // empty')
if [ "$actual" = "$TETRAGON_VER" ]; then
  log "Tetragon $TETRAGON_VER ya estaba instalado"
else
  log "Instalando Tetragon $TETRAGON_VER"
  # export.mode="": sin el contenedor que copia eventos a stdout (otra imagen
  #   mas, hubble-export-stdout). Los eventos se leen por gRPC con
  #   `tetra getevents`, que es lo que usa el observador.
  # Recursos modestos: la VM tiene 10 GB y Ollama usa ~6.
  helm upgrade --install tetragon cilium/tetragon \
    --version "$TETRAGON_VER" \
    --namespace "$NS" \
    --set export.mode="" \
    --set tetragon.resources.requests.memory=128Mi \
    --set tetragon.resources.limits.memory=512Mi \
    --wait --timeout 10m
fi

log "Esperando a que el DaemonSet este listo"
kubectl -n "$NS" rollout status ds/tetragon --timeout=300s

log "Tetragon listo"
kubectl -n "$NS" get pods -l app.kubernetes.io/name=tetragon -o wide
echo ""
echo "Ver eventos del kernel en vivo:"
echo "  kubectl -n $NS exec ds/tetragon -c tetragon -- tetra getevents -o compact"
