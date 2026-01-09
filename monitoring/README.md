# Monitoring (Prometheus + Grafana + Kepler)

Short guide to the in-repo monitoring deployment and helper script.

**What this contains**
- Helm deployment of `kube-prometheus-stack` (Prometheus + Grafana ).
- Local manifests in `monitoring/` for Grafana datasource
- Local manifests in `monitoring/kepler/` for Kepler monitoring.
- Script `monitoring/kube-prometheus-stack.sh` that renders and installs the Helm charts.

**Script usage**
```bash
./monitoring/kube-prometheus-stack.sh [--skip-deploy] [--only-apply-local] [--with-kepler] [<chart-version>] 
```    
**Script flags**

- `--skip-deploy`: Render the charts but skip `helm upgrade --install` (generating manifests without applying).
- `--only-apply-local`: Skip chart rendering/helm, and only `kubectl apply` the local YAML files in `monitoring/`(for changes in local files like the grafana-datasource file).
- `--with-kepler`: (opt-in) Install Kepler via Helm after Prometheus becomes available.

Note: When using `--only-apply-local`, the script will still apply local `ServiceMonitor` manifests such as `monitoring/kepler/servicemonitor.yaml` (so Prometheus scrape config is present), but it will not run Helm to install Kepler itself.

**How to get the password for Grafana 'admin' user**
```bash
kubectl --namespace monitoring get secrets monitoring-grafana -o jsonpath="{.data.admin-password}" | base64 -d ; echo
```
Then port forward Grafana and login with user `admin` and the retrieved password:
```bash
export POD_NAME=$(kubectl --namespace monitoring get pod -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=monitoring" -oname)
  kubectl --namespace monitoring port-forward $POD_NAME 3000
```

**How to verify**
- Port-forward Grafana and open http://localhost:3000 (script above)
- Port-forward Prometheus: `kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090` and open http://localhost:9090/targets to see scrape targets.
- If the Kepler installation was used, check for Kepler pods and services in the `monitoring` namespace:
  ```bash
  kubectl -n monitoring get pods -l app.kubernetes.io/name=kepler
  kubectl -n monitoring get svc -l app.kubernetes.io/name=kepler
  ```
And check that Prometheus has Kepler scrape targets at http://localhost:9090/targets


