# Proposal: Update OpenRouter AI to Nemotron-3 Super 120B

## Reason for Change
The operator requested to replace the current OpenRouter AI model (DeepSeek/Llama/Misc Free Models rotation) with the specific model `nvidia/nemotron-3-super-120b-a12b:free` and to use a newly provided API key.

## Risk Assessment
**Low Risk.**
- Changing the AI model only impacts the final sentiment analysis and systemic fragility checks.
- Assuming the Nemotron model strictly follows the formatting requested by the prompts, this will not break the async loop.
- The API key change is isolated to `.env`.

## Exact Changes

### 1. Update `.env` (Environment Variables)
**File Path**: `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env`

Update or replace the existing OpenRouter API key entry:
```diff
- OPENROUTER_API_KEY=your_old_api_key_here
+ OPENROUTER_API_KEY=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
```

### 2. Update `openrouter_intelligence.py` (Model List)
**File Path**: `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/openrouter_intelligence.py`

Replace the list of `free_models` to enforce the usage of Nemotron, or set it as the exclusive model so the bot doesn't rotate away from it.

```diff
     def __init__(self, api_key=None, model=None):
         self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
-        # Use free models only
-        self.free_models = [
-            "meta-llama/llama-3.1-8b-instruct:free",
-            "microsoft/phi-3-medium-128k-instruct:free", 
-            "google/gemma-2-9b-it:free",
-            "qwen/qwen-2.5-7b-instruct:free",
-            "anthropic/claude-3-haiku:free",
-            "mistralai/mistral-7b-instruct:free",
-            "meta-llama/llama-3.1-70b-instruct:free",
-            "google/gemma-7b-it:free"
-        ]
+        self.free_models = [
+            "nvidia/nemotron-3-super-120b-a12b:free"
+        ]
         self.current_model_index = 0
```
