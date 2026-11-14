"""Pinned, public CLIP assets. This module does not load application secrets."""

ONNX_REPO = "Xenova/clip-vit-base-patch32"
ONNX_REVISION = "6b7c523703ae26e39be4b03774966f8571c7f523"
Q8_BUILD_ID = "ort1.23.2-weight8-block32-symmetric-accuracy1"
COMMON_FILES = ("tokenizer.json", "preprocessor_config.json")
MODEL_FILES = {
    "q8f16": ("onnx/text_model_q8f16.onnx", "onnx/vision_model_q8f16.onnx"),
    "q4f16": ("onnx/text_model_q4f16.onnx", "onnx/vision_model_q4f16.onnx"),
    "uint8": ("onnx/text_model_uint8.onnx", "onnx/vision_model_uint8.onnx"),
    "fp16": ("onnx/text_model_fp16.onnx", "onnx/vision_model_fp16.onnx"),
    "mixed": ("onnx/text_model_fp16.onnx", "onnx/vision_model_uint8.onnx"),
}
ONNX_FILES = MODEL_FILES["q8f16"] + COMMON_FILES

