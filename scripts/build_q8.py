"""Build weight-only Q8 models, keeping activations at floating point precision."""
import argparse
import logging
from pathlib import Path

import onnx
from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, MatMulNBitsQuantizer

logging.getLogger("onnxruntime.quantization.matmul_nbits_quantizer").setLevel(logging.ERROR)


def build(source: Path, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    for tower in ("text", "vision"):
        output = target / f"{tower}_model_q8f16.onnx"
        if output.is_file():
            continue
        print(f"Quantizing {tower}: 8-bit weights, floating point activations", flush=True)
        model = onnx.load(str(source / f"{tower}_model_fp16.onnx"))
        config = DefaultWeightOnlyQuantConfig(
            bits=8, block_size=32, is_symmetric=True, accuracy_level=1,
            op_types_to_quantize=("MatMul",),
        )
        quantizer = MatMulNBitsQuantizer(model, algo_config=config)
        quantizer.process()
        quantizer.model.save_model_to_file(str(output), use_external_data_format=False)
        print(f"Saved {output.name}: {output.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("model_cache/onnx-int8/onnx"))
    parser.add_argument("--target", type=Path, default=Path("model_cache/onnx/onnx"))
    args = parser.parse_args()
    build(args.source, args.target)
