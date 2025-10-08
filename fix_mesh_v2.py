# pip install trimesh pymeshfix
import os, glob, csv, traceback
import trimesh
import pymeshfix as mf
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutErrorqq

# -------------------- CONFIG --------------------
IN_DIR = "/mnt/nvme0n1/Datasets/SingleCellFromNathan_17122021/Plate3/stacked_off_smoothed"
OUT_DIR = "/mnt/nvme0n1/Datasets/SingleCellFromNathan_17122021/Plate3/stacked_off_smoothed_fixed"
EXT_GLOB = "*.off"         # change to *.obj / *.ply / *.stl if needed
TIMEOUT_S = 60             # per-mesh timeout in seconds
MAX_VERTS = 3_000_000      # skip monsters that will likely hang
MAX_FACES = 3_000_000
LOG_CSV   = os.path.join(OUT_DIR, "repair_log.csv")
# ------------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)

def save_mesh(vertices, faces, out_path):
    m = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    # light clean-up: ensure indices compact, remove degens
    m.remove_unreferenced_vertices()
    m.remove_degenerate_faces()
    m.export(out_path)

def fallback_fast_fill(path_in, path_out):
    # A lightweight, surgical cap of small boundary loops
    m = trimesh.load(path_in, process=False)
    # quick sanity clean
    m.remove_unreferenced_vertices()
    m.remove_degenerate_faces()
    # fill simple holes (won't fix everything, but fast)
    trimesh.repair.fill_holes(m)
    # keep largest component to avoid tiny floaters
    if not m.is_empty:
        comps = m.split(only_watertight=False)
        if comps:
            m = max(comps, key=lambda c: len(c.faces))
    m.export(path_out)

def repair_with_pymeshfix(path_in, path_out):
    mesh = trimesh.load(path_in, process=False)
    if mesh.vertices.shape[0] > MAX_VERTS or mesh.faces.shape[0] > MAX_FACES:
        return {"status": "skipped", "reason": "too_large"}

    M = mf.MeshFix(mesh.vertices, mesh.faces)
    # join components; drop tiny bits
    M.repair(verbose=False, joincomp=True, remove_smallest_components=True)
    save_mesh(M.v, M.f, path_out)

    return {"status": "ok", "watertight": trimesh.load(path_out, process=False).is_watertight}

def process_one(path_in):
    """
    Runs in a separate process so TIMEOUT can kill it cleanly.
    Returns a dict with keys: status, reason (optional).
    """
    out_path = os.path.join(OUT_DIR, os.path.basename(path_in))
    try:
        # 1) primary: PyMeshFix
        r = repair_with_pymeshfix(path_in, out_path)
        if r.get("status") == "ok":
            return {"status": "ok", "method": "pymeshfix", "out": out_path, "wt": r.get("watertight")}
        if r.get("status") == "skipped":
            return r | {"method": "none", "out": ""}
    except Exception as e:
        # fall through to fallback
        err1 = f"pymeshfix_error: {e}"

    # 2) fallback: quick boundary fill (best-effort)
    try:
        fallback_fast_fill(path_in, out_path)
        wt = trimesh.load(out_path, process=False).is_watertight
        return {"status": "ok", "method": "fallback_fill", "out": out_path, "wt": wt}
    except Exception as e2:
        return {"status": "failed", "reason": f"{err1 if 'err1' in locals() else ''} | fallback_error: {e2}"}

def main():
    paths = sorted(glob.glob(os.path.join(IN_DIR, EXT_GLOB)))
    if not paths:
        print(f"No files found in {IN_DIR}/{EXT_GLOB}")
        return

    with open(LOG_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "status", "method", "watertight", "reason_or_output"])

        futures = {}
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
            for p in paths:
                futures[ex.submit(process_one, p)] = p

            done_count = 0
            for fut in as_completed(futures, timeout=None):
                path = futures[fut]
                try:
                    result = fut.result(timeout=0)  # already completed to be here
                except TimeoutError:
                    # (rare here; kept for completeness)
                    result = {"status": "timeout", "method": "n/a", "wt": "", "reason": ""}
                except Exception as e:
                    tb = traceback.format_exc(limit=1)
                    result = {"status": "failed", "method": "n/a", "wt": "", "reason": f"runner_error: {e} {tb}"}

                # Write log line
                w.writerow([
                    os.path.basename(path),
                    result.get("status"),
                    result.get("method", ""),
                    result.get("wt", ""),
                    result.get("reason", result.get("out", "")),
                ])

                done_count += 1
                if done_count % 20 == 0:
                    print(f"Processed {done_count}/{len(paths)}")

def main_with_timeouts():
    # Same as main(), but we enforce a wall-clock TIMEOUT_S per mesh by waiting on each future with a timeout.
    paths = sorted(glob.glob(os.path.join(IN_DIR, EXT_GLOB)))
    if not paths:
        print(f"No files found in {IN_DIR}/{EXT_GLOB}")
        return

    with open(LOG_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "status", "method", "watertight", "reason_or_output"])

        with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
            for p in paths:
                fut = ex.submit(process_one, p)
                try:
                    res = fut.result(timeout=TIMEOUT_S)
                except TimeoutError:
                    res = {"status": "timeout", "method": "n/a", "wt": "", "reason": f"exceeded {TIMEOUT_S}s"}
                except Exception as e:
                    tb = traceback.format_exc(limit=1)
                    res = {"status": "failed", "method": "n/a", "wt": "", "reason": f"runner_error: {e} {tb}"}

                w.writerow([
                    os.path.basename(p),
                    res.get("status"),
                    res.get("method", ""),
                    res.get("wt", ""),
                    res.get("reason", res.get("out", "")),
                ])

if __name__ == "__main__":
    # Choose the timeout-enforced runner:
    main_with_timeouts()
