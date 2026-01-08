This POS client generates sample receips and sends them to the endpoint of a MCP Client.
It can be configured to send a number of messages or retained messages.

**Endpoints:**
GET /health
    Health check endpoint.
POST /trigger
    Trigger a run 
    - Content-Type: application/json
    - Body Parameters:
        - Single receipt (default):
            {}
        - Multiple receipts:
            {"num_messages": <number_of_messages>}
        - Retained receipts:
            {"mode":"retained","num_messages": <number_of_messages>}

**Environment Variables:**
MCP_URL: URL of the MCP endpoint (default: http://mcp-client:5000)
MANDANT_ID: Name of the fictional store (default: mandant_1234)
NUM_MESSAGES: Number of messages to send at startup (default: 0)
POST_TIMEOUT: Timeout for POST requests to the LLM endpoint in seconds (default: 10)

**Usage:**
TThis describes how to run the POS client in a kubernetes environment using minikube.
1. Ensure you have minikube and kubectl installed and running.
2. Build the Docker image for the POS client:
    ```bash
    docker build -t pos-client:latest financial_use_case/pos-client
    ```
3. Load the Docker image into your Minikube cluster:
    ```bash
    minikube image load pos-client:latest
    ```
4. Use the YAML file in the k8s folder to deploy the client (adjust the envoironment variables as needed):
    ```bash
    kubectl apply -f k8s/client-deployment.yaml
    ```
5. Reaching the health route for verification:
    ```bash
    kubectl port-forward deployment/pos-client 8000:8000
    curl http://localhost:8000/health
    ```