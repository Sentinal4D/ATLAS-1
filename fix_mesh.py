import os, glob, trimesh, pymeshfix as mf
from tqdm import tqdm

in_dir = "/mnt/nvme0n1/Datasets/SingleCellFromNathan_17122021/Plate1/stacked_off_smoothed"
out_dir = "/mnt/nvme0n1/Datasets/SingleCellFromNathan_17122021/Plate1/stacked_off_smoothed_fixed"
os.makedirs(out_dir, exist_ok=True)

for path in tqdm(glob.glob(os.path.join(in_dir, "**/*.off"))):
    mesh = trimesh.load(path, process=False)  # OFF works here
    M = mf.MeshFix(mesh.vertices, mesh.faces)
    M.repair(joincomp=True, remove_smallest_components=True)
    fixed = trimesh.Trimesh(vertices=M.v, faces=M.f, process=False)
    fixed.export(os.path.join(out_dir, os.path.basename(path)))  # can export as .off too
