import os
import shutil

src_dir = r"c:\Users\Priyanshu\Downloads\wisoft-coworker-main\wisoft-coworker-main"
dst_dir = r"c:\Users\Priyanshu\Downloads\latest_co_worker"

def copy_new_files(src, dst):
    files_copied = 0
    dirs_created = 0
    
    for root, dirs, files in os.walk(src):
        # Ignore common unnecessary directories if needed, e.g., node_modules, .git
        if '.git' in dirs:
            dirs.remove('.git')
            
        rel_path = os.path.relpath(root, src)
        target_dir = os.path.join(dst, rel_path)
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            dirs_created += 1
            print(f"Created directory: {target_dir}")
        
        for file in files:
            src_file = os.path.join(root, file)
            target_file = os.path.join(target_dir, file)
            
            if not os.path.exists(target_file):
                try:
                    shutil.copy2(src_file, target_file)
                    files_copied += 1
                    print(f"Copied: {target_file}")
                except Exception as e:
                    print(f"Error copying {src_file}: {e}")

    print(f"\nSummary: Copied {files_copied} new files and created {dirs_created} directories.")

if __name__ == "__main__":
    print(f"Starting to sync new files from:\n{src_dir}\nto\n{dst_dir}...\n")
    copy_new_files(src_dir, dst_dir)
    print("Update complete!")
