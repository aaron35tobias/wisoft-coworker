import filecmp
import os

src_dir = r"c:\Users\Priyanshu\Downloads\wisoft-coworker-main\wisoft-coworker-main"
dst_dir = r"c:\Users\Priyanshu\Downloads\latest_co_worker"

def compare_dirs(src, dst):
    diff_files = []
    for root, dirs, files in os.walk(src):
        rel_path = os.path.relpath(root, src)
        target_dir = os.path.join(dst, rel_path)
        
        for file in files:
            src_file = os.path.join(root, file)
            target_file = os.path.join(target_dir, file)
            
            if os.path.exists(target_file):
                if not filecmp.cmp(src_file, target_file, shallow=False):
                    diff_files.append(os.path.join(rel_path, file))
    return diff_files

if __name__ == "__main__":
    diffs = compare_dirs(src_dir, dst_dir)
    print(f"Found {len(diffs)} files that exist in both but differ:")
    for d in diffs:
        print("  " + d)
