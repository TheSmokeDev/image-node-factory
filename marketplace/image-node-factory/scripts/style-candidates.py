"""Offline candidate stage; shares the verified corpus implementation."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("factory_style_corpus", Path(__file__).with_name("style-corpus.py"))
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
if __name__ == "__main__":
    raise SystemExit(module.main(["candidates"]))
