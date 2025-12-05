#!/usr/bin/env bash
set -euo pipefail
# Render kube-prometheus-stack into monitoring/charts/kube-prometheus-stack.yaml

CHART=prometheus-community/kube-prometheus-stack
VERSION=""
OUT=monitoring/charts/kube-prometheus-stack.yaml

# Flags
SKIP_DEPLOY=0
ONLY_APPLY_LOCAL=0

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
      echo "Usage: $0 [--skip-deploy] [--only-apply-local] [<chart-version>]"
      echo "  --skip-deploy        Render chart but skip helm upgrade/install"
      echo "  --only-apply-local   Skip rendering/helm; only apply local YAMLs in monitoring/"
      exit 0
      ;;
    *)
      if [[ -z "${VERSION// }" ]]; then
        VERSION="$arg"
      fi
      ;;
  esac
done

LATEST_TESTED_VERSION=79.11.0

function latest_version_via_helm() {
  helm repo update >/dev/null 2>&1 || true
  helm search repo prometheus-community/kube-prometheus-stack --versions | sed -n '2p' | awk '{print $2}'
}


echo "Rendering kube-prometheus-stack (chart ${CHART})"

LATEST_AVAILABLE_VERSION=$(latest_version_via_helm)

if [[ -z "${VERSION// }" ]]; then
  VERSION=${LATEST_AVAILABLE_VERSION}
  echo "No version provided; using latest available: ${VERSION}"
fi

if [[ -z "${VERSION}" ]]; then
  echo "Failed to determine a chart version. Please provide one as argument." >&2
  exit 2
fi

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo update

echo "Rendering chart version ${VERSION} to ${OUT}"
helm template monitoring ${CHART} --version "${VERSION}" -f monitoring/charts/values.yaml > "${OUT}"
echo "Rendered chart to ${OUT}"

if [[ ${ONLY_APPLY_LOCAL} -eq 1 ]]; then
  echo "--only-apply-local set; skipping render/helm and applying local manifests only."
else
  if [[ ${SKIP_DEPLOY} -eq 1 ]]; then
    echo "--skip-deploy set; rendering only (no helm upgrade/install)."
  else
    echo "Installing/upgrading kube-prometheus-stack into namespace 'monitoring' (helm upgrade --install)"
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    helm upgrade --install monitoring ${CHART} --version "${VERSION}" -n monitoring -f monitoring/charts/values.yaml
    echo "Helm upgrade/install command finished. Use 'kubectl get pods -n monitoring' to watch pod status."
  fi
fi

# Apply local YAML manifests in monitoring/ (excluding charts dir and this script)
echo "Applying local manifests in monitoring/"
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
shopt -s nullglob
for f in monitoring/*.yaml; do
  # skip charts output and this script's possible rendered file
  case "${f}" in
    monitoring/charts/*|monitoring/render-*)
      continue
      ;;
  esac
  echo "Applying ${f}"
  kubectl apply -f "${f}"
done
shopt -u nullglob

echo "Applied local manifests. Use 'kubectl get pods -n monitoring' to check status." 
