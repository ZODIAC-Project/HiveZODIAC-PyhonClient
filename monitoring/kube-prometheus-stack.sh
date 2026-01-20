#!/usr/bin/env bash
set -euo pipefail 

LATEST_TESTED_VERSION=80.00.0

CHART=prometheus-community/kube-prometheus-stack
VERSION=""
OUT=monitoring/charts/kube-prometheus-stack.yaml

KEPLER_CHART=kepler/kepler
KEPLER_VALUES=monitoring/kepler/values.yaml
KEPLER_SERVICEMONITOR=monitoring/kepler/servicemonitor.yaml
KEPLER_RELEASE=kepler

SKIP_DEPLOY=0
ONLY_APPLY_LOCAL=0
WITH_KEPLER=0
WITH_ISTIO=0
WITH_KIALI=0
WITH_MESH=0

# arg parsing: --skip-deploy, --only-apply-local, otherwise first non-flag is version
for arg in "$@"; do
  case "$arg" in
    --skip-deploy)
      SKIP_DEPLOY=1
      ;;
    --only-apply-local)
      ONLY_APPLY_LOCAL=1
      ;;
    --help|-h)
        printf '%s\n' "Usage: $0 [--skip-deploy] [--only-apply-local] [--with-kepler] [--with-istio] [--with-kiali] [--with-mesh] [<chart-version>]"
        printf '%s\n' "  --skip-deploy        Render chart but skip helm upgrade/install"
        printf '%s\n' "  --only-apply-local   Skip rendering/helm; only apply local YAMLs in monitoring/"
        printf '%s\n' "  --with-kepler        Also install Kepler via Helm after Prometheus is ready"
        printf '%s\n' "  --with-istio         Install Istio (base, istiod, ingress) and apply ServiceMonitors"
        printf '%s\n' "  --with-kiali         Install Kiali server configured to use Prometheus"
        printf '%s\n' "  --with-mesh          Convenience flag: same as --with-istio --with-kiali"
      exit 0
      ;;
    --with-kepler)
      WITH_KEPLER=1
      ;;
    --with-istio)
      WITH_ISTIO=1
      ;;
    --with-kiali)
      WITH_KIALI=1
      ;;
    --with-mesh)
      WITH_ISTIO=1
      WITH_KIALI=1
      ;;
    *)
      if [[ -z "${VERSION// }" ]]; then
        VERSION="$arg"
      fi
      ;;
  esac
done

function latest_version_via_helm() {
  helm repo update >/dev/null 2>&1 || true
  helm search repo prometheus-community/kube-prometheus-stack --versions | sed -n '2p' | awk '{print $2}'
}

function wait_for_service() {
  local ns="$1" svc="$2" timeout=${3:-300}
  local start=$(date +%s)
  while true; do
    if kubectl -n "$ns" get svc "$svc" >/dev/null 2>&1; then
      return 0
    fi
    now=$(date +%s)
    if (( now - start > timeout )); then
      return 1
    fi
    sleep 2
  done
}

printf '%s\n' "Rendering kube-prometheus-stack (chart ${CHART})"

LATEST_AVAILABLE_VERSION=$(latest_version_via_helm)

if [[ -z "${VERSION// }" ]]; then
  VERSION=${LATEST_AVAILABLE_VERSION}
  printf '%s\n' "No version provided; using latest available: ${VERSION}"
fi

if [[ -z "${VERSION}" ]]; then
  printf '%s\n' "❗ Failed to determine a chart version. Please provide one as argument." >&2
  printf '%s\n' "The latest tedted version is ${LATEST_TESTED_VERSION}." >&2
  exit 2
fi

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo add kepler https://sustainable-computing-io.github.io/kepler-helm-chart || true
helm repo add istio https://istio-release.storage.googleapis.com/charts || true
helm repo add kiali https://kiali.org/helm-charts || true
helm repo update

printf '%s\n' "Rendering chart version ${VERSION} to ${OUT}"
helm template monitoring ${CHART} --version "${VERSION}" -f monitoring/charts/values.yaml > "${OUT}"
printf '%s\n' "Rendered chart to ${OUT}"

if [[ ${ONLY_APPLY_LOCAL} -eq 1 ]]; then
  printf '%s\n' "--only-apply-local set; skipping render/helm and applying local manifests only."
  # When only applying local manifests, also apply the Kepler ServiceMonitor if present
  if [[ -f "${KEPLER_SERVICEMONITOR}" ]]; then
    printf '%s\n' "Applying local Kepler ServiceMonitor manifest (only-apply-local mode)"
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n monitoring apply -f "${KEPLER_SERVICEMONITOR}" || true
  fi
  # Apply Istio and Kiali ServiceMonitors if present
  if [[ -f monitoring/istio/servicemonitors.yaml ]]; then
    printf '%s\n' "Applying local Istio ServiceMonitors (only-apply-local mode)"
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n monitoring apply -f monitoring/istio/servicemonitors.yaml || true
  fi
  if [[ -f monitoring/kiali/servicemonitor.yaml ]]; then
    printf '%s\n' "Applying local Kiali ServiceMonitor (only-apply-local mode)"
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n monitoring apply -f monitoring/kiali/servicemonitor.yaml || true
  fi
else
  if [[ ${SKIP_DEPLOY} -eq 1 ]]; then
    printf '%s\n' "--skip-deploy set; rendering only (no helm upgrade/install)."
  else
    printf '%s\n' "Installing/upgrading kube-prometheus-stack into namespace 'monitoring' (helm upgrade --install)"
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    helm upgrade --install monitoring ${CHART} --version "${VERSION}" -n monitoring -f monitoring/charts/values.yaml
    printf '%s\n' "Helm upgrade/install command finished. Use 'kubectl get pods -n monitoring' to watch pod status."
  fi
fi

  # If we performed the helm install/upgrade above, optionally install Kepler now.
  # Only try to install Kepler when not running in --skip-deploy or --only-apply-local modes.
  if [[ ${WITH_KEPLER} -eq 1 && ${ONLY_APPLY_LOCAL} -eq 0 && ${SKIP_DEPLOY} -eq 0 ]]; then
    printf '%s\n' "⏳ Waiting for Prometheus service to appear before installing Kepler..."
    PROM_SVC_NAME="monitoring-kube-prometheus-prometheus"
    if wait_for_service monitoring "${PROM_SVC_NAME}" 300; then
      printf '%s\n' "🪐 Prometheus service present; installing/upgrading Kepler (${KEPLER_RELEASE})"
      helm upgrade --install "${KEPLER_RELEASE}" "${KEPLER_CHART}" -n monitoring -f "${KEPLER_VALUES}" || {
        printf '%s\n' "❗ Kepler helm install failed; you can retry manually."
      }
      # Apply ServiceMonitor manifest as a fallback or customization
      if [[ -f "${KEPLER_SERVICEMONITOR}" ]]; then
        printf '%s\n' "Applying Kepler ServiceMonitor manifest"
        kubectl -n monitoring apply -f "${KEPLER_SERVICEMONITOR}" || true
      fi
    else
      printf '%s\n' "❗Timed out waiting for Prometheus service; skipping automatic Kepler install."
    fi
  else
    printf '%s\n' "Skipping Kepler automatic install (WITH_KEPLER=${WITH_KEPLER}, ONLY_APPLY_LOCAL=${ONLY_APPLY_LOCAL}, SKIP_DEPLOY=${SKIP_DEPLOY})."
  fi

# Apply local YAML manifests in monitoring/ (excluding charts dir and this script)
printf '%s\n' "Applying local manifests in monitoring/"
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
shopt -s nullglob
for f in monitoring/*.yaml; do
  # skip charts output and this script's possible rendered file
  case "${f}" in
    monitoring/charts/*|monitoring/render-*)
      continue
      ;;
  esac
  printf '%s\n' "Applying ${f}"
  kubectl apply -f "${f}"
done
shopt -u nullglob

printf '%s\n' "Applied local manifests. Use 'kubectl get pods -n monitoring' to check status."

printf '%s\n' "✅ kube-prometheus-stack script completed."

printf '%s\n' "⬆ Scroll up for the steps to access Grafana ⬆"

# --- Helper functions to install Istio and Kiali ---
ISTIO_VALUES=monitoring/istio/values.yaml
ISTIO_SERVICEMONITORS=monitoring/istio/servicemonitors.yaml
KIALI_VALUES=monitoring/kiali/values.yaml
KIALI_SERVICEMONITOR=monitoring/kiali/servicemonitor.yaml

function install_istio() {
  printf '%s\n' "Checking existing Istio control-plane (istiod) health. If healthy, reuse it; otherwise report and continue."
  kubectl create namespace istio-system --dry-run=client -o yaml | kubectl apply -f -

  # If istiod deployment exists, check readiness
  if kubectl -n istio-system get deploy istiod >/dev/null 2>&1; then
    ready=$(kubectl -n istio-system get deploy istiod -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
    desired=$(kubectl -n istio-system get deploy istiod -o jsonpath='{.status.replicas}' 2>/dev/null || echo 0)
    printf '%s\n' "istiod deployment detected: ready=${ready:-0}, desired=${desired:-0}"
    # consider healthy when at least one ready replica and ready == desired (simple heuristic)
    if [[ -n "${ready}" && -n "${desired}" && ${ready:-0} -ge 1 && ${ready:-0} -eq ${desired:-0} ]]; then
      printf '%s\n' "Istiod is present and appears healthy; reusing existing control-plane."
      if [[ -f "${ISTIO_SERVICEMONITORS}" ]]; then
        kubectl -n monitoring apply -f "${ISTIO_SERVICEMONITORS}" || true
      fi
      return 0
    else
      printf '%s\n' "Istiod is present but not healthy (ready=${ready:-0}, desired=${desired:-0}). Will NOT force reinstall; please inspect cluster. Continuing with other installs."
      kubectl -n istio-system get pods -o wide || true
      if [[ -f "${ISTIO_SERVICEMONITORS}" ]]; then
        kubectl -n monitoring apply -f "${ISTIO_SERVICEMONITORS}" || true
      fi
      return 0
    fi
  else
    printf '%s\n' "Istiod deployment not found in namespace 'istio-system'. Installing Istio via Helm."
    # Install Istio base chart
    helm upgrade --install istio-base istio/base -n istio-system --wait --atomic || {
      printf '%s\n' "❗ Failed to install istio-base via Helm."
      return 1
    }
    # Install Istiod chart
    helm upgrade --install istiod istio/istiod -n istio-system -f "${ISTIO_VALUES}" --wait --atomic || {
      printf '%s\n' "❗ Failed to install istiod via Helm."
      return 1
    }
    # Install Istio ingress gateway
    helm upgrade --install istio-ingress istio/gateway -n istio-system --wait --atomic || {
      printf '%s\n' "❗ Failed to install istio-ingress via Helm."
      return 1
    }
    printf '%s\n' "Istio installation via Helm completed."
    # Apply ServiceMonitors so Prometheus scrapes Istio components
    if [[ -f "${ISTIO_SERVICEMONITORS}" ]]; then
      kubectl -n monitoring apply -f "${ISTIO_SERVICEMONITORS}" || true
    fi
  fi  
}

function detect_monitoring_services() {
  # Defaults (common names used by kube-prometheus-stack)
  PROM_SVC="monitoring-kube-prometheus-prometheus"
  GRAF_SVC="monitoring-grafana"

  # Try to detect Prometheus service by label (some charts use different names)
  found_prom=$(kubectl -n monitoring get svc -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "${found_prom}" ]]; then
    PROM_SVC="${found_prom}"
  else
    # fallback: find service that exposes port 9090
    found_prom=$(kubectl -n monitoring get svc --no-headers -o custom-columns=NAME:.metadata.name,PORTS:.spec.ports 2>/dev/null | grep 9090 | awk '{print $1}' | head -n1 || true)
    if [[ -n "${found_prom}" ]]; then
      PROM_SVC="${found_prom}"
    fi
  fi

  # Detect Grafana service by label
  found_graf=$(kubectl -n monitoring get svc -l app.kubernetes.io/name=grafana -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "${found_graf}" ]]; then
    GRAF_SVC="${found_graf}"
  else
    # fallback: find service exposing port 3000 or 80
    found_graf=$(kubectl -n monitoring get svc --no-headers -o custom-columns=NAME:.metadata.name,PORTS:.spec.ports 2>/dev/null | grep -E "3000|:80" | awk '{print $1}' | head -n1 || true)
    if [[ -n "${found_graf}" ]]; then
      GRAF_SVC="${found_graf}"
    fi
  fi

  PROM_URL="http://${PROM_SVC}.monitoring.svc.cluster.local:9090"
  GRAF_URL="http://${GRAF_SVC}.monitoring.svc.cluster.local:80"
  printf '%s\n' "Detected monitoring endpoints: PROM_URL=${PROM_URL}, GRAF_URL=${GRAF_URL}"
}

function install_kiali() {
  printf '%s\n' "Installing or configuring Kiali server"
  # Ensure Prometheus service exists before Kiali (so Kiali can connect)
  if wait_for_service monitoring monitoring-kube-prometheus-prometheus 600; then
    :
  else
    printf '%s\n' "Warning: Prometheus service not ready; Kiali may start without metrics."
  fi

  # Detect monitoring endpoints to configure Kiali properly
  detect_monitoring_services

  # For testing clusters we prefer a clean Kiali install: delete any existing Kiali resources and reinstall
  if kubectl -n istio-system get deploy kiali >/dev/null 2>&1 || kubectl -n istio-system get svc kiali >/dev/null 2>&1 || kubectl -n istio-system get sa kiali >/dev/null 2>&1; then
    printf '%s\n' "Found existing Kiali resources; deleting them for a fresh Helm install."
    kubectl -n istio-system delete deploy kiali --ignore-not-found || true
    kubectl -n istio-system delete svc kiali --ignore-not-found || true
    kubectl -n istio-system delete sa kiali --ignore-not-found || true
    kubectl -n istio-system delete secret kiali --ignore-not-found || true
    sleep 2
  fi

  printf '%s\n' "Installing kiali-server via Helm with external_services.prometheus.url=${PROM_URL}"
  helm upgrade --install kiali-server kiali/kiali-server -n istio-system -f "${KIALI_VALUES}" \
    --set "external_services.prometheus.url=${PROM_URL}" \
    --set "external_services.grafana.url=${GRAF_URL}" --wait --atomic || {
    printf '%s\n' "❗ Failed to install kiali-server via Helm."
    return 1
  }

  # Apply ServiceMonitor so Prometheus scrapes Kiali metrics (safe to apply regardless)
  if [[ -f "${KIALI_SERVICEMONITOR}" ]]; then
    kubectl -n monitoring apply -f "${KIALI_SERVICEMONITOR}" || true
  fi
}

# --- Execute optional installs ---
if [[ ${WITH_ISTIO} -eq 1 || ${WITH_KIALI} -eq 1 || ${WITH_MESH} -eq 1 ]]; then
  if [[ ${SKIP_DEPLOY} -eq 1 ]]; then
    printf '%s\n' "--skip-deploy set; skipping Istio/Kiali helm installs."
  else
    if [[ ${WITH_ISTIO} -eq 1 || ${WITH_MESH} -eq 1 ]]; then
      install_istio
    fi
    if [[ ${WITH_KIALI} -eq 1 || ${WITH_MESH} -eq 1 ]]; then
      install_kiali
    fi
  fi
fi

printf '%s\n' "Notes:"
printf '%s\n' "- Label your workload namespaces for sidecar injection: kubectl label ns <ns> istio-injection=enabled"
printf '%s\n' "- Port-forward Kiali: kubectl -n istio-system port-forward svc/kiali 20001:20001"

