#!/bin/bash

usage() {
cat <<'USAGE'
Usage: curl ... | bash -s -- <image-name> <k8s-file> [container-name]

Description:
    Builds a Docker image using the current Git commit as a temporary tag,
    pushes the image to the registry, retrieves the image digest, and updates
    the given Kubernetes YAML file to reference the image by its digest.

Arguments:
    <image-name>   e.g. myrepo/myimage
    <k8s-file>     path to the Kubernetes YAML file to update
    [container-name]  (optional) container name in the YAML to target

Options:
    -h, --help     Show this help message and exit
    -f, --dockerfile <path>  Use an alternative Dockerfile (default: Dockerfile)

Notes:
    - You must be logged in to your Docker registry before running this script.
    - The script expects to be run from within a Git repository (uses git SHA).
    - The sed replacement is simplistic; ensure the YAML contains a line like
        "image: <image-name>..." so it can be replaced correctly.
USAGE
}

# Print the usage info if requested 
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
        usage
        exit 0
fi

# Default Dockerfile path
DOCKERFILE_PATH="Dockerfile"

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -f|--dockerfile)
            shift
            if [ -z "$1" ]; then
                echo "Error: --dockerfile requires a path argument"
                exit 1
            fi
            DOCKERFILE_PATH="$1"
            shift
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

IMAGE_NAME=$1      # z.B. myrepo/myimage
K8S_FILE=$2        # z.B. deployment.yaml
CONTAINER_NAME=$3  # use container name in yaml 

if [ -z "$IMAGE_NAME" ] || [ -z "$K8S_FILE" ]; then
    echo "Usage: curl ... | bash -s -- <image-name> <k8s-file> <container-name-in-yaml>"
    exit 1
fi
echo ""
echo "--- Starte Build-Prozess für $IMAGE_NAME ---"

GIT_SHA=$(git rev-parse --short HEAD)
FULL_IMAGE_NAME="${IMAGE_NAME}:${GIT_SHA}"

# check if file is present
if [ ! -f "$DOCKERFILE_PATH" ]; then
    echo "Error: No Dockerfile found at '$DOCKERFILE_PATH' in $(pwd). Place a Dockerfile there or pass -f /path/to/Dockerfile."
    exit 1
fi

# Ensure logged in to Docker (simple check) 
# TODO: This check is not working
if ! docker info 2>/dev/null | grep -q '^Username:'; then
    echo "Warning: docker does not appear to be logged in. Please run 'docker login' if pushing to a remote registry."
fi

# build the image
if ! docker build -f "$DOCKERFILE_PATH" -t "$FULL_IMAGE_NAME" .; then
    echo "Error: docker build failed. Ensure Dockerfile is valid and docker daemon is running."
    exit 1
fi
echo "|------------------------------------------"
echo "|---> Docker image built: $FULL_IMAGE_NAME"
echo "|"
echo "|---> Pushing image to registry and retrieving digest... "

# Push and capture output to extract digest if available
PUSH_OUTPUT=$(docker push "$FULL_IMAGE_NAME" 2>&1) || {
    echo "|Error: docker push failed. Output:";
    echo "|$PUSH_OUTPUT";
    exit 1
}

# Try to find digest in push output (pattern: sha256:...)
# TODO: this is not stable. change it to use docker inspect 
DIGEST=$(echo "$PUSH_OUTPUT" | grep -oE 'sha256:[a-f0-9]+' | head -n1 | sed 's/sha256://')
if [ -z "$DIGEST" ]; then
    # If not found, fall back to RepoDigests from docker inspect
    if [ -z "$DIGEST" ]; then
        DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "$FULL_IMAGE_NAME" 2>/dev/null | cut -d'@' -f2)
    fi
fi


if [ -z "$DIGEST" ]; then
    echo "|Error: Could not retrieve digest. Was the image pushed?"
    exit 1
fi

echo "|---> Found digest: $DIGEST"
echo "|"
echo "|---> Updating Kubernetes YAML file: $K8S_FILE"
# 3. Replace the image in the static YAML file
# Ensure the digest includes the algorithm (e.g. sha256:...);
if [[ "$DIGEST" =~ ^sha256: ]]; then
    DIGEST_FULL="$DIGEST"
else
    DIGEST_FULL="sha256:${DIGEST}"
fi
NEW_IMAGE_REFERENCE="${IMAGE_NAME}@${DIGEST_FULL}"

# Perform a global image replacement in the YAML file (portable sed)
if [ ! -f "$K8S_FILE" ]; then
    echo "| Error: target YAML file '$K8S_FILE' does not exist. Aborting replacement."
    exit 1
fi
grep -- "| image: ${IMAGE_NAME}" "$K8S_FILE" || echo "| (no direct 'image: ${IMAGE_NAME}' matches found)"
grep -- "| image:" "$K8S_FILE" | head -n 10 || true

REPLACEMENT_CMD_STATUS=0
# Compute image basename (e.g. 'data_consumer' from 'mathiskae/data_consumer')
IMAGE_BASENAME="${IMAGE_NAME##*/}"

# Use a portable awk-based replacement that writes to a temp file and moves it into place.
TMPFILE="$(mktemp "${K8S_FILE}.tmp.XXXXXX")"
echo "|---> Using portable awk replacement (matching basename='${IMAGE_BASENAME}'), writing to $TMPFILE"
awk -v basename="$IMAGE_BASENAME" -v newref="$NEW_IMAGE_REFERENCE" '
  { if ($0 ~ /^[[:space:]]*image:/ && $0 ~ basename && !replaced) {
        match($0,/^[[:space:]]*/);
        lead=substr($0,RSTART,RLENGTH);
        print lead "image: " newref;
        replaced=1;
    } else {
        print $0;
    } }
' "$K8S_FILE" > "$TMPFILE" || REPLACEMENT_CMD_STATUS=$?

if [ "$REPLACEMENT_CMD_STATUS" -eq 0 ]; then
    # Only move the temp file over the real file if awk succeeded
    mv "$TMPFILE" "$K8S_FILE" || { echo "| Error: could not move temp file to $K8S_FILE"; REPLACEMENT_CMD_STATUS=1; }
else
    echo "| Replacement awk failed (exit $REPLACEMENT_CMD_STATUS). Leaving original file untouched."
    rm -f "$TMPFILE" 2>/dev/null || true
fi

echo "|                              "
echo "|---> Verifying replacement results (first matching lines):"
grep -n -- "${NEW_IMAGE_REFERENCE}" "$K8S_FILE" | head -n 20 || echo "|  (no lines found containing the new image reference)"

if ! grep -q -- "${NEW_IMAGE_REFERENCE}" "$K8S_FILE"; then
    echo "| Replacement did not succeed."


    echo "| Attempting fallback: replace first 'image:' line with the new image reference (safe for single-deployment files)"
    if awk -v newref="${NEW_IMAGE_REFERENCE}" 'BEGIN{done=0} {
          if(!done && $0 ~ /^[[:space:]]*image:/){
              match($0,/^[[:space:]]*/);
              lead=substr($0,RSTART,RLENGTH);
              print lead "image: " newref;
              done=1;
          } else print $0;
        }' "$K8S_FILE" > "$K8S_FILE.tmp"; then
        mv "$K8S_FILE.tmp" "$K8S_FILE"
        echo "| Fallback replacement performed — verifying results..."
        if grep -- "| ${NEW_IMAGE_REFERENCE}" "$K8S_FILE" | head -n 20; then
            echo "| Fallback replacement succeeded."
        else
            echo "| Fallback did not produce the expected. Check the file $K8S_FILE manually.";
        fi
    else
        echo "| Fallback replacement failed (awk error)."
    fi
else
    echo "| Replacement succeeded. YAML file $K8S_FILE has been updated with the digest."
fi

echo "| Ready for: kubectl apply -f $K8S_FILE"