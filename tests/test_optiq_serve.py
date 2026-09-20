from __future__ import annotations

import base64
import io
import sys
import types
import unittest
from unittest import mock
from types import SimpleNamespace

from PIL import Image

from macjev import optiq_serve


def _image_data_url() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class OptiqServeTests(unittest.TestCase):
    def _reset_patch_state(self) -> None:
        self.addCleanup(
            setattr, optiq_serve, "_PATCHED", optiq_serve._PATCHED
        )
        self.addCleanup(
            setattr,
            optiq_serve,
            "diffusion_stream_generate",
            optiq_serve.diffusion_stream_generate,
        )
        optiq_serve._PATCHED = False
        optiq_serve.diffusion_stream_generate = None

    def test_decodes_image_data_url(self) -> None:
        image = optiq_serve._image_from_part(
            {"type": "image_url", "image_url": {"url": _image_data_url()}}
        )

        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (2, 2))

    def test_rejects_non_data_image_sources(self) -> None:
        for source in (
            "/etc/passwd",
            "file:///etc/passwd",
            "https://example.com/image.png",
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    optiq_serve._image_from_part(
                        {"type": "image_url", "image_url": {"url": source}}
                    )

    def test_rejects_invalid_data_image_payloads(self) -> None:
        for source in (
            "data:image/png;base64",
            "data:image/png;base64,not-base64",
            "data:image/png;base64,AAAA",
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    optiq_serve._image_from_part({"url": source})

    def test_extracts_text_and_images_from_messages(self) -> None:
        prompt, images = optiq_serve._messages_to_prompt_and_images(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before "},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url()},
                        },
                        {"type": "text", "text": "after"},
                    ],
                }
            ]
        )

        self.assertEqual(prompt, "Before after")
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].size, (2, 2))

    def test_rejects_installed_version_drift(self) -> None:
        self._reset_patch_state()
        with mock.patch("macjev.optiq_serve.version", return_value="0.5.11"):
            with self.assertRaisesRegex(RuntimeError, "0.5.12"):
                optiq_serve.patch_diffusion_vision_serving()

    def test_patch_routes_diffusion_images_to_native_stream(self) -> None:
        self._reset_patch_state()
        calls: dict[str, object] = {}

        class GenerationResponse:
            def __init__(self, **kwargs: object) -> None:
                self.__dict__.update(kwargs)

        mlx = types.ModuleType("mlx")
        mlx_core = types.ModuleType("mlx.core")
        mlx_core.float32 = object()
        mlx_core.zeros = lambda *args, **kwargs: None
        mlx.core = mlx_core

        mlx_lm = types.ModuleType("mlx_lm")
        mlx_lm.__path__ = []
        mlx_lm_generate = types.ModuleType("mlx_lm.generate")
        mlx_lm_generate.GenerationResponse = GenerationResponse
        mlx_lm.generate = mlx_lm_generate

        server = types.ModuleType("mlx_lm.server")

        def original_stream_generate(*args: object, **kwargs: object):
            calls["original_stream_generate"] = (args, kwargs)
            yield "original"

        server.stream_generate = original_stream_generate

        class FakeTokenizer:
            chat_template = "template"
            eos_token_id = 1

            def apply_chat_template(self, *args: object, **kwargs: object):
                calls["apply_chat_template"] = kwargs
                return "prompt"

            def decode(self, tokens: object, **kwargs: object) -> str:
                return "answer"

        tokenizer = FakeTokenizer()
        model = SimpleNamespace(
            _optiq_diffusion=True,
            config=SimpleNamespace(
                text_config=SimpleNamespace(vocab_size=16)
            ),
        )

        def original_load(*args: object, **kwargs: object):
            calls["original_load"] = (args, kwargs)
            return model, tokenizer

        server.load = original_load

        class ModelProvider:
            def _load(self, *args: object, **kwargs: object) -> None:
                self.model = model
                self.is_batchable = True

        server.ModelProvider = ModelProvider
        server.GenerationContext = object

        serve = types.ModuleType("optiq.serve")
        serve._PENDING_VLM = {}
        serve.install_diffusion_serving = lambda: calls.setdefault(
            "diffusion_install", True
        )
        serve.install_vision_serving = lambda path: calls.setdefault(
            "vision_install", path
        )

        def native_stream_generate(*args: object, **kwargs: object):
            calls["native_stream_generate"] = (args, kwargs)
            yield SimpleNamespace(
                is_draft=False,
                token=7,
                prompt_tokens=3,
                prompt_tps=1.0,
                generation_tps=2.0,
                peak_memory=0.0,
                finish_reason="stop",
            )

        generate = types.ModuleType("optiq.vlm.diffusion_gemma.generate")
        generate.stream_generate = native_stream_generate
        optiq = types.ModuleType("optiq")
        optiq.__path__ = []
        optiq.serve = serve
        vlm = types.ModuleType("optiq.vlm")
        vlm.__path__ = []
        diffusion = types.ModuleType("optiq.vlm.diffusion_gemma")
        diffusion.__path__ = []

        modules = {
            "mlx": mlx,
            "mlx.core": mlx_core,
            "mlx_lm": mlx_lm,
            "mlx_lm.generate": mlx_lm_generate,
            "mlx_lm.server": server,
            "optiq": optiq,
            "optiq.serve": serve,
            "optiq.vlm": vlm,
            "optiq.vlm.diffusion_gemma": diffusion,
            "optiq.vlm.diffusion_gemma.generate": generate,
        }
        with mock.patch.dict(sys.modules, modules, clear=False):
            with mock.patch(
                "macjev.optiq_serve.version", return_value="0.5.12"
            ):
                optiq_serve.patch_diffusion_vision_serving()

            serve.install_diffusion_serving()
            self.assertEqual(calls["diffusion_install"], True)
            loaded_model, loaded_tokenizer = server.load("model")
            self.assertIs(loaded_model, model)
            self.assertEqual(loaded_tokenizer.eos_token_ids, {1})

            provider = ModelProvider()
            provider._load()
            self.assertFalse(provider.is_batchable)

            serve.install_vision_serving("model")
            self.assertEqual(calls["vision_install"], "model")
            serve._PENDING_VLM["messages"] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "choose "},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url()},
                        },
                    ],
                }
            ]
            responses = list(
                server.stream_generate(
                    model,
                    tokenizer,
                    "text prompt",
                    max_tokens=4,
                    temperature=0.1,
                )
            )

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].text, "answer")
        self.assertEqual(calls["native_stream_generate"][0][2], "choose ")
        self.assertEqual(len(calls["native_stream_generate"][1]["images"]), 1)
        self.assertEqual(calls["native_stream_generate"][1]["max_tokens"], 4)
        self.assertEqual(calls["native_stream_generate"][1]["temperature"], 0.1)


if __name__ == "__main__":
    unittest.main()
