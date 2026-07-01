import os
import shutil

dst_dir = r"c:\Users\Priyanshu\Downloads\latest_co_worker"

def restore_backups(dst):
    restored = 0
    for root, dirs, files in os.walk(dst):
        for file in files:
            if file.endswith('.bak'):
                backup_file = os.path.join(root, file)
                original_file = backup_file[:-4] # remove .bak
                
                try:
                    shutil.move(backup_file, original_file)
                    restored += 1
                    print(f"Restored: {original_file}")
                except Exception as e:
                    print(f"Error restoring {original_file}: {e}")
                    
    print(f"\nSummary: Successfully restored {restored} files to their original latest_co_worker state.")

if __name__ == "__main__":
    print(f"Starting to restore backups in:\n{dst_dir}...\n")
    restore_backups(dst_dir)
    print("Restore complete!")
