from __future__ import annotations

import os
from getpass import getpass

HARDCODED_HF_TOKEN = "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"


def resolve_hf_token(prompt_if_missing: bool = False) -> str:
    token = os.getenv("HF_TOKEN", "").strip()
    if token:
        return _store_token(token)

    token = _get_token_from_colab_secrets()
    if token:
        return _store_token(token)

    if HARDCODED_HF_TOKEN:
        return _store_token(HARDCODED_HF_TOKEN)

    if prompt_if_missing:
        token = getpass("Enter Hugging Face token (HF_TOKEN): ").strip()
        if token:
            return _store_token(token)

    raise RuntimeError(
        "Hugging Face token not found. Set HF_TOKEN in the environment or Colab Secrets."
    )


def login_to_huggingface(token: str | None = None, prompt_if_missing: bool = True) -> str:
    resolved = token or resolve_hf_token(prompt_if_missing=prompt_if_missing)
    try:
        from huggingface_hub import login

        login(token=resolved)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "huggingface_hub is not installed. Install it before calling login_to_huggingface()."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Hugging Face login failed. Update HF_TOKEN in env or Colab Secrets and try again."
        ) from exc
    return resolved


def _get_token_from_colab_secrets() -> str:
    try:
        from google.colab import userdata  # type: ignore
    except ImportError:
        return ""

    try:
        token = userdata.get("HF_TOKEN")
    except Exception:  # noqa: BLE001
        return ""

    if not token:
        return ""
    return str(token).strip()


def _store_token(token: str) -> str:
    os.environ["HF_TOKEN"] = token
    return token
