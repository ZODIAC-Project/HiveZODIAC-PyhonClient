# Monitoring (Prometheus + Grafana + Kepler)

Short guide to the in-repo monitoring deployment and helper script.

**What this contains**
- Helm deployment of `kube-prometheus-stack` (Prometheus + Grafana + Alertmanager).
- Local manifests in `monitoring/` for Grafana provisioning, Kepler (estimator), and a few helper resources.
- A helper script `monitoring/kube-prometheus-stack.sh` that renders the Helm chart and can install it.

**Quick deploy**
1. Ensure `kubectl` and `helm` are configured to your cluster (minikube recommended for testing).
2. Run the script to render and deploy (auto-selects latest chart unless you pass a version):
   ```bash
   ./monitoring/render-kube-prometheus-stack.sh
   ```
   Useful flags:
   - `--skip-deploy` : Render only, do not run `helm upgrade --install`.
   - `--only-apply-local` : Skip rendering/helm; apply only local `monitoring/*.yaml` manifests.

**How to verify**
- Port-forward Grafana: `kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80` and open http://localhost:3000
- Port-forward Prometheus: `kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090` and open http://localhost:9090/targets to see scrape targets.
