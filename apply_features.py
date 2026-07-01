import os
import shutil
import filecmp

src_dir = r"c:\Users\Priyanshu\Downloads\wisoft-coworker-main\wisoft-coworker-main"
dst_dir = r"c:\Users\Priyanshu\Downloads\latest_co_worker"

def apply_feature_updates(src, dst):
    files_updated = 0
    backups_created = 0
    
    for root, dirs, files in os.walk(src):
        # Ignore common unnecessary directories if needed, e.g., node_modules, .git
        if '.git' in dirs:
            dirs.remove('.git')
        if 'node_modules' in dirs:
            dirs.remove('node_modules')
            
        rel_path = os.path.relpath(root, src)
        target_dir = os.path.join(dst, rel_path)
        
        for file in files:
            src_file = os.path.join(root, file)
            target_file = os.path.join(target_dir, file)
            
            # If file exists in both places and is different
            if os.path.exists(target_file):
                if not filecmp.cmp(src_file, target_file, shallow=False):
                    try:
                        # Create a backup of the old file first to ensure NO code is deleted/lost
                        backup_file = target_file + ".bak"
                        shutil.copy2(target_file, backup_file)
                        backups_created += 1
                        
                        # Overwrite with the new feature file
                        shutil.copy2(src_file, target_file)
                        files_updated += 1
                        print(f"Updated: {target_file} (Backup saved as .bak)")
                    except Exception as e:
                        print(f"Error updating {src_file}: {e}")

    print(f"\nSummary: Updated {files_updated} files with new features. Created {backups_created} backups.")

if __name__ == "__main__":
    print(f"Starting to apply feature updates from:\n{src_dir}\nto\n{dst_dir}...\n")
    apply_feature_updates(src_dir, dst_dir)
    print("Feature update complete!")
