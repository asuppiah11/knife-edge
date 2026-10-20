"""Agent layer: moment selection, narration, localisation, verification.

The pipeline runs fully offline in *template mode* (no LLM) so the product
always has a trustworthy fallback. In *LLM mode* a Foundry-hosted model
drafts the text and a deterministic Verifier grounds every number and name
against the facts before anything is shown.
"""

from .pipeline import CuePipeline, LLM
from .verifier import verify_cue, VerifierResult

__all__ = ["CuePipeline", "LLM", "verify_cue", "VerifierResult"]
