#!/bin/bash
#SBATCH -J mfc-test
#SBATCH -A ACD110018
#SBATCH -p dev
#SBATCH --exclude=25a-hgpn001,25a-hgpn062
#SBATCH -N 1
#SBATCH --gres=gpu:2
#SBATCH -c 24
#SBATCH -t 04:00:00
#SBATCH -o /work/twtomtwcc00/mfc-adv/logs/%x-%j.out
#
# MFC's own regression suite (golden files, tol 1e-12) on H200 with an OpenACC build of REF (git ref of this repo),
# built and run on node-local /tmp. Run once for the unmodified upstream commit and once for the optimized HEAD and
# compare the failure lists: a change is accepted only if it adds no failure.
#   sbatch --export=ALL,REF=3a9bb766,TAG=test_base hw/scripts/regtest.sbatch
#   sbatch --export=ALL,REF=main,TAG=test_opt hw/scripts/regtest.sbatch
# env: TEST_ARGS (extra ./mfc.sh test args, e.g. "-o 3D" or "-% 50")
set -uo pipefail
source /work/twtomtwcc00/mfc-adv/scripts/env.sh
REF=${REF:-main}
TAG=${TAG:-test-$SLURM_JOB_ID}
RES=$ADV_WORK/results/$TAG
SRC=/tmp/mfcadv-test-$SLURM_JOB_ID
mkdir -p "$RES"
git clone -q https://github.com/TWTom041/NTHU-HPC-II-Coding-Adv-HW.git "$SRC" && cd "$SRC" && git checkout -q "$REF"
git log -1 --format='%H %s' > "$RES/ref.txt"
# MFC's default launcher search picks srun first; this HPC-X Open MPI has no Slurm PMI support ("getting job size
# failed" in a first attempt), so force mpirun (-b) and disable Open MPI's bind-to-core inside the Slurm cgroup.
export OMPI_MCA_hwloc_base_binding_policy=none
./mfc.sh test --gpu acc -j 12 -g 0 1 ${TEST_ARGS:-} -- -b mpirun > "$RES/test.log" 2>&1
echo "exit=$?" >> "$RES/ref.txt"
cp tests/failed_uuids.txt "$RES/" 2>/dev/null || true
grep -E "passed|failed|skipped|TESTS" "$RES/test.log" | tail -8 > "$RES/summary.txt"
grep -iE "^ *\( *[0-9]+/ *[0-9]+\).*(fail|error)" "$RES/test.log" > "$RES/failures.txt" || true
xz -T4 "$RES/test.log"
rm -rf "$SRC"
