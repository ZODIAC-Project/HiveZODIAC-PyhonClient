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
        printf '%s\n' "Usage: $0 [--skip-deploy] [--only-apply-local] [--with-kepler] [<chart-version>]"
        printf '%s\n' "  --skip-deploy        Render chart but skip helm upgrade/install"
        printf '%s\n' "  --only-apply-local   Skip rendering/helm; only apply local YAMLs in monitoring/"
        printf '%s\n' "  --with-kepler        Also install Kepler via Helm after Prometheus is ready"
      exit 0
      ;;
    --with-kepler)
      WITH_KEPLER=1
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

