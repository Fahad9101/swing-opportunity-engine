from app.core.config import rules_hash
from app.core.constants import MODEL_NAME, MODEL_VERSION


def model_identity() -> dict[str, str]:
    return {"model_name": MODEL_NAME, "model_version": MODEL_VERSION, "rules_hash": rules_hash()}

