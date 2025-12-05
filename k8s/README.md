Minimal Setup: broker-mediated DB access control using reservation policies 
=============================================================
## Files: 
------------
- `Dockerfile.backend` — Dockerfile for the backend service (ingest + reservation enforcement).
- `Dockerfile.dashboard` — Dockerfile for the dashboard service (REST + WebSocket UI)
- `k8s/deployment.yaml` — Kubernetes deployment manifest for deploying the PoC services.

## Steps to run the PoC
1. Build Docker images for the backend and dashboard services:

```zsh
docker build -f Dockerfile.backend -t poc-backend:latest .
docker build -f Dockerfile.publisher -t poc-publisher:latest .
```
2. Load the Docker images into your Minikube cluster (if using Minikube):

```zsh
minikube image load poc-backend:latest
minikube image load poc-publisher:latest
```
3. Apply the Kubernetes deployment manifest to create the resources:

```zsh
kubectl apply -f k8s/deployments.yaml -n hivezodiac
```
4. Remove the deployed resources when done:

```zsh
kubectl delete -f k8s/deployments.yaml -n hivezodiac
``` 
