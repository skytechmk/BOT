# Proposal: ML Inference Isolation

## Context & Problem
Currently, the predictive machine learning engine evaluates models directly within the unified Python monolith (`main.py` -> `signal_generator.py`). Machine Learning inference requires large serializations and matrix operations which inherently invoke the Python GIL (Global Interpreter Lock). This stalls the primary thread, creating a head-of-line blocking situation for time-critical routines (like Telegram Signal Delivery or WebSocket parsing) executing on the same event loop.

## Proposed Architecture: Independent Microservice (gRPC or Triton)

Decouple the ML processing entirely from the core orchestration loop. `main.py` handles the data-fetching and macro environment management, but instead of scoring the ML confidence locally, it shoots an RPC request to a dedicated inference server. 

## Code Changes / Implementation Steps

### 1. NVIDIA Triton Inference Server (or FastAPI Sidecar)
Deploy the trained XGBoost + Transformer models via NVIDIA Triton Inference Server natively on the RTX 3090, or alternatively wrap the predictor inside a standalone `FastAPI` instance.

```yaml
# Add to docker-compose.yml
services:
  ml_inference:
    build: ./inference_engine
    runtime: nvidia
    ports:
      - "8000:8000"
    volumes:
      - ./models:/models
```

### 2. Main Bot Refactor (`main.py`)
Remove the heavy memory dependencies from `main.py` (`joblib`, `tensorflow`/`torch`).
Instead, post a serialized JSON of the technical indicators to the inference wrapper:

```python
import aiohttp

async def get_ml_prediction(features_dict: dict) -> float:
    async with aiohttp.ClientSession() as session:
        # Pushes computation entirely out-of-process, releasing the GIL
        async with session.post("http://ml_inference:8000/predict", json=features_dict) as resp:
            data = await resp.json()
            return data.get("prediction_confidence", 0.0)
```

## Risk Assessment
**Medium Risk**: Extracting the Python inference logic fundamentally alters the architecture and introduces dependency on network communications (`aiohttp`). If the sidecar container crashes, `main.py` must default safely back to purely Technical Analysis configurations (acting as a fallback).
