#!/usr/bin/env bash
#
# Crea el cluster de Kubernetes con Cilium como red.
#
# Idempotente: si el cluster ya existe, no lo vuelve a crear.
# Para borrarlo y empezar de cero:  kind delete cluster --name agentes

set -euo pipefail

CLUSTER=agentes
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo ""; echo "=== $1"; }

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  log "El cluster '$CLUSTER' ya existe"
else
  log "Creando el cluster '$CLUSTER'"
  # Ojo con la configuracion: creamos el cluster SIN red.
  # Eso es a proposito. Cilium va a ser la red, y necesita ser el unico.
  kind create cluster --name "$CLUSTER" --config "$DIR/kind-cluster.yaml"
fi

log "Instalando Cilium como red del cluster"
# kubeProxyReplacement=true: Cilium reemplaza a kube-proxy usando eBPF.
# hubble: es el sistema de observabilidad. Sin esto no puedes VER el trafico,
#         y ver el trafico es la mitad de la demo.
if ! cilium status >/dev/null 2>&1; then
  cilium install \
    --set kubeProxyReplacement=true \
    --set hubble.enabled=true \
    --set hubble.relay.enabled=true \
    --set hubble.ui.enabled=true
else
  echo "Cilium ya estaba instalado"
fi

log "Esperando a que Cilium este listo (puede tardar unos minutos)"
cilium status --wait

log "Cluster listo"
kubectl get nodes
echo ""
echo "Siguiente paso:  kubectl apply -f $DIR/01-dos-agentes.yaml"
