
```zsh
docker build -f Dockerfile.dataConsumer -t data-consumer:latest . &&
docker build -f Dockerfile.posClient -t pos-client:latest .
```
2. Load the Docker images into your Minikube cluster (if using Minikube):

```zsh
minikube image load data-consumer:latest &&
minikube image load pos-client:latest
```
3. Apply both Kubernetes deployment manifest to create the resources:

```zsh
kubectl apply -f k8s/
```
