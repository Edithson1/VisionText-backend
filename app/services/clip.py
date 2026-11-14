"""CLIP inference without importing PyTorch in the production ONNX path."""
import io
import json
from pathlib import Path
import threading
from typing import Union, Tuple

import numpy as np
from PIL import Image

from app.clip_assets import ONNX_REVISION, Q8_BUILD_ID
from app.config import settings
from app.services.memory import release_unused_memory


class ONNXCLIP:
    def __init__(self):
        self.model = None
        self.text_model = None
        self.tokenizer = None

    def load_model(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if settings.clip_model != "ViT-B-32" or settings.clip_pretrained != "openai":
            raise ValueError("ONNX requiere CLIP_MODEL=ViT-B-32 y CLIP_PRETRAINED=openai")
        directory = Path(settings.onnx_model_dir)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("Faltan modelos ONNX. Ejecuta python scripts/prepare_onnx.py")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != ONNX_REVISION:
            raise RuntimeError("Revisión ONNX incompatible. Prepara los modelos de nuevo.")
        if settings.onnx_precision == "q8f16" and manifest.get("conversion") != Q8_BUILD_ID:
            raise RuntimeError("Prepara el perfil Q8 con python scripts/prepare_onnx.py")
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, settings.inference_threads)
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        text_precision = "fp16" if settings.onnx_precision in {"fp16", "mixed"} else "uint8"
        image_precision = "fp16" if settings.onnx_precision == "fp16" else "uint8"
        if settings.onnx_precision in {"q4f16", "q8f16"}:
            text_precision = image_precision = settings.onnx_precision
        self.text_model = ort.InferenceSession(
            str(directory / f"onnx/text_model_{text_precision}.onnx"), options,
            providers=["CPUExecutionProvider"],
        )
        self.model = ort.InferenceSession(
            str(directory / f"onnx/vision_model_{image_precision}.onnx"), options,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=77)
        self.tokenizer.enable_padding(length=77, pad_id=49407, pad_token="<|endoftext|>")
        self.preprocess = json.loads((directory / "preprocessor_config.json").read_text(encoding="utf-8"))
        print(f"CLIP ONNX {settings.onnx_precision} ready ({ONNX_REVISION[:8]}, {settings.inference_threads} thread)")

    @staticmethod
    def normalize(vector):
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        return vector / max(float(np.linalg.norm(vector)), 1e-12)

    def encode_text(self, text):
        encoded = self.tokenizer.encode(text)
        inputs = {"input_ids": np.array([encoded.ids], dtype=np.int64)}
        if any(item.name == "attention_mask" for item in self.text_model.get_inputs()):
            inputs["attention_mask"] = np.array([encoded.attention_mask], dtype=np.int64)
        return self.normalize(self.text_model.run(["text_embeds"], inputs)[0])

    def encode_image(self, image):
        if isinstance(image, (str, Path)):
            with Image.open(image) as source:
                pil_image = source.convert("RGB")
                source.close()
        elif isinstance(image, bytes):
            with Image.open(io.BytesIO(image)) as source:
                pil_image = source.convert("RGB")
                source.close()
        else:
            pil_image = image if image.mode == "RGB" else image.convert("RGB")
        config = self.preprocess
        edge = config["size"]["shortest_edge"]
        width, height = pil_image.size
        # Extremely thin images must not create a huge intermediate resize.
        # CLIP ultimately uses only the center; discard the distant ends first.
        if width > 16 * height:
            left = (width - 16 * height) // 2
            pil_image = pil_image.crop((left, 0, left + 16 * height, height))
        elif height > 16 * width:
            top = (height - 16 * width) // 2
            pil_image = pil_image.crop((0, top, width, top + 16 * width))
        width, height = pil_image.size
        ratio = edge / min(width, height)
        pil_image = pil_image.resize((int(width * ratio), int(height * ratio)), Image.Resampling.BICUBIC)
        crop = config["crop_size"]
        left = round((pil_image.width - crop["width"]) / 2)
        top = round((pil_image.height - crop["height"]) / 2)
        pil_image = pil_image.crop((left, top, left + crop["width"], top + crop["height"]))
        pixels = np.asarray(pil_image, dtype=np.float32) * np.float32(config["rescale_factor"])
        pixels = (pixels - np.array(config["image_mean"], dtype=np.float32)) / np.array(config["image_std"], dtype=np.float32)
        pixels = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])
        if self.model.get_inputs()[0].type == "tensor(float16)":
            pixels = pixels.astype(np.float16)
        return self.normalize(self.model.run(["image_embeds"], {"pixel_values": pixels})[0])

    def get_embedding_dimension(self):
        return 512


class CLIPService:
    def __init__(self):
        self.engine = None
        self._lock = threading.RLock()

    @property
    def model(self):
        return self.engine.model if self.engine is not None else None

    @property
    def embedding_model(self):
        if settings.clip_backend == "onnx":
            conversion = Q8_BUILD_ID if settings.onnx_precision == "q8f16" else settings.onnx_precision
            return f"clip-vit-base-patch32:onnx-{conversion}:{ONNX_REVISION}:v2"
        return f"{settings.clip_model}:{settings.clip_pretrained}:torch:v1"

    def load_model(self):
        with self._lock:
            if settings.clip_backend == "onnx":
                self.engine = ONNXCLIP()
            else:
                from app.services.clip_torch import CLIPService as TorchCLIP
                import torch
                torch.set_num_threads(max(1, settings.inference_threads))
                self.engine = TorchCLIP()
            self.engine.load_model()
            release_unused_memory()

    def encode_text(self, text: str) -> np.ndarray:
        with self._lock:
            try:
                return self.engine.encode_text(text)
            finally:
                release_unused_memory()

    def encode_image(self, image: Union[Image.Image, str, bytes]) -> np.ndarray:
        with self._lock:
            try:
                return self.engine.encode_image(image)
            finally:
                release_unused_memory()

    @staticmethod
    def compute_similarity(embedding1, embedding2) -> float:
        return float(np.dot(embedding1, embedding2))

    def validate_image_text_similarity(self, image, text, threshold=None) -> Tuple[bool, float]:
        with self._lock:
            score = self.compute_similarity(self.encode_image(image), self.encode_text(text))
        return score >= (settings.similarity_threshold if threshold is None else threshold), score

    def get_embedding_dimension(self) -> int:
        return self.engine.get_embedding_dimension()


clip_service = CLIPService()
