#!/usr/bin/env bash
# Opt-in build with the locally installed toolkit. Never install a driver or touch models.
set -euo pipefail
umask 077
omnicore_pin=c3df4b7e22a1ac38da663552d19e649dd97ca936
omnicore_cache=${XDG_CACHE_HOME:-"$HOME/.cache"}/omnicore/llama-cuda-$omnicore_pin
omnicore_target=${XDG_DATA_HOME:-"$HOME/.local/share"}/omnicore/engines/cuda
for dependency in git cmake ninja nvcc patchelf; do
  command -v "$dependency" >/dev/null || { echo "Missing $dependency. On CachyOS install git cmake ninja cuda patchelf with your package manager." >&2; exit 2; }
done
if [[ -e "$omnicore_target/llama-server" ]]; then
  echo 'A managed CUDA engine already exists; preserving it. Configure it in OmniCore or choose another XDG_DATA_HOME.' >&2
  exit 2
fi
mkdir -p "$(dirname -- "$omnicore_cache")" "$(dirname -- "$omnicore_target")"
if [[ ! -e "$omnicore_cache" ]]; then
  git clone --no-checkout https://github.com/ggml-org/llama.cpp.git "$omnicore_cache"
  git -C "$omnicore_cache" checkout --detach "$omnicore_pin"
fi
[[ $(git -C "$omnicore_cache" rev-parse HEAD) == "$omnicore_pin" ]] || { echo 'Unexpected source revision; preserving source.' >&2; exit 2; }
cmake -S "$omnicore_cache" -B "$omnicore_cache/build-cuda" -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DGGML_CUDA_NO_VMM=ON -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build "$omnicore_cache/build-cuda" --target llama-server -j 2
omnicore_stage=$(mktemp -d "$(dirname -- "$omnicore_target")/.cuda-install.XXXXXXXX")
trap 'rm -rf -- "$omnicore_stage"' EXIT
cp "$omnicore_cache/build-cuda/bin/llama-server" "$omnicore_stage/"
cp "$omnicore_cache/build-cuda/bin/"*.so* "$omnicore_stage/"
cp "$omnicore_cache/LICENSE" "$omnicore_stage/"
omnicore_cuda_lib="$(dirname -- "$(dirname -- "$(readlink -f -- "$(command -v nvcc)")")")/lib64"
for library in "$omnicore_stage/llama-server" "$omnicore_stage/"*.so*; do
  patchelf --set-rpath '$ORIGIN':"$omnicore_cuda_lib" "$library"
done
"$omnicore_stage/llama-server" --version
# Atomic installation only when the target has never existed; no replacement of user files.
[[ ! -e "$omnicore_target" ]] || { echo 'Target already exists; preserving it.' >&2; exit 2; }
mv -T -- "$omnicore_stage" "$omnicore_target"
trap - EXIT
echo 'CUDA engine installed. OmniCore Auto will discover it. Run the hardware acceptance test before relying on CUDA.'
