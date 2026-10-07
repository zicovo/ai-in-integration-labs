#!/usr/bin/env python3
"""ground-the-answer's measure: index-the-manuals's, with the ground-the-answer question set. `--retriever vector` or `--retriever hybrid`.

    python measure.py --retriever vector
    python measure.py --retriever hybrid

Question eleven has no relevance entry and is skipped here; score.py is where it counts.
"""
import pathlib
import runpy
import sys

HERE = pathlib.Path(__file__).resolve().parent
B01 = HERE.parent / "index-the-manuals"
CORPUS = HERE.parent / "corpus" / "ground-the-answer"

sys.path.insert(0, str(B01))
args = sys.argv[1:]
if not any(a.startswith("--questions") for a in args):
    args += ["--questions", str(CORPUS / "questions.yaml"), "--relevance", str(CORPUS / "relevance.yaml")]
sys.argv = [str(B01 / "measure.py")] + args
runpy.run_path(str(B01 / "measure.py"), run_name="__main__")
