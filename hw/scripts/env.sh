# Common environment for the Coding-Adv-HW harness on nano4 (NCHC, 8x H200 per node).
# NVHPC_VER=25.9 source hw/scripts/env.sh   (default 26.3)
NVHPC_VER=${NVHPC_VER:-26.3}
module purge >/dev/null 2>&1
module load x86-nvhpc/${NVHPC_VER}
export MFC_CUDA_CC=90
# HPC-X Open MPI bundled with NVHPC: relocated install, so point OPAL_PREFIX at it (else MPI_Init cannot find its
# help/aux files). Slurm cgroups only expose the allocated cores, so Open MPI's default bind-to-core on core 0 fails;
# MPIRUN uses --bind-to none unless a binding experiment overrides it.
export OPAL_PREFIX=$(dirname "$(dirname "$(command -v mpirun)")")
export MPIRUN=${MPIRUN:-"mpirun --bind-to none"}
# login-node scratch (builds) and quota-limited shared storage (binaries, inputs, small results)
export ADV_ROOT=${ADV_ROOT:-/tmp/twtomtwcc00-mfcadv}
export ADV_WORK=${ADV_WORK:-/work/twtomtwcc00/mfc-adv}
export ADV_CASE=${ADV_CASE:-3D_performance_test}
export SLURM_ACCOUNT_ARGS="-A ACD110018 -p dev --exclude=25a-hgpn001,25a-hgpn062"
