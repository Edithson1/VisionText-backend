"""Create a separate Q8 arithmetic variant without changing production assets."""
from pathlib import Path
import shutil
import onnx

root = Path(__file__).resolve().parents[1]
source = root / "model_cache/onnx"
target = root / "model_cache/q8-accuracy4"
(target / "onnx").mkdir(parents=True, exist_ok=True)
for filename in ("tokenizer.json", "preprocessor_config.json", "manifest.json"):
    shutil.copyfile(source / filename, target / filename)
for tower in ("text", "vision"):
    filename = f"onnx/{tower}_model_q8f16.onnx"
    model = onnx.load(str(source / filename))
    for node in model.graph.node:
        if node.op_type == "MatMulNBits":
            for attribute in node.attribute:
                if attribute.name == "accuracy_level":
                    attribute.i = 4
    onnx.save(model, str(target / filename))
print("Prepared isolated Q8 accuracy_level=4 experiment", flush=True)
