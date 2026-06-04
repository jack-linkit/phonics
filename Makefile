IMAGE_NAME ?= phonics-poc
IMAGE_TAG ?= local
PORT ?= 8000
ENV_FILE ?= .env

.PHONY: start docker-build docker-run

start:
	@if [ -f "$(ENV_FILE)" ]; then set -a; . "$(ENV_FILE)"; set +a; fi; uvicorn app:app --reload --host 0.0.0.0 --port $(PORT)

docker-build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-run:
	@test -f "$(ENV_FILE)" || { echo "Missing $(ENV_FILE). Copy .env.example to $(ENV_FILE) and fill in your Azure values."; exit 1; }
	docker run --rm -p $(PORT):8000 --env-file "$(ENV_FILE)" $(IMAGE_NAME):$(IMAGE_TAG)
