"""Build the pinned engine; CUDA requires an installed toolkit, never Rust or weights."""

import argparse
import shutil
import subprocess
from pathlib import Path

COMMIT = "c3df4b7e22a1ac38da663552d19e649dd97ca936"


def run(*command):
    subprocess.run(command, check=True)  # noqa: S603 — explicit build tools, no shell.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backend", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--cuda-architectures", default="89")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.backend == "cuda" and not shutil.which("nvcc"):
        parser.error("Install the NVIDIA CUDA toolkit first; CPU builds remain independent")
    if args.jobs < 1:
        parser.error("jobs must be positive")
    if any(not architecture.isdigit() for architecture in args.cuda_architectures.split(";")):
        parser.error("CUDA architectures must be numeric, e.g. 89 for RTX 4060")
    git = shutil.which("git") or "/usr/bin/git"
    source = args.source.absolute()
    if not source.exists():
        run(git, "clone", "--no-checkout", "https://github.com/ggml-org/llama.cpp", str(source))
        run(git, "-C", str(source), "checkout", "--detach", COMMIT)
    actual = subprocess.check_output(  # noqa: S603
        [git, "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != COMMIT:
        parser.error(
            "Existing source has a different commit; use a separate build source directory"
        )
    build = source / ("build-cuda" if args.backend == "cuda" else "build")
    options = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DGGML_NATIVE=OFF",
        "-DGGML_OPENMP=OFF",
        "-DLLAMA_CURL=OFF",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_BUILD_EXAMPLES=OFF",
        "-DLLAMA_BUILD_SERVER=ON",
        f"-DGGML_CUDA={'ON' if args.backend == 'cuda' else 'OFF'}",
    ]
    if args.backend == "cuda":
        options += [
            f"-DCMAKE_CUDA_ARCHITECTURES={args.cuda_architectures}",
            "-DGGML_CUDA_NO_VMM=ON",
        ]
    run("cmake", "-S", str(source), "-B", str(build), "-G", "Ninja", *options)
    run("cmake", "--build", str(build), "--target", "llama-server", "-j", str(args.jobs))
    print(
        f"Built {build / 'bin/llama-server'} ({args.backend}); "
        "GPU inference requires hardware tests"
    )


if __name__ == "__main__":
    main()
