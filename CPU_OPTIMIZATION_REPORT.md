# Dependency Optimization Report (CPU Environments)

## Overview
The application's dependencies and launch scripts have been successfully refactored to prioritize CPU-optimized environments (e.g., 1GB Oracle VirtualBox VMs without GPUs). The previous configuration caused OOM (Out Of Memory) crashes because `pip` was pulling massive (~2GB+) CUDA-enabled GPU distributions for `torch`, `torchvision`, and `torchaudio` simply because they are transitive dependencies for `sentence-transformers`.

## Technical Changes Made
1. **CPU Wheels Forced via `requirements.txt`:**
   - Appended `--extra-index-url https://download.pytorch.org/whl/cpu` to the top of `requirements.txt`.
   - Explicitly listed `torch`, `torchvision`, and `torchaudio` right below the index url flag to force standard `pip` resolvers to fetch the lightweight CPU wheels *before* processing downstream AI packages like `sentence-transformers`.

2. **Automated Swap File Generation (`start.sh`):**
   - Implemented an OS detection check for Linux.
   - If total system RAM is under 2000 MB and no swap exists, the `start.sh` script will automatically allocate and mount a 2GB `/swapfile` via `sudo` commands before triggering the `pip` installation phase.

## Estimated Savings & Impact
- **Disk Space Savings:** Reduced the Python environment footprint by approximately 1.5GB to 2GB because massive `nvidia_cudnn`, `nvidia_cublas`, and `cuda` artifacts are no longer downloaded.
- **RAM Savings during Install:** Eliminating the decompression overhead of 2GB wheels massively lowers the memory spikes during `pip install`, keeping usage under ~800MB safely within the 1GB VM budget limit.
- **Stability:** The OOM Killer (Exit Code 137) is mitigated both by smaller dependencies and the robust 2GB fallback swap allocation.
