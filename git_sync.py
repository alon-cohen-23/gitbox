import os
import time
import subprocess
import sys
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from watchdog.utils.event_debouncer import EventDebouncer
from plyer import notification
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()
# Check if WATCH_FOLDER is provided as a command-line argument
if len(sys.argv) > 1:
    WATCH_FOLDER = sys.argv[1]
else:
    # Fallback to the WATCH_FOLDER from the .env file or a default value
    WATCH_FOLDER = os.getenv('WATCH_FOLDER', 'your/folder/path')


GIT_LFS_TRACK = os.getenv('GIT_LFS_TRACK', [])
GIT_LFS_TRACK = GIT_LFS_TRACK.split(',')

PULL_INTERVAL_MINUTES = 1

# Create a threading lock and an event to stop the thread
git_lock = threading.Lock()
stop_event = threading.Event()

def show_notification(title, message):
    trimmed_message = message[:255]  # Trim the message to 255 characters
    """Show a system tray notification."""
    notification.notify(
        title=title,
        message=trimmed_message,
        app_name='Git Sync',
        timeout=15
    )
def run_command(command):
    try:
        print(command)
        result = subprocess.run(command, check=True, shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            print(f"Command output: {result.stdout.strip()}")
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        error_message = f"Error executing command: {e}"
        if e.stderr and type(e.stderr)==str and e.stderr.strip():
            error_message += f"\nError output: {e.stderr.strip()}"
            print(f"Error output: {e.stderr.strip()}")
        print(error_message)
        return False, error_message
    
def add_git_lfs_tracking ():
    for i in GIT_LFS_TRACK:
       run_command(f'git -C {WATCH_FOLDER} lfs track "{i}"')
    run_command(f'git -C "{WATCH_FOLDER}" commit -m "Auto-commit: Added lfs tracking"')   
    
def check_if_ahead():
    # Check if local branch is ahead of the remote branch
    success, output = run_command(f'git -C "{WATCH_FOLDER}" status -uno')
    if success and "Your branch is ahead of" in output:
        print("Local branch is ahead of remote. Pushing changes...")
        success, push_output = run_command(f'git -C "{WATCH_FOLDER}" push')
        if not success:
            msg = "Push failed while trying to sync local changes."
            show_notification("Push Failed", msg + '\n' + push_output)
        return success
    return False

def git_sync():
    with git_lock:
            # Changes detected, proceed with git operations
            if run_command(f'git -C "{WATCH_FOLDER}" add .')[0]:
                if run_command(f'git -C "{WATCH_FOLDER}" commit -m "Auto-commit: Syncing changes"')[0]:
                    success, push_output = run_command(f'git -C "{WATCH_FOLDER}" push')
                    if not success:
                        # If push failed, notify and attempt to pull and merge
                        msg = "Push failed, attempting to pull and merge..."
                        print(msg)
                        show_notification("Push Failed", msg + '\n' + push_output)
                        pull_merge_and_push()
            else:
                print("No changes detected.")
def pull_merge_and_push():
    with git_lock:
        print("Attempting to pull and merge...")
        success, output = run_command(f'git -C "{WATCH_FOLDER}" pull')
        if not success: 
            msg = "Pull failed, stopping further operations."
            print(msg)
            show_notification("Pull Failed", msg + '\n' + output)
            return  # Stop further operations if the pull fails
        # Check if the pull resulted in a merge commit (i.e., no conflicts)
        if "Merge made by the" in output or "Fast-forward" in output:
            print("Merge was successful with no conflicts. Pushing changes...")
            success, push_output = run_command(f'git -C "{WATCH_FOLDER}" push')
            if not success:
                show_notification("Push After Merge Failed", push_output)
def pull_and_merge():
    while not stop_event.is_set():
        time.sleep(PULL_INTERVAL_MINUTES * 60)  # Sleep first to allow initial commits
        pull_merge_and_push()

class GitHandler(FileSystemEventHandler):
    def __init__(self, debounce_interval_seconds=5):
        self.debouncer = EventDebouncer(debounce_interval_seconds, self.handle_events)
        self.debouncer.start()

    def on_any_event(self, event):
        if event.is_directory:
            return None

        # Check if the file is not in the .git directory
        if not event.src_path.replace(WATCH_FOLDER, '').startswith(os.path.sep + '.git' + os.path.sep):
            print(f"File change detected: {event.src_path}")
            self.debouncer.handle_event(event)

    def handle_events(self, events):
        # Called by the EventDebouncer after debounce_interval_seconds
        print(f"Handling {len(events)} debounced events.")
        git_sync()

def main():
    add_git_lfs_tracking()
    print(f'gitto: git sync "{WATCH_FOLDER}"')
    pull_merge_and_push()
    
    # Check if local branch is ahead of remote and push if necessary
    check_if_ahead()

    # Perform initial sync
    print("Performing initial sync...")
    git_sync()

    observer = Observer()
    handler = GitHandler(debounce_interval_seconds=5)  # Set debounce interval to 5 seconds
    observer.schedule(handler, path=WATCH_FOLDER, recursive=True)
    observer.start()

    # Start the pull_and_merge function in a separate thread
    pull_thread = threading.Thread(target=pull_and_merge, daemon=True)
    pull_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected, stopping...")
        stop_event.set()  # Signal the pull thread to stop
        observer.stop()    # Stop the observer
    observer.join(timeout=5)  # Wait for the observer to finish with a timeout
    pull_thread.join(timeout=5)  # Wait for the pull thread to finish with a timeout

if __name__ == "__main__":
    main()
    
