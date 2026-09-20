"""MacJev-owned compatibility launcher for mlx-optiq serving.

mlx-optiq 0.5.12 can run DiffusionGemma text generation, but its generic
serving layer does not preserve DiffusionGemma image inputs. Keep the
compatibility fixes here instead of modifying the installed package.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any, Callable, Iterable

from .schema import is_data_image_url

SUPPORTED_OPTIQ_VERSION = "0.5.12"

_PATCHED = False
diffusion_stream_generate: Callable[..., Iterable[Any]] | None = None


def _image_from_part(part: dict[str, Any]) -> Any:
    from PIL import Image

    source = part.get("image") or part.get("image_url") or part.get("url")
    if isinstance(source, dict):
        source = source.get("url")
    if not isinstance(source, str):
        raise TypeError(f"unsupported image source: {type(source)!r}")
    if not is_data_image_url(source):
        raise ValueError("image source must be a data:image URL")
    try:
        _, encoded = source.split(",", 1)
    except ValueError as exc:
        raise ValueError("image data URL is missing a comma") from exc

    import base64
    import binascii
    import io

    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("image data URL is not valid base64") from exc
    try:
        return Image.open(io.BytesIO(payload)).convert("RGB")
    except OSError as exc:
        raise ValueError("image data URL does not contain a supported image") from exc


def _messages_to_prompt_and_images(
    messages: list[dict[str, Any]],
) -> tuple[str, list[Any]]:
    prompt_parts: list[str] = []
    images: list[Any] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            prompt_parts.append(content)
            continue
        for part in content or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                prompt_parts.append(part.get("text", ""))
            elif part.get("type") in ("image", "image_url", "input_image"):
                images.append(_image_from_part(part))
    return "".join(prompt_parts), images


def _decode_events(
    results: Iterable[Any],
    tokenizer: Any,
    on_prompt_tokens: Callable[[int], None] | None = None,
    logprobs: Any = None,
) -> Iterable[Any]:
    from mlx_lm.generate import GenerationResponse

    emitted_tokens: list[int] = []
    previous_text = ""
    generation_index = 0
    for result in results:
        if getattr(result, "is_draft", False):
            continue
        generation_index += 1
        if result.token is not None:
            emitted_tokens.append(int(result.token))
        current_text = tokenizer.decode(emitted_tokens, skip_special_tokens=True)
        text = current_text[len(previous_text) :]
        previous_text = current_text
        if on_prompt_tokens is not None:
            on_prompt_tokens(result.prompt_tokens)
        yield GenerationResponse(
            text=text,
            token=result.token,
            logprobs=logprobs,
            from_draft=False,
            prompt_tokens=result.prompt_tokens,
            prompt_tps=result.prompt_tps,
            generation_tokens=generation_index,
            generation_tps=result.generation_tps,
            peak_memory=result.peak_memory,
            finish_reason=result.finish_reason,
        )


def patch_diffusion_vision_serving() -> None:
    """Apply the five compatibility fixes required by mlx-optiq 0.5.12."""

    global _PATCHED
    if _PATCHED:
        return

    installed_version = version("mlx-optiq")
    if installed_version != SUPPORTED_OPTIQ_VERSION:
        raise RuntimeError(
            "MacJev OptiQ vision compatibility is pinned to mlx-optiq "
            f"{SUPPORTED_OPTIQ_VERSION}; found {installed_version}"
        )

    import mlx_lm.server as server_mod
    from optiq import serve
    from optiq.vlm.diffusion_gemma.generate import (
        stream_generate as _diffusion_stream_generate,
    )

    global diffusion_stream_generate
    diffusion_stream_generate = _diffusion_stream_generate

    original_install = serve.install_diffusion_serving
    original_vision_install = serve.install_vision_serving

    def install_vision_with_diffusion(model_path: str) -> None:
        original_vision_install(model_path)
        current_stream_generate = server_mod.stream_generate

        def stream_generate(
            model: Any,
            tokenizer: Any,
            prompt: Any,
            max_tokens: int = 256,
            **kwargs: Any,
        ) -> Iterable[Any]:
            pending = serve._PENDING_VLM.get("messages")
            if not getattr(model, "_optiq_diffusion", False):
                yield from current_stream_generate(
                    model, tokenizer, prompt, max_tokens, **kwargs
                )
                return

            if not pending:
                yield from current_stream_generate(
                    model, tokenizer, prompt, max_tokens, **kwargs
                )
                return

            prompt_text, images = _messages_to_prompt_and_images(pending)
            temperature = float(
                kwargs.get("temp", kwargs.get("temperature", 0.0))
            )
            context = serve._PENDING_VLM.get("ctx")
            results = diffusion_stream_generate(
                model,
                tokenizer,
                prompt_text,
                images=images,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            def update_usage(prompt_tokens: int) -> None:
                if context is not None:
                    context.prompt = [0] * int(prompt_tokens)
                    context.prompt_cache_count = 0

            yield from _decode_events(
                results,
                tokenizer,
                update_usage,
                logprobs=serve._NULL_LOGPROBS,
            )

        server_mod.stream_generate = stream_generate

    serve.install_vision_serving = install_vision_with_diffusion

    def install_with_compat() -> None:
        original_install()
        current_load = server_mod.load
        model_provider = server_mod.ModelProvider
        original_provider_load = model_provider._load

        def load(model_path: str, *args: Any, **kwargs: Any) -> Any:
            model, tokenizer = current_load(model_path, *args, **kwargs)
            if not getattr(model, "_optiq_diffusion", False):
                return model, tokenizer

            original_apply_chat_template = tokenizer.apply_chat_template

            def apply_chat_template(*args: Any, **kwargs: Any) -> Any:
                if kwargs.get("tokenize", True):
                    kwargs.setdefault("return_dict", False)
                return original_apply_chat_template(*args, **kwargs)

            object.__setattr__(
                tokenizer, "apply_chat_template", apply_chat_template
            )
            if not hasattr(tokenizer, "has_chat_template"):
                tokenizer.has_chat_template = (
                    getattr(tokenizer, "chat_template", None) is not None
                )
            if not hasattr(tokenizer, "has_tool_calling"):
                tokenizer.has_tool_calling = False
            if not hasattr(tokenizer, "has_thinking"):
                tokenizer.has_thinking = False
            if not hasattr(tokenizer, "tool_parser"):
                tokenizer.tool_parser = None
            eos_token_id = getattr(tokenizer, "eos_token_id", None)
            if eos_token_id is not None:
                tokenizer.eos_token_ids = {int(eos_token_id)}
            return model, tokenizer

        server_mod.load = load

        def provider_load(self: Any, *args: Any, **kwargs: Any) -> None:
            original_provider_load(self, *args, **kwargs)
            if getattr(self.model, "_optiq_diffusion", False):
                self.is_batchable = False

        model_provider._load = provider_load

    serve.install_diffusion_serving = install_with_compat
    _PATCHED = True


def main() -> None:
    patch_diffusion_vision_serving()
    from optiq.cli import cli

    cli()


if __name__ == "__main__":
    main()
