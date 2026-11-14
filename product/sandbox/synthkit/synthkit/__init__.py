"""synthkit: deterministic synthetic test data for model audits.

Flow (docs/services/sandbox.md): ``profile`` (understand the model first) →
``scenarios-check`` → ``generate`` (GenerationSpec + seed → dataset + Data Card)
→ ``analyze`` (five gates, shown to the human before approval).
"""

__version__ = "0.1.0"
GENERATOR = f"synthkit {__version__}"
