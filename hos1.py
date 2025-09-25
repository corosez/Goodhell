#coded by @avesz @corose 
import subprocess
import sys

required_modules = [
    "os",
    "logging",
    "json",
    "time",
    "threading",
    "subprocess",
    "psutil",
    "platform", 
    "asyncio",
    "signal",
    "uuid",
    "datetime",
    "pathlib",
    "typing",
    "python-telegram-bot",
]

# Built-in modules (will not be installed)
builtin_modules = {
    "os", "logging", "json", "time", "threading", "subprocess", "platform",
    "asyncio", "signal", "uuid", "datetime", "pathlib", "typing"
}

# Install missing modules
for module in required_modules:
    if module not in builtin_modules:
        try:
            if module == "python-telegram-bot":
                __import__("telegram")
            else:
                __import__(module)
        except ImportError:
            print(f"Installing: {module} ...")
            if module == "python-telegram-bot":
                subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot[job-queue]"])
            else:
                subprocess.check_call([sys.executable, "-m", "pip", "install", module])

print("All modules are installed and ready.")

import os
import logging
import json
import time
import threading
import subprocess
import psutil
import platform
import asyncio
import signal
import uuid
import zipfile
import shutil
import tempfile
import httpx
import pty
import fcntl
import select
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ParseMode
except ImportError:
    # For older versions
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply, ParseMode
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Suppress verbose logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.INFO)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "7320676748:AAHofgkz35-MgY_LCJ_w7iCIkJ2bnMgdg0k")
ADMIN_IDS = [6827291977]  # Add your Telegram user ID here
SCRIPTS_DIR = "bot_scripts"
LOGS_DIR = "bot_logs"
DATA_FILE = "bot_data.json"
BACKUP_DIR = "backups"

class ScriptManager:
    def __init__(self):
        self.scripts: Dict[str, Dict] = {}
        self.processes: Dict[str, subprocess.Popen] = {}
        self.script_stdin_pipes: Dict[str, subprocess.Popen] = {}  # Track stdin pipes for script input
        self.terminal_sessions: Dict[int, Dict] = {}
        self.interactive_processes: Dict[int, subprocess.Popen] = {}  # For terminal sessions
        self.backup_thread = None
        self.last_backup_time = None
        self.load_data()
        self.ensure_directories()
        self.monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
        self.monitor_thread.start()
        # Start automatic backup thread
        self.start_backup_scheduler()

    def ensure_directories(self):
        """Create necessary directories"""
        # Use absolute paths to avoid path issues
        directories = [
            os.path.abspath(SCRIPTS_DIR), 
            os.path.abspath(LOGS_DIR), 
            os.path.abspath("temp_uploads"),
            os.path.abspath(BACKUP_DIR)  # Backup directory
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            # Set proper permissions
            os.chmod(directory, 0o755)
            logger.info(f"✅ Directory ready: {directory}")
        
        # Clean up old temp files (older than 1 hour)
        try:
            temp_dir = os.path.abspath("temp_uploads")
            current_time = time.time()
            cleaned_count = 0
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > 3600:  # 1 hour
                        os.remove(file_path)
                        cleaned_count += 1
            if cleaned_count > 0:
                logger.info(f"🧹 Cleaned up {cleaned_count} old temp files")
        except Exception as e:
            logger.warning(f"Error cleaning temp files: {e}")

    def load_data(self):
        """Load persistent data"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.scripts = data.get('scripts', {})
                    self.last_backup_time = data.get('last_backup_time', None)
                    logger.info(f"Loaded {len(self.scripts)} scripts from data file")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            self.scripts = {}

    def save_data(self):
        """Save persistent data"""
        try:
            data = {
                'scripts': self.scripts,
                'last_updated': datetime.now().isoformat(),
                'last_backup_time': self.last_backup_time
            }
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")

    def add_script(self, file_path: str, original_name: str, script_type: str) -> str:
        """Add a new script"""
        script_id = str(uuid.uuid4())[:8]
        unique_name = f"{script_id}_{original_name}"
        
        # Use absolute path for script directory
        scripts_dir_abs = os.path.abspath(SCRIPTS_DIR)
        final_path = os.path.join(scripts_dir_abs, unique_name)
        
        script_info = {
            'id': script_id,
            'original_name': original_name,
            'file_name': unique_name,
            'file_path': final_path,
            'script_type': script_type,
            'created_at': datetime.now().isoformat(),
            'status': 'stopped',
            'auto_restart': False,
            'restart_count': 0,
            'last_started': None,
            'last_stopped': None
        }
        
        # Move file to scripts directory
        try:
            os.rename(file_path, final_path)
            os.chmod(final_path, 0o755)
            logger.info(f"Script moved to: {final_path}")
        except Exception as e:
            logger.error(f"Error moving script file: {e}")
            raise
        
        self.scripts[script_id] = script_info
        self.save_data()
        
        logger.info(f"Added script: {original_name} with ID: {script_id}")
        return script_id

    def start_backup_scheduler(self):
        """Start the automatic backup scheduler"""
        def backup_scheduler():
            while True:
                try:
                    # Calculate next backup time (24 hours from last backup or now)
                    now = datetime.now()
                    if self.last_backup_time:
                        last_backup = datetime.fromisoformat(self.last_backup_time)
                        next_backup = last_backup + timedelta(hours=24)
                        if now >= next_backup:
                            self.create_automatic_backup()
                    else:
                        # First time, schedule backup for next 24 hours
                        self.last_backup_time = now.isoformat()
                        self.save_data()
                    
                    # Check every hour
                    time.sleep(3600)
                except Exception as e:
                    logger.error(f"Error in backup scheduler: {e}")
                    time.sleep(3600)
        
        self.backup_thread = threading.Thread(target=backup_scheduler, daemon=True)
        self.backup_thread.start()
        logger.info("📅 Automatic backup scheduler started")

    def create_backup(self, is_automatic=False):
        """Create a complete backup of all bot data"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_type = "auto" if is_automatic else "manual"
            backup_filename = f"bot_backup_{backup_type}_{timestamp}.zip"
            backup_path = os.path.join(BACKUP_DIR, backup_filename)
            
            logger.info(f"🔄 Creating {backup_type} backup: {backup_filename}")
            
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add bot_data.json
                if os.path.exists(DATA_FILE):
                    zipf.write(DATA_FILE, DATA_FILE)
                    logger.info(f"✅ Added {DATA_FILE} to backup")
                
                # Add all scripts
                if os.path.exists(SCRIPTS_DIR):
                    for root, dirs, files in os.walk(SCRIPTS_DIR):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, '.')
                            zipf.write(file_path, arcname)
                    logger.info(f"✅ Added scripts directory to backup")
                
                # Add logs directory
                if os.path.exists(LOGS_DIR):
                    for root, dirs, files in os.walk(LOGS_DIR):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, '.')
                            zipf.write(file_path, arcname)
                    logger.info(f"✅ Added logs directory to backup")
                
                # Add bot.log if exists
                if os.path.exists('bot.log'):
                    zipf.write('bot.log', 'bot.log')
                    logger.info(f"✅ Added bot.log to backup")
                
                # Add backup metadata
                metadata = {
                    'backup_type': backup_type,
                    'created_at': datetime.now().isoformat(),
                    'scripts_count': len(self.scripts),
                    'running_scripts': len([s for s in self.scripts.values() if s.get('status') == 'running']),
                    'bot_version': '2.0',
                    'platform': platform.system()
                }
                
                # Create temporary metadata file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_meta:
                    json.dump(metadata, temp_meta, indent=2)
                    temp_meta_path = temp_meta.name
                
                zipf.write(temp_meta_path, 'backup_metadata.json')
                os.unlink(temp_meta_path)
                logger.info(f"✅ Added backup metadata")
            
            # Update last backup time
            self.last_backup_time = datetime.now().isoformat()
            self.save_data()
            
            # Clean up old backups (keep last 10)
            self.cleanup_old_backups()
            
            backup_size = os.path.getsize(backup_path) / 1024
            logger.info(f"✅ Backup created successfully: {backup_filename} ({backup_size:.1f} KB)")
            
            return True, f"Backup created successfully: {backup_filename} ({backup_size:.1f} KB)", backup_path
            
        except Exception as e:
            logger.error(f"❌ Error creating backup: {e}")
            return False, f"Error creating backup: {str(e)}", None

    def create_automatic_backup(self):
        """Create automatic backup"""
        try:
            success, message, path = self.create_backup(is_automatic=True)
            if success:
                logger.info(f"✅ Automatic backup completed: {message}")
            else:
                logger.error(f"❌ Automatic backup failed: {message}")
        except Exception as e:
            logger.error(f"Error in automatic backup: {e}")

    def cleanup_old_backups(self, keep_count=10):
        """Clean up old backup files, keeping only the most recent ones"""
        try:
            if not os.path.exists(BACKUP_DIR):
                return
            
            backup_files = []
            for filename in os.listdir(BACKUP_DIR):
                if filename.startswith('bot_backup_') and filename.endswith('.zip'):
                    file_path = os.path.join(BACKUP_DIR, filename)
                    backup_files.append((file_path, os.path.getmtime(file_path)))
            
            # Sort by modification time (newest first)
            backup_files.sort(key=lambda x: x[1], reverse=True)
            
            # Remove old backups
            removed_count = 0
            for file_path, _ in backup_files[keep_count:]:
                try:
                    os.remove(file_path)
                    removed_count += 1
                except Exception as e:
                    logger.warning(f"Could not remove old backup {file_path}: {e}")
            
            if removed_count > 0:
                logger.info(f"🧹 Cleaned up {removed_count} old backup files")
                
        except Exception as e:
            logger.warning(f"Error cleaning up old backups: {e}")

    def restore_backup(self, backup_file_path: str):
        """Restore bot data from backup file - ENHANCED VERSION"""
        try:
            logger.info(f"🔄 Starting backup restoration from: {backup_file_path}")
            
            # Verify file exists
            if not os.path.exists(backup_file_path):
                return False, "Backup file not found"
            
            # Verify it's a valid zip file
            try:
                if not zipfile.is_zipfile(backup_file_path):
                    return False, "Invalid backup file format - not a valid ZIP file"
            except Exception as e:
                return False, f"Cannot read backup file: {str(e)}"
            
            # Stop all running scripts before restore
            stopped_scripts = []
            for script_id in list(self.processes.keys()):
                try:
                    if script_id in self.processes and self.processes[script_id].poll() is None:
                        self.stop_script(script_id)
                        stopped_scripts.append(script_id)
                except Exception as e:
                    logger.warning(f"Error stopping script {script_id}: {e}")
            
            logger.info(f"🛑 Stopped {len(stopped_scripts)} running scripts for restore")
            
            # Extract backup
            restore_temp_dir = tempfile.mkdtemp(prefix='restore_')
            try:
                with zipfile.ZipFile(backup_file_path, 'r') as zipf:
                    # Check if backup contains expected files
                    file_list = zipf.namelist()
                    
                    # Verify this looks like a valid backup
                    has_data_file = any(DATA_FILE in f for f in file_list)
                    has_scripts_dir = any(SCRIPTS_DIR in f for f in file_list)
                    has_metadata = any('backup_metadata.json' in f for f in file_list)
                    
                    if not (has_data_file or has_scripts_dir or has_metadata):
                        return False, "Invalid backup file - missing expected backup components"
                    
                    zipf.extractall(restore_temp_dir)
                    logger.info(f"📦 Extracted backup to temporary directory")
                
                # Restore bot_data.json
                extracted_data_file = os.path.join(restore_temp_dir, DATA_FILE)
                if os.path.exists(extracted_data_file):
                    # Backup current data file first
                    if os.path.exists(DATA_FILE):
                        shutil.copy2(DATA_FILE, f"{DATA_FILE}.backup")
                    
                    shutil.copy2(extracted_data_file, DATA_FILE)
                    logger.info(f"✅ Restored {DATA_FILE}")
                
                # Restore scripts directory
                extracted_scripts_dir = os.path.join(restore_temp_dir, SCRIPTS_DIR)
                if os.path.exists(extracted_scripts_dir):
                    # Backup current scripts directory
                    if os.path.exists(SCRIPTS_DIR):
                        backup_scripts_dir = f"{SCRIPTS_DIR}_backup_{int(time.time())}"
                        shutil.move(SCRIPTS_DIR, backup_scripts_dir)
                        logger.info(f"📁 Backed up current scripts to {backup_scripts_dir}")
                    
                    shutil.copytree(extracted_scripts_dir, SCRIPTS_DIR)
                    logger.info(f"✅ Restored {SCRIPTS_DIR}")
                
                # Restore logs directory if exists
                extracted_logs_dir = os.path.join(restore_temp_dir, LOGS_DIR)
                if os.path.exists(extracted_logs_dir):
                    if os.path.exists(LOGS_DIR):
                        backup_logs_dir = f"{LOGS_DIR}_backup_{int(time.time())}"
                        shutil.move(LOGS_DIR, backup_logs_dir)
                        logger.info(f"📋 Backed up current logs to {backup_logs_dir}")
                    
                    shutil.copytree(extracted_logs_dir, LOGS_DIR)
                    logger.info(f"✅ Restored {LOGS_DIR}")
                
                # Reload data from restored files
                try:
                    self.load_data()
                except Exception as e:
                    logger.warning(f"Warning loading restored data: {e}")
                    # Initialize empty if load fails
                    self.scripts = {}
                
                # Clear current process tracking
                self.processes.clear()
                self.script_stdin_pipes.clear()

                # --- FIX: NORMALIZE SCRIPT PATHS AND UPDATE STATUS ---
                scripts_dir_abs = os.path.abspath(SCRIPTS_DIR)
                for script_id, script_info in self.scripts.items():
                    # Update status to stopped
                    script_info['status'] = 'stopped'
                    script_info['last_stopped'] = datetime.now().isoformat()
                    script_info.pop('pid', None)

                    # Reconstruct the absolute file_path based on the script's file_name
                    # This corrects paths from a different system
                    if 'file_name' in script_info:
                        correct_path = os.path.join(scripts_dir_abs, script_info['file_name'])
                        if script_info.get('file_path') != correct_path:
                            logger.info(f"Normalizing path for script {script_id}: '{script_info.get('file_path')}' -> '{correct_path}'")
                            script_info['file_path'] = correct_path
                
                # Save the updated data with corrected paths
                self.save_data()
                
                # Validate restored scripts
                valid_scripts = 0
                for script_id, script_info in self.scripts.items():
                    if os.path.exists(script_info.get('file_path', '')):
                        valid_scripts += 1
                    else:
                        logger.warning(f"Restored script file not found after normalization: {script_info.get('file_path', 'Unknown')}")
                
                restored_count = len(self.scripts)
                logger.info(f"✅ Backup restoration completed successfully")
                
                return True, f"✅ Restoration successful! Restored {restored_count} scripts ({valid_scripts} with valid files). All scripts are stopped."
                
            finally:
                # Clean up temp directory
                try:
                    shutil.rmtree(restore_temp_dir)
                except Exception as e:
                    logger.warning(f"Could not clean up temp directory: {e}")
                    
        except zipfile.BadZipFile:
            logger.error("❌ Invalid ZIP file during restoration")
            return False, "Invalid ZIP file - file may be corrupted"
        except Exception as e:
            logger.error(f"❌ Error during backup restoration: {e}")
            return False, f"Restoration failed: {str(e)}"

    def get_run_command(self, script_info: Dict) -> List[str]:
        """Get the appropriate run command for script type"""
        file_path = script_info['file_path']
        script_type = script_info['script_type']
        
        # Use just the filename since working directory is set to script directory
        filename = os.path.basename(file_path)
        
        if script_type == 'python':
            return ['python3', filename]
        elif script_type == 'shell':
            return ['bash', filename]
        elif script_type == 'javascript':
            return ['node', filename]
        else:
            return ['bash', filename]  # Default to bash

    def start_script(self, script_id: str) -> Tuple[bool, str]:
        """Start a script - ENHANCED with proper stdin support"""
        if script_id not in self.scripts:
            return False, "Script not found"
        
        script_info = self.scripts[script_id]
        
        if script_id in self.processes and self.processes[script_id].poll() is None:
            return False, "Script is already running"
        
        # Check if script file exists
        script_path = script_info['file_path']
        if not os.path.exists(script_path):
            logger.error(f"Script file not found: {script_path}")
            return False, f"Script file not found: {script_path}"
        
        try:
            log_file_path = os.path.join(os.path.abspath(LOGS_DIR), f"{script_id}.log")
            
            with open(log_file_path, 'a') as log_file:
                log_file.write(f"\n--- Started at {datetime.now().isoformat()} ---\n")
                log_file.write(f"Script path: {script_path}\n")
                log_file.write(f"Working directory: {os.path.dirname(script_path)}\n")
                
                cmd = self.get_run_command(script_info)
                logger.info(f"Running command: {' '.join(cmd)}")
                
                # ENHANCED: Create process with stdin pipe for interactive input
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,  # Enable stdin for script input
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=os.path.dirname(script_path),
                    preexec_fn=os.setsid,
                    text=True,  # Enable text mode for easier input handling
                    bufsize=0   # Unbuffered for real-time interaction
                )
                
                self.processes[script_id] = process
                self.script_stdin_pipes[script_id] = process  # Track for input
                self.scripts[script_id]['status'] = 'running'
                self.scripts[script_id]['last_started'] = datetime.now().isoformat()
                self.scripts[script_id]['pid'] = process.pid
                self.save_data()
                
                logger.info(f"Started script {script_id} with PID {process.pid}")
                return True, f"Script started successfully (PID: {process.pid})"
                
        except Exception as e:
            logger.error(f"Error starting script {script_id}: {e}")
            return False, f"Error starting script: {str(e)}"

    def stop_script(self, script_id: str) -> Tuple[bool, str]:
        """Stop a script"""
        if script_id not in self.scripts:
            return False, "Script not found"
        
        if script_id not in self.processes:
            self.scripts[script_id]['status'] = 'stopped'
            self.save_data()
            return True, "Script was not running"
        
        try:
            process = self.processes[script_id]
            if process.poll() is None:
                # Kill the process group to ensure all child processes are terminated
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    # Wait for graceful termination
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # Force kill if it doesn't terminate gracefully  
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        process.wait()
                except OSError:
                    # Fallback to regular termination if process group doesn't exist
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            
            # Clean up
            del self.processes[script_id]
            if script_id in self.script_stdin_pipes:
                del self.script_stdin_pipes[script_id]
            
            # Update script info
            self.scripts[script_id]['status'] = 'stopped'
            self.scripts[script_id]['last_stopped'] = datetime.now().isoformat()
            self.scripts[script_id].pop('pid', None)
            
            self.save_data()
            
            logger.info(f"Stopped script: {self.scripts[script_id]['original_name']} (ID: {script_id})")
            return True, f"Script '{self.scripts[script_id]['original_name']}' stopped successfully"
            
        except Exception as e:
            logger.error(f"Error stopping script {script_id}: {e}")
            return False, f"Error stopping script: {str(e)}"

    def stop_all_scripts(self):
        """Stop all running scripts"""
        stopped_count = 0
        for script_id in list(self.processes.keys()):
            success, _ = self.stop_script(script_id)
            if success:
                stopped_count += 1
        
        logger.info(f"Stopped {stopped_count} scripts")
        return stopped_count

    def restart_script(self, script_id: str) -> Tuple[bool, str]:
        """Restart a script"""
        if script_id not in self.scripts:
            return False, "Script not found"
        
        script = self.scripts[script_id]
        
        # Stop first
        if script_id in self.processes:
            self.stop_script(script_id)
            time.sleep(1)  # Brief pause
        
        # Then start
        return self.start_script(script_id)

    def delete_script(self, script_id: str) -> Tuple[bool, str]:
        """Delete a script"""
        if script_id not in self.scripts:
            return False, "Script not found"
        
        script = self.scripts[script_id]
        
        try:
            # Stop script if running
            if script_id in self.processes:
                self.stop_script(script_id)
            
            # Delete script file
            if os.path.exists(script['file_path']):
                os.remove(script['file_path'])
            
            # Delete log file
            log_file = os.path.join(LOGS_DIR, f"{script_id}.log")
            if os.path.exists(log_file):
                os.remove(log_file)
            
            # Remove from scripts dict
            del self.scripts[script_id]
            self.save_data()
            
            logger.info(f"Deleted script: {script['original_name']} (ID: {script_id})")
            return True, f"Script '{script['original_name']}' deleted successfully"
            
        except Exception as e:
            logger.error(f"Error deleting script {script_id}: {e}")
            return False, f"Error deleting script: {str(e)}"

    def send_input_to_script(self, script_id: str, input_text: str) -> Tuple[bool, str]:
        """Send input to a running script"""
        if script_id not in self.scripts:
            return False, "Script not found"
        
        if script_id not in self.script_stdin_pipes:
            return False, "Script is not running or doesn't accept input"
        
        try:
            process = self.script_stdin_pipes[script_id]
            if process.poll() is None:  # Process is still running
                process.stdin.write(input_text + '\n')
                process.stdin.flush()
                logger.info(f"Sent input to script {script_id}: {input_text}")
                return True, "Input sent successfully"
            else:
                return False, "Script is not running"
                
        except Exception as e:
            logger.error(f"Error sending input to script {script_id}: {e}")
            return False, f"Error sending input: {str(e)}"

    def send_input_to_script_by_pid(self, pid: int, input_text: str) -> Tuple[bool, str]:
        """Send input to a script by PID"""
        try:
            # Find script by PID
            target_script_id = None
            for script_id, script_info in self.scripts.items():
                if script_info.get('pid') == pid:
                    target_script_id = script_id
                    break
            
            if not target_script_id:
                return False, f"No managed script found with PID {pid}"
            
            return self.send_input_to_script(target_script_id, input_text)
            
        except Exception as e:
            logger.error(f"Error sending input to PID {pid}: {e}")
            return False, f"Error sending input: {str(e)}"

    def get_script_logs(self, script_id: str, lines: int = 50) -> str:
        """Get recent logs from a script"""
        if script_id not in self.scripts:
            return "Script not found"
        
        log_file = os.path.join(LOGS_DIR, f"{script_id}.log")
        
        if not os.path.exists(log_file):
            return "No logs available"
        
        try:
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return ''.join(recent_lines)
        except Exception as e:
            return f"Error reading logs: {e}"

    def get_system_info(self) -> str:
        """Get system information"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            info = f"""🖥️ **System Information**
            
**CPU Usage:** {cpu_percent}%
**Memory:** {memory.percent}% used ({memory.used // 1024 // 1024} MB / {memory.total // 1024 // 1024} MB)
**Disk:** {disk.percent}% used ({disk.used // 1024 // 1024 // 1024} GB / {disk.total // 1024 // 1024 // 1024} GB)
**Platform:** {platform.system()} {platform.release()}
**Python:** {platform.python_version()}

**Running Scripts:** {len([s for s in self.scripts.values() if s.get('status') == 'running'])}
**Total Scripts:** {len(self.scripts)}
            """
            return info
        except Exception as e:
            return f"Error getting system info: {e}"

    def list_scripts(self) -> List[Dict]:
        """Get list of all scripts"""
        return list(self.scripts.values())

    def get_running_processes(self):
        """Get list of running processes"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return processes
        except Exception as e:
            logger.error(f"Error getting processes: {e}")
            return []

    def kill_process(self, pid: int) -> Tuple[bool, str]:
        """Kill a process by PID"""
        try:
            process = psutil.Process(pid)
            process.terminate()
            return True, f"Process {pid} terminated successfully"
        except psutil.NoSuchProcess:
            return False, f"Process {pid} not found"
        except psutil.AccessDenied:
            return False, f"Permission denied to kill process {pid}"
        except Exception as e:
            return False, f"Error killing process {pid}: {str(e)}"

    def monitor_processes(self):
        """Monitor running scripts and restart if needed"""
        while True:
            try:
                for script_id, process in list(self.processes.items()):
                    if process.poll() is not None:  # Process has terminated
                        script = self.scripts.get(script_id)
                        if script:
                            script['status'] = 'stopped'
                            script['last_stopped'] = datetime.now().isoformat()
                            script.pop('pid', None)
                            
                            # Auto restart if enabled
                            if script.get('auto_restart', False):
                                logger.info(f"Auto-restarting script: {script['original_name']}")
                                self.start_script(script_id)
                            
                        # Clean up
                        del self.processes[script_id]
                        if script_id in self.script_stdin_pipes:
                            del self.script_stdin_pipes[script_id]
                
                self.save_data()
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in process monitor: {e}")
                time.sleep(30)

    def toggle_auto_restart(self, script_id: str) -> Tuple[bool, str]:
        """Toggle auto-restart for a script"""
        if script_id not in self.scripts:
            return False, "Script not found"
        
        script = self.scripts[script_id]
        current_state = script.get('auto_restart', False)
        script['auto_restart'] = not current_state
        self.save_data()
        
        new_state = "enabled" if script['auto_restart'] else "disabled"
        return True, f"Auto-restart {new_state} for '{script['original_name']}'"

    def execute_terminal_command(self, user_id: int, command: str) -> str:
        """Execute a terminal command"""
        try:
            # For security, limit certain commands
            dangerous_commands = ['rm -rf', 'dd if=', 'mkfs', ':(){:|:&};:', 'sudo rm']
            if any(dangerous in command.lower() for dangerous in dangerous_commands):
                return "⚠️ Command blocked for security reasons"
            
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = result.stdout
            if result.stderr:
                output += f"\nError: {result.stderr}"
            
            return output if output else "Command executed (no output)"
            
        except subprocess.TimeoutExpired:
            return "⏱️ Command timed out (30s limit)"
        except Exception as e:
            return f"❌ Error executing command: {str(e)}"

    def start_interactive_terminal(self, user_id: int) -> Tuple[bool, str]:
        """Start interactive terminal session using a PTY."""
        if user_id in self.interactive_processes:
            return False, "Terminal session is already active."

        try:
            # Create a pseudo-terminal
            master_fd, slave_fd = pty.openpty()

            # Start a new bash session in the PTY
            process = subprocess.Popen(
                ['bash', '-i'],
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                text=True,
                bufsize=1,
                close_fds=True
            )
            
            # Close the slave descriptor in the parent
            os.close(slave_fd)

            # Make the master descriptor non-blocking
            fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            self.interactive_processes[user_id] = {
                'process': process,
                'master_fd': master_fd
            }

            logger.info(f"Started PTY-based interactive terminal for user {user_id} with PID {process.pid}")
            return True, "Interactive terminal started."
            
        except Exception as e:
            logger.error(f"Error starting PTY terminal: {e}")
            return False, f"Error starting PTY terminal: {str(e)}"

    def stop_interactive_terminal(self, user_id: int) -> Tuple[bool, str]:
        """Stop interactive terminal session and clean up resources."""
        if user_id not in self.interactive_processes:
            return False, "No active terminal session."

        try:
            session = self.interactive_processes[user_id]
            process = session['process']
            master_fd = session['master_fd']

            # Terminate the process
            if process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait(timeout=2)

            # Close the master file descriptor
            os.close(master_fd)

            del self.interactive_processes[user_id]
            logger.info(f"Stopped interactive terminal for user {user_id}")
            return True, "Interactive terminal stopped."

        except Exception as e:
            logger.error(f"Error stopping PTY terminal: {e}")
            # Ensure cleanup
            if user_id in self.interactive_processes:
                del self.interactive_processes[user_id]
            return False, f"Error stopping terminal: {str(e)}"

    def send_input_to_terminal(self, user_id: int, input_text: str, add_newline: bool = True) -> Tuple[bool, str]:
        """Send input to the PTY-based interactive terminal."""
        if user_id not in self.interactive_processes:
            return False, "No active terminal session."

        try:
            session = self.interactive_processes[user_id]
            if session['process'].poll() is not None:
                self.stop_interactive_terminal(user_id)
                return False, "Terminal session has ended. Please restart."
            
            master_fd = session['master_fd']
            
            if add_newline:
                input_text += '\n'
            
            os.write(master_fd, input_text.encode())
            return True, "Input sent."
            
        except Exception as e:
            logger.error(f"Error sending input to PTY: {e}")
            return False, f"Error sending input: {str(e)}"

    def read_terminal_output(self, user_id: int, timeout: float = 0.5) -> str:
        """Read output from the PTY-based interactive terminal."""
        if user_id not in self.interactive_processes:
            return "No active terminal session."

        try:
            session = self.interactive_processes[user_id]
            if session['process'].poll() is not None:
                self.stop_interactive_terminal(user_id)
                return "Terminal session has ended. Please restart."

            master_fd = session['master_fd']
            
            # Use select to wait for data to be available for reading
            ready_to_read, _, _ = select.select([master_fd], [], [], timeout)
            
            if ready_to_read:
                output = ""
                while True:
                    try:
                        chunk = os.read(master_fd, 1024)
                        if not chunk:
                            break
                        output += chunk.decode(errors='ignore')
                    except BlockingIOError:
                        # No more data to read at the moment
                        break
                return output if output else "No output received."
            else:
                return "No output received."
                
        except Exception as e:
            logger.error(f"Error reading PTY output: {e}")
            return f"Error reading output: {str(e)}"


class TelegramBot:
    def __init__(self):
        self.script_manager = ScriptManager()
        self.application = None

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_IDS

    async def unauthorized_response(self, update: Update):
        """Send unauthorized response"""
        await update.message.reply_text("🚫 Unauthorized access. Contact admin.")
        logger.warning(f"Unauthorized access attempt from user {update.effective_user.id}")

    async def send_script_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send input to a specific script"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            if len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Usage: `/sinput <script_id> <input_text>`\n\n"
                    "Example: `/sinput abc123 mypassword`\n"
                    "Use `/scripts` to see script IDs"
                )
                return
            
            script_id = context.args[0]
            input_text = ' '.join(context.args[1:])
            
            success, message = self.script_manager.send_input_to_script(script_id, input_text)
            
            if success:
                await update.message.reply_text(f"✅ Input sent to script {script_id}: `{input_text}`", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            logger.error(f"Error in send_script_input: {e}")
            await update.message.reply_text(f"❌ Error sending input: {str(e)}")

    async def send_pid_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send input to a script by PID"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            if len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Usage: `/pinput <pid> <input_text>`\n\n"
                    "Example: `/pinput 1234 mypassword`\n"
                    "Use `/scripts` to see script PIDs"
                )
                return
            
            try:
                pid = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ Invalid PID. Please provide a number.")
                return
            
            input_text = ' '.join(context.args[1:])
            
            success, message = self.script_manager.send_input_to_script_by_pid(pid, input_text)
            
            if success:
                await update.message.reply_text(f"✅ Input sent to PID {pid}: `{input_text}`", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            logger.error(f"Error in send_pid_input: {e}")
            await update.message.reply_text(f"❌ Error sending input: {str(e)}")

    async def send_enter_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send input with Enter key to terminal"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            user_id = update.effective_user.id
            
            # Check if in terminal mode
            if user_id not in self.script_manager.terminal_sessions:
                await update.message.reply_text("❌ Terminal mode not active. Use /terminal to enable.")
                return
            
            # Get input text
            input_text = ' '.join(context.args) if context.args else ""
            
            # Send input to terminal
            success, message = self.script_manager.send_input_to_terminal(user_id, input_text, add_newline=True)
            
            if success:
                await update.message.reply_text(f"📝 Input sent: {input_text}")
                
                # Wait a moment and get output
                await asyncio.sleep(1)
                output = self.script_manager.read_terminal_output(user_id, timeout=3.0)
                
                if output and output != "No output received":
                    # Truncate if too long
                    if len(output) > 4000:
                        output = output[:4000] + "\n\n... (output truncated)"
                    
                    await update.message.reply_text(f"```\n{output}\n```", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            logger.error(f"Error in send_enter_input: {e}")
            await update.message.reply_text(f"❌ Error sending input: {str(e)}")

    async def send_space(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send space key to terminal"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            user_id = update.effective_user.id
            
            if user_id not in self.script_manager.terminal_sessions:
                await update.message.reply_text("❌ Terminal mode not active.")
                return
            
            success, message = self.script_manager.send_input_to_terminal(user_id, " ", add_newline=False)
            
            if success:
                await update.message.reply_text("⌨️ **Space key sent**")
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            logger.error(f"Error in send_space: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def send_ctrl_c(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send Ctrl+C to terminal"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            user_id = update.effective_user.id
            
            if user_id not in self.script_manager.terminal_sessions:
                await update.message.reply_text("❌ Terminal mode not active.")
                return
            
            success, message = self.script_manager.send_input_to_terminal(user_id, "\x03", add_newline=False)  # Ctrl+C
            
            if success:
                await update.message.reply_text("🛑 **Ctrl+C sent (interrupt signal)**")
                
                # Get output after interrupt
                await asyncio.sleep(1)
                output = self.script_manager.read_terminal_output(user_id, timeout=2.0)
                if output and output != "No output received":
                    await update.message.reply_text(f"```\n{output}\n```", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            logger.error(f"Error in send_ctrl_c: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def send_raw_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send raw input without Enter to terminal"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            user_id = update.effective_user.id
            
            if user_id not in self.script_manager.terminal_sessions:
                await update.message.reply_text("❌ Terminal mode not active.")
                return
            
            if not context.args:
                await update.message.reply_text("❌ Please provide input text. Usage: `/input your text here`")
                return
            
            input_text = ' '.join(context.args)
            success, message = self.script_manager.send_input_to_terminal(user_id, input_text, add_newline=False)
            
            if success:
                await update.message.reply_text(f"📝 Raw input sent: {input_text}")
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            logger.error(f"Error in send_raw_input: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Simple test command to verify bot is working"""
        try:
            logger.info(f"📨 Test command from user {update.effective_user.id}")
            
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
                
            await update.message.reply_text("✅ Bot is working! All systems operational.")
            logger.info("✅ Test command completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Test command error: {e}")
            try:
                await update.message.reply_text(f"❌ Error: {e}")
            except:
                pass

    async def import_from_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Import a backup from a direct download link."""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return

            if not context.args:
                await update.message.reply_text("❌ **Usage:** `/importlink <direct_download_url>`\n\nPlease provide a direct download link to a .zip backup file.")
                return

            url = context.args[0]

            # Basic validation for Dropbox direct link
            if not ("dropbox.com" in url and "dl=1" in url):
                await update.message.reply_text("❌ **Invalid URL:** Please provide a Dropbox direct download link (with `?dl=1`).")
                return

            processing_msg = await update.message.reply_text("⬇️ Downloading backup file...")

            temp_file_path = None
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, follow_redirects=True, timeout=60.0)
                    response.raise_for_status()  # Raise an exception for bad status codes

                # Save to a temporary file
                temp_dir = os.path.abspath("temp_uploads")
                os.makedirs(temp_dir, exist_ok=True)
                temp_file_path = os.path.join(temp_dir, f"restore_{uuid.uuid4().hex}.zip")

                with open(temp_file_path, 'wb') as f:
                    f.write(response.content)

                await processing_msg.edit_text("📦 Backup downloaded. Verifying file...")

                # Verify it's a valid zip file
                if not zipfile.is_zipfile(temp_file_path):
                    await processing_msg.edit_text("❌ **Invalid File:** The downloaded file is not a valid .zip archive.")
                    return

                # Create a pre-restore backup
                await processing_msg.edit_text("🔄 Creating pre-restore backup of current state...")
                self.script_manager.create_backup(is_automatic=True)

                # Restore from backup
                await processing_msg.edit_text("⚙️ Restoring from backup...")
                restore_success, restore_message = self.script_manager.restore_backup(temp_file_path)

                if restore_success:
                    await processing_msg.edit_text(f"✅ **Backup Restored Successfully!**\n\n{restore_message}")
                else:
                    await processing_msg.edit_text(f"❌ **Backup Restore Failed:**\n\n{restore_message}")

            except httpx.RequestError as e:
                await processing_msg.edit_text(f"❌ **Download Failed:** Could not download the file from the URL.\nError: {e}")
            except Exception as e:
                logger.error(f"Error during import from link: {e}")
                await processing_msg.edit_text(f"❌ **An unexpected error occurred:** {e}")
            finally:
                # Clean up the temporary file
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        except Exception as e:
            logger.error(f"Error in import_from_link command: {e}")
            await update.message.reply_text(f"❌ **An unexpected error occurred:** {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        try:
            logger.info(f"📨 START command from user {update.effective_user.id}")
            
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
                
            welcome_text = """
🤖 **Enhanced Advanced Hosting Management Bot**

🚀 **Features:**
• Upload and run scripts (.py, .sh, .js)
• Real-time interactive terminal access
• Background process management
• **Script-specific input support**
• Auto-restart capabilities
• System monitoring
• Log management
• Backup/restore functionality

📋 **Commands:**
• `/scripts` - Manage your scripts
• `/status` - Server status
• `/terminal` - Toggle terminal mode
• `/cmd <command>` - Execute shell command
• `/ps` - List running processes
• `/kill <pid>` - Kill process by PID
• `/export` - Create local backup
• `/importlink <url>` - Restore from Dropbox link

🖥️ **Terminal Input Commands:**
• `/enter <text>` - Send input + Enter key
• `/space` - Send space key
• `/ctrl_c` - Send Ctrl+C (interrupt)
• `/input <text>` - Send raw input (no Enter)

🎯 **Script Input Commands:**
• `/sinput <script_id> <text>` - Send input to specific script
• `/pinput <pid> <text>` - Send input to script by PID

💡 **Quick Start:**
1. Upload a script file
2. Use inline buttons to manage it
3. Use script input commands for interactive scripts
4. Toggle terminal mode for direct shell access

Your enhanced server is ready! 🎯
            """
            
            keyboard = [
                [InlineKeyboardButton("📂 My Scripts", callback_data="list_scripts")],
                [InlineKeyboardButton("📊 Server Status", callback_data="server_status")],
                [InlineKeyboardButton("🖥️ Terminal Mode", callback_data="toggle_terminal")],
                [InlineKeyboardButton("📦 Backup Menu", callback_data="backup_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            logger.info("✅ Start command completed")
            
        except Exception as e:
            logger.error(f"❌ Start command error: {e}")
            try:
                await update.message.reply_text(f"Error: {e}")
            except:
                pass

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            help_text = """
🔧 **Enhanced Advanced Hosting Bot - Complete Guide**

**📁 Script Management:**
• Upload .py, .sh, .js files to run them
• Scripts are saved with unique names
• Start/Stop/Restart with inline buttons
• Auto-restart on crash (configurable)
• View real-time logs
• Delete scripts when no longer needed

**🎯 Script-Specific Input (Major Feature):**
• `/sinput <script_id> <input>` - Send input directly to a specific script
• `/pinput <pid> <input>` - Send input to script by PID
• Perfect for interactive scripts requiring passwords, prompts, etc.
• Works independently from global terminal mode
• Supports multiple running scripts simultaneously

**🖥️ Enhanced Terminal Features:**
• `/terminal` - Enter/exit interactive terminal mode
• `/cmd <command>` - Execute single command
• **Terminal Input Commands:**
  • `/enter <text>` - Send input + Enter (for passwords, prompts)
  • `/space` - Send space key
  • `/ctrl_c` - Send interrupt signal (Ctrl+C)
  • `/input <text>` - Send raw text without Enter
• Full interactive support for general system commands

**📊 Process Management:**
• `/ps` - List all running processes
• `/kill <pid>` - Terminate process by PID
• Background script monitoring
• Automatic restart on crash
• Process logs and status tracking

**📦 Backup/Restore System:**
• `/export` - Create manual backup (saves locally)
• `/importlink <url>` - Restore from a Dropbox direct link
• Automatic daily backups
• Complete data preservation

**🔧 System Commands:**
• `/status` - CPU, RAM, disk usage
• Monitor system performance
• View system information

**🔒 Security Features:**
• Admin-only access (unauthorized users blocked)
• All access attempts logged
• Secure process isolation
• Comprehensive error handling

**💡 Enhanced Usage Examples:**
• **Script needs password:** `/sinput abc123 mypassword`
• **Script asks for confirmation:** `/sinput abc123 y`
• **Multiple scripts running:** `/sinput script1 input1` then `/sinput script2 input2`
• **Use PID instead:** `/pinput 1234 myinput`
• **Global terminal:** `/terminal` then type commands normally
• **Terminal password:** `/enter systempassword`

**🚨 Key Improvements:**
• Script input works independently from terminal mode
• Enhanced Start button reliability
• Support for multiple interactive scripts
• Enhanced process monitoring and input handling
• All data persists across bot restarts

**🎯 Perfect for:**
• Interactive Python scripts
• Shell scripts requiring user input
• Node.js applications with prompts
• Multiple concurrent script management
• System administration tasks
            """
            await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            try:
                await update.message.reply_text(f"❌ Error occurred: {str(e)}")
            except:
                pass

    async def server_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get comprehensive server status"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            status_parts = []
            
            # System metrics with error handling
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                status_parts.append(f"• CPU: {cpu_percent}% usage")
            except Exception as e:
                status_parts.append(f"• CPU: Unable to read ({str(e)[:30]}...)")
            
            try:
                memory = psutil.virtual_memory()
                status_parts.append(f"• Memory: {memory.percent}% ({memory.used // (1024**3)}GB / {memory.total // (1024**3)}GB)")
            except Exception as e:
                status_parts.append(f"• Memory: Unable to read ({str(e)[:30]}...)")
            
            try:
                disk = psutil.disk_usage('/')
                status_parts.append(f"• Disk: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)")
            except Exception as e:
                status_parts.append(f"• Disk: Unable to read ({str(e)[:30]}...)")
                
            try:
                boot_time = datetime.fromtimestamp(psutil.boot_time())
                boot_time_str = boot_time.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                boot_time_str = "Unable to read"
            
            # Running scripts count
            try:
                running_scripts = len([s for s in self.script_manager.list_scripts() if s['status'] == 'running'])
                total_scripts = len(self.script_manager.scripts)
                scripts_with_input = len(self.script_manager.script_stdin_pipes)
            except Exception:
                running_scripts = 0
                total_scripts = 0
                scripts_with_input = 0
            
            # Active terminal sessions
            active_terminals = len(self.script_manager.interactive_processes)
            
            # System info with error handling
            try:
                system_info = {
                    'platform': platform.system(),
                    'release': platform.release(),
                    'architecture': platform.machine(),
                }
            except Exception:
                system_info = {
                    'platform': 'Unknown',
                    'release': 'Unknown', 
                    'architecture': 'Unknown'
                }
            
            # Network interfaces with error handling
            try:
                network_info = psutil.net_io_counters()
                network_sent = network_info.bytes_sent // (1024**2)
                network_recv = network_info.bytes_recv // (1024**2)
            except Exception:
                network_sent = 0
                network_recv = 0
            
            status_text = f"""📊 Enhanced Server Status

🖥️ System:
• OS: {system_info['platform']} {system_info['release']}
• Architecture: {system_info['architecture']}
• Boot Time: {boot_time_str}

⚡ Performance:
{chr(10).join(status_parts)}

🔄 Scripts Status:
• Running: {running_scripts}/{total_scripts}
• Interactive Ready: {scripts_with_input}
• Total Managed: {total_scripts}

🖥️ Terminal Sessions:
• Active Interactive: {active_terminals}

🌐 Network:
• Bytes Sent: {network_sent}MB
• Bytes Received: {network_recv}MB

🔋 Health: 🟢 Enhanced & Operational"""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="server_status")],
                [InlineKeyboardButton("📂 Scripts", callback_data="list_scripts")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(status_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in server_status: {e}")
            try:
                await update.message.reply_text(f"❌ Error getting server status: {str(e)}")
            except:
                pass

    async def list_scripts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all managed scripts"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            scripts = self.script_manager.list_scripts()
            
            if not scripts:
                keyboard = [[InlineKeyboardButton("📤 Upload Script", callback_data="upload_help")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    "📂 No scripts found\n\nUpload a .py, .sh, or .js file to get started!",
                    reply_markup=reply_markup
                )
                return
            
            text = "📂 Your Enhanced Scripts:\n\n"
            keyboard = []
            
            for script in sorted(scripts, key=lambda x: x['created_at'], reverse=True):
                status_emoji = "🟢" if script['status'] == 'running' else "🔴"
                auto_restart_emoji = "🔄" if script.get('auto_restart', False) else ""
                input_ready_emoji = "🎯" if script['id'] in self.script_manager.script_stdin_pipes else ""
                
                text += f"{status_emoji} {script['original_name']} {auto_restart_emoji}{input_ready_emoji}\n"
                text += f"   • Type: {script['script_type']}\n"
                text += f"   • Status: {script['status']}\n"
                if script.get('pid'):
                    text += f"   • PID: {script['pid']}\n"
                text += f"   • ID: {script['id']}\n"
                if input_ready_emoji:
                    text += f"   • Input Ready: `/sinput {script['id']} <text>`\n"
                text += "\n"
                
                # Create buttons for each script
                keyboard.append([
                    InlineKeyboardButton(f"⚙️ {script['original_name'][:15]}", 
                                       callback_data=f"manage_{script['id']}")
                ])
            
            # Add legend
            text += "🎯 = Input Ready | 🔄 = Auto-restart | 🟢 = Running\n"
            
            # Add general buttons
            keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="list_scripts")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in list_scripts: {e}")
            try:
                await update.message.reply_text(f"❌ Error listing scripts: {str(e)}")
            except:
                pass

    async def export_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create and send manual backup"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            processing_msg = await update.message.reply_text("🔄 Creating backup...")
            
            success, message, backup_path = self.script_manager.create_backup(is_automatic=False)
            
            if success and backup_path:
                await processing_msg.edit_text("✅ Backup created! Now uploading...")
                try:
                    await update.message.reply_document(
                        document=open(backup_path, 'rb'),
                        caption=f"Here is your backup file.\n\n{message}"
                    )
                    await processing_msg.delete()
                except Exception as e:
                    await processing_msg.edit_text(f"❌ Failed to upload backup: {e}")
                finally:
                    # Clean up the local file after sending
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
            else:
                await processing_msg.edit_text(f"❌ Backup failed: {message}")
                
        except Exception as e:
            logger.error(f"Error creating manual backup: {e}")
            await update.message.reply_text(f"❌ Error creating backup: {str(e)}")


    async def toggle_terminal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle enhanced interactive terminal mode"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            user_id = update.effective_user.id
            
            if user_id in self.script_manager.terminal_sessions:
                # Stop interactive terminal
                self.script_manager.stop_interactive_terminal(user_id)
                del self.script_manager.terminal_sessions[user_id]
                
                await update.message.reply_text(
                    "🖥️ **Interactive Terminal Disabled**\n\n"
                    "✅ Terminal session ended\n"
                    "🔙 Back to normal bot mode\n\n"
                    "💡 Script input commands still available:\n"
                    "• `/sinput <script_id> <text>`\n"
                    "• `/pinput <pid> <text>`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Start interactive terminal
                success, message = self.script_manager.start_interactive_terminal(user_id)
                
                if success:
                    self.script_manager.terminal_sessions[user_id] = {
                        'enabled': True,
                        'started_at': datetime.now().isoformat()
                    }
                    
                    await update.message.reply_text(
                        "🖥️ Interactive Terminal Enabled\n\n"
                        "✅ Terminal session started\n"
                        "📝 Every message = shell command\n"
                        "⌨️ Input Commands Available:\n"
                        "• /enter <text> - Send input + Enter\n"
                        "• /space - Send space key\n"
                        "• /ctrl_c - Send Ctrl+C\n"
                        "• /input <text> - Send raw input\n\n"
                        "🎯 Script Input Still Works:\n"
                        "• /sinput <script_id> <text>\n"
                        "• /pinput <pid> <text>\n\n"
                        "🚨 Enhanced: No more freezing issues!\n"
                        "Type /terminal again to disable."
                    )
                else:
                    await update.message.reply_text(f"❌ Failed to start terminal: {message}")
                
        except Exception as e:
            logger.error(f"Error in toggle_terminal: {e}")
            try:
                await update.message.reply_text(f"❌ Error toggling terminal: {str(e)}")
            except:
                pass

    async def execute_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute a shell command - ENHANCED NON-FREEZING VERSION"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            if not context.args:
                await update.message.reply_text("❌ Please provide a command. Example: `/cmd ls -la`")
                return
            
            command = ' '.join(context.args)
            await self.run_shell_command_safe(update, command)
            
        except Exception as e:
            logger.error(f"Error in execute_command: {e}")
            try:
                await update.message.reply_text(f"❌ Error executing command: {str(e)}")
            except:
                pass

    async def run_shell_command_safe(self, update: Update, command: str):
        """Run a shell command safely with timeout and proper output escaping."""
        try:
            processing_msg = await update.message.reply_text(f"🔄 Executing: `{command}`", parse_mode=ParseMode.MARKDOWN_V2)

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                await processing_msg.edit_text(f"⏰ Command timed out: `{command}`", parse_mode=ParseMode.MARKDOWN_V2)
                return

            output = ""
            if stdout:
                output += stdout.decode('utf-8', errors='ignore')
            if stderr:
                output += f"\n--- STDERR ---\n{stderr.decode('utf-8', errors='ignore')}"

            if not output.strip():
                output = "Command executed successfully (no output)."

            # Escape special characters for MarkdownV2
            def escape_markdown(text: str) -> str:
                escape_chars = r'_*[]()~`>#+-=|{}.!'
                return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

            response_text = f"*Command:* `{command}`\n"
            response_text += f"*Exit Code:* `{process.returncode}`\n\n"

            # Truncate output if too long
            if len(output) > 3800:
                output = output[:3800] + "\n\n... (output truncated)"

            # Send as code block
            response_text += f"```\n{escape_markdown(output)}\n```"
            
            try:
                await processing_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                # If markdown fails, send as plain text
                logger.warning(f"Markdown send failed, sending as plain text. Error: {e}")
                await processing_msg.edit_text(f"Command: {command}\nExit Code: {process.returncode}\n\n{output}")

        except Exception as e:
            logger.error(f"Error in run_shell_command_safe: {e}")
            await update.message.reply_text(f"❌ Command execution failed: {str(e)}")

    async def list_processes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List running processes"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            processes = []
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    try:
                        proc_info = proc.info
                        if proc_info['cpu_percent'] > 0 or proc_info['memory_percent'] > 0.1:
                            processes.append(proc_info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
            except Exception as e:
                await update.message.reply_text(f"❌ Error accessing process list: {str(e)}")
                return
            
            # Sort by CPU usage
            processes.sort(key=lambda x: x.get('cpu_percent', 0), reverse=True)
            processes = processes[:20]  # Top 20
            
            if not processes:
                text = "🔄 No active processes found\n\nThis may be due to system permission restrictions."
            else:
                text = "🔄 Top Running Processes:\n\n"
                for proc in processes:
                    cpu = proc.get('cpu_percent', 0)
                    mem = proc.get('memory_percent', 0)
                    name = proc.get('name', 'Unknown')
                    pid = proc.get('pid', 'Unknown')
                    text += f"• PID {pid}: {name}\n"
                    text += f"  CPU: {cpu:.1f}% | RAM: {mem:.1f}%\n\n"
            
            keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="list_processes")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in list_processes: {e}")
            try:
                await update.message.reply_text(f"❌ Error listing processes: {str(e)}")
            except:
                pass

    async def kill_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kill a process by PID"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            if not context.args:
                await update.message.reply_text("❌ Please provide a PID. Example: `/kill 1234`")
                return
            
            try:
                pid = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ Invalid PID. Please provide a number.")
                return
            
            try:
                process = psutil.Process(pid)
                process_name = process.name()
                
                process.terminate()
                await update.message.reply_text(f"✅ Process killed: {process_name} (PID: {pid})")
                
            except psutil.NoSuchProcess:
                await update.message.reply_text("❌ Process not found.")
            except psutil.AccessDenied:
                await update.message.reply_text("❌ Access denied. Cannot kill this process (insufficient permissions).")
            except psutil.ZombieProcess:
                await update.message.reply_text("❌ Cannot kill zombie process.")
            except Exception as e:
                await update.message.reply_text(f"❌ Error killing process: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error in kill_process: {e}")
            await update.message.reply_text(f"❌ Error killing process: {str(e)}")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file uploads - ENHANCED to fix Start button issues and backup import"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return

            # Send initial processing message
            processing_msg = await update.message.reply_text("📤 Processing your file...")
            
            file = await update.message.document.get_file()
            file_name = update.message.document.file_name
            
            # Determine script type
            if file_name.endswith('.py'):
                script_type = 'python'
            elif file_name.endswith('.sh'):
                script_type = 'shell'
            elif file_name.endswith('.js'):
                script_type = 'javascript'
            else:
                await processing_msg.edit_text(
                    "❌ Unsupported file type\n\n"
                    "Supported types: .py (Python), .sh (Shell), .js (Node.js)\n"
                    "For backup import, use /import command first"
                )
                return
            
            # Update processing message
            await processing_msg.edit_text("⬇️ Downloading file...")
            
            # Create temp directory if it doesn't exist
            temp_dir = os.path.abspath("temp_uploads")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Download file to temp directory in current path
            temp_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}_{file_name}")
            await file.download_to_drive(temp_path)
            
            # Set proper permissions
            os.chmod(temp_path, 0o755)
            
            # Update processing message
            await processing_msg.edit_text("⚙️ Setting up script...")
            
            # Add to script manager - ENHANCED ERROR HANDLING
            try:
                script_id = self.script_manager.add_script(temp_path, file_name, script_type)
            except Exception as e:
                # Clean up temp file if script addition fails
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except:
                    pass
                await processing_msg.edit_text(f"❌ **Script setup failed:** {str(e)}", parse_mode=ParseMode.MARKDOWN)
                return
            
            # ENHANCED: Immediately test script availability
            script_info = self.script_manager.scripts.get(script_id)
            if not script_info or not os.path.exists(script_info['file_path']):
                await processing_msg.edit_text("❌ **Script file validation failed**", parse_mode=ParseMode.MARKDOWN)
                return
            
            # Create management keyboard
            keyboard = [
                [InlineKeyboardButton("▶️ Start", callback_data=f"start_{script_id}")],
                [InlineKeyboardButton("⚙️ Manage", callback_data=f"manage_{script_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            success_text = f"""✅ Script uploaded successfully!

📄 File: {file_name}
🆔 ID: {script_id}
🔧 Type: {script_type}
📁 Location: {SCRIPTS_DIR}
🎯 Input Ready: `/sinput {script_id} <text>`

Ready to run! 🚀"""
            
            await processing_msg.edit_text(success_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling document: {e}")
            try:
                if 'processing_msg' in locals():
                    await processing_msg.edit_text(f"❌ **Upload failed:** {str(e)}", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text(f"❌ **Upload failed:** {str(e)}", parse_mode=ParseMode.MARKDOWN)
            except:
                pass


    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages - ENHANCED TERMINAL MODE"""
        try:
            if not self.is_admin(update.effective_user.id):
                await self.unauthorized_response(update)
                return
            
            user_id = update.effective_user.id
            
            # Check if in terminal mode
            if user_id in self.script_manager.terminal_sessions:
                command = update.message.text.strip()
                if command:
                    # Send command to interactive terminal
                    success, message = self.script_manager.send_input_to_terminal(user_id, command, add_newline=True)
                    
                    if success:
                        # Wait for output
                        await asyncio.sleep(0.5)
                        output = self.script_manager.read_terminal_output(user_id, timeout=3.0)
                        
                        if output and output != "No output received":
                            # Truncate if too long
                            if len(output) > 4000:
                                output = output[:4000] + "\n\n... (output truncated)"
                            
                            await update.message.reply_text(f"```\n{output}\n```", parse_mode=ParseMode.MARKDOWN)
                        else:
                            # No immediate output, acknowledge command
                            await update.message.reply_text(f"📝 Command sent: {command}")
                    else:
                        await update.message.reply_text(f"❌ Terminal error: {message}")
                        # Terminal might have died, restart it
                        if "session has ended" in message.lower():
                            success, restart_msg = self.script_manager.start_interactive_terminal(user_id)
                            if success:
                                await update.message.reply_text("🔄 Terminal session restarted automatically")
                            else:
                                await update.message.reply_text("❌ Failed to restart terminal session")
                    
        except Exception as e:
            logger.error(f"Error in handle_text: {e}")
            try:
                await update.message.reply_text(f"❌ Error handling message: {str(e)}")
            except:
                pass

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        try:
            query = update.callback_query
            await query.answer()
            
            if not self.is_admin(query.from_user.id):
                await query.edit_message_text("🚫 **ACCESS DENIED**\n\nUnauthorized access attempt logged.")
                return
            
            data = query.data
            
            if data == "list_scripts":
                await self.list_scripts_callback(query, context)
            elif data == "server_status":
                await self.server_status_callback(query, context)
            elif data == "toggle_terminal":
                await self.toggle_terminal_callback(query, context)
            elif data == "list_processes":
                await self.list_processes_callback(query, context)
            elif data == "export_backup":
                await self.export_backup_callback(query, context)
            elif data == "backup_menu":
                await self.backup_menu_callback(query, context)
            elif data.startswith("manage_"):
                script_id = data.split("_", 1)[1]
                await self.script_management_menu(query, script_id)
            elif data.startswith("start_"):
                script_id = data.split("_", 1)[1]
                await self.start_script_callback(query, script_id)
            elif data.startswith("stop_"):
                script_id = data.split("_", 1)[1]
                await self.stop_script_callback(query, script_id)
            elif data.startswith("restart_"):
                script_id = data.split("_", 1)[1]
                await self.restart_script_callback(query, script_id)
            elif data.startswith("logs_"):
                script_id = data.split("_", 1)[1]
                await self.show_logs_callback(query, script_id)
            elif data.startswith("toggle_auto_"):
                script_id = data.split("_", 2)[2]
                await self.toggle_auto_restart_callback(query, script_id)
            elif data.startswith("delete_"):
                script_id = data.split("_", 1)[1]
                await self.delete_script_callback(query, script_id)
            elif data == "upload_help":
                await self.upload_help_callback(query, context)
            elif data == "main_menu":
                await self.main_menu_callback(query, context)
                
        except Exception as e:
            logger.error(f"Error in button callback: {e}")

    async def upload_help_callback(self, query, context):
        """Upload help callback"""
        try:
            help_text = """
📤 **How to Upload Scripts**

1. **Supported File Types:**
   • `.py` - Python scripts
   • `.sh` - Shell/Bash scripts  
   • `.js` - JavaScript/Node.js scripts

2. **Upload Process:**
   • Send file as attachment
   • Bot will auto-detect script type
   • Get instant management buttons
   • Start/stop with one click

3. **Enhanced Features:**
   • Auto-restart on crash
   • Real-time logs
   • Background execution
   • **Script-specific input support**
   • Process monitoring

4. **Interactive Script Support:**
   • Upload interactive scripts
   • Use `/sinput <script_id> <input>` for passwords/prompts
   • Multiple scripts can run simultaneously
   • Independent from global terminal mode

📎 **Ready to upload?** Just send your script file!
            """
            
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="list_scripts")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(help_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in upload_help_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def main_menu_callback(self, query, context):
        """Main menu callback"""
        try:
            welcome_text = """
🤖 **Enhanced Advanced Hosting Management Bot**

Your enhanced server management dashboard:

🔧 **Quick Actions:**
• Manage your scripts with input support
• Check server status  
• Access interactive terminal mode
• Monitor processes

🎯 **Features:**
• Script-specific input commands
• Enhanced Start button reliability
• Multi-script interaction support

🔒 **Security:** Admin-only access active

Choose an option below to get started:
            """
            
            keyboard = [
                [InlineKeyboardButton("📂 My Scripts", callback_data="list_scripts")],
                [InlineKeyboardButton("📊 Server Status", callback_data="server_status")],
                [InlineKeyboardButton("🖥️ Terminal Mode", callback_data="toggle_terminal")],
                [InlineKeyboardButton("📦 Backup Menu", callback_data="backup_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(welcome_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in main_menu_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def backup_menu_callback(self, query, context):
        """Show backup management menu"""
        try:
            menu_text = """📦 **Backup Management**

🔧 **Available Options:**
• Export current bot data to a local backup file.
• Use `/importlink <url>` to restore from a backup.

⚠️ **Important Notes:**
• Restoring from a backup will replace ALL current data.
• A backup of the current state is created before restoration.

Choose an option below:"""
            
            keyboard = [
                [InlineKeyboardButton("📤 Export Backup", callback_data="export_backup")],
                [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(menu_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Error in backup_menu_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def script_management_menu(self, query, script_id: str):
        """Show script management menu - ENHANCED"""
        try:
            scripts = self.script_manager.list_scripts()
            script = next((s for s in scripts if s['id'] == script_id), None)
            
            if not script:
                await query.edit_message_text("❌ Script not found")
                return
            
            status_emoji = "🟢 Running" if script['status'] == 'running' else "🔴 Stopped"
            auto_restart_status = "🔄 Enabled" if script.get('auto_restart', False) else "❌ Disabled"
            input_ready = "🎯 Ready" if script_id in self.script_manager.script_stdin_pipes else "❌ Not Available"
            
            text = f"""
⚙️ Enhanced Script Management

📄 Name: {script['original_name']}
🆔 ID: {script['id']}
🔧 Type: {script['script_type']}
📊 Status: {status_emoji}
🔄 Auto-restart: {auto_restart_status}
🎯 Input Ready: {input_ready}
📈 Restarts: {script.get('restart_count', 0)}
            """
            
            if script.get('last_started'):
                text += f"\n🕐 Last Started: {script['last_started'][:19]}"
            
            if script.get('pid'):
                text += f"\n🔢 PID: {script['pid']}"
            
            # Enhanced input instructions
            if script_id in self.script_manager.script_stdin_pipes:
                text += f"\n\n💡 Send Input:\n• `/sinput {script_id} <text>`\n• `/pinput {script.get('pid', 'N/A')} <text>`"
            
            keyboard = []
            
            if script['status'] == 'running':
                keyboard.append([InlineKeyboardButton("⏹️ Stop", callback_data=f"stop_{script_id}")])
                keyboard.append([InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{script_id}")])
            else:
                keyboard.append([InlineKeyboardButton("▶️ Start", callback_data=f"start_{script_id}")])
            
            keyboard.append([InlineKeyboardButton("📋 View Logs", callback_data=f"logs_{script_id}")])
            
            auto_text = "Disable Auto-restart" if script.get('auto_restart', False) else "Enable Auto-restart"
            keyboard.append([InlineKeyboardButton(f"🔄 {auto_text}", callback_data=f"toggle_auto_{script_id}")])
            
            keyboard.append([InlineKeyboardButton("🗑️ Delete Script", callback_data=f"delete_{script_id}")])
            keyboard.append([InlineKeyboardButton("🔙 Back to Scripts", callback_data="list_scripts")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in script_management_menu: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def start_script_callback(self, query, script_id: str):
        """Start script callback - ENHANCED to fix Start button issues"""
        try:
            # Show immediate feedback
            await query.edit_message_text("🚀 Starting script...")
            
            # Validate script exists before attempting to start
            if script_id not in self.script_manager.scripts:
                await query.edit_message_text("❌ Script not found. Please refresh and try again.")
                return
            
            script_info = self.script_manager.scripts[script_id]
            if not os.path.exists(script_info['file_path']):
                await query.edit_message_text(f"❌ Script file missing: {script_info['file_path']}")
                return
            
            # Attempt to start the script
            success, message = self.script_manager.start_script(script_id)
            status_emoji = "✅" if success else "❌"
            
            # Show result message
            result_text = f"{status_emoji} {message}"
            if success:
                result_text += f"\n\n🎯 Input ready: `/sinput {script_id} <text>`"
            
            await query.edit_message_text(result_text)
            
            # Show management menu after 3 seconds
            await asyncio.sleep(3)
            await self.script_management_menu(query, script_id)
            
        except Exception as e:
            logger.error(f"Error in start_script_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Start failed: {str(e)}")
                # Still try to show management menu after error
                await asyncio.sleep(2)
                await self.script_management_menu(query, script_id)
            except:
                pass

    async def stop_script_callback(self, query, script_id: str):
        """Stop script callback"""
        try:
            await query.edit_message_text("⏹️ Stopping script...")
            
            success, message = self.script_manager.stop_script(script_id)
            status_emoji = "✅" if success else "❌"
            
            await query.edit_message_text(f"{status_emoji} {message}")
            
            # Show management menu after 2 seconds
            await asyncio.sleep(2)
            await self.script_management_menu(query, script_id)
            
        except Exception as e:
            logger.error(f"Error in stop_script_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def restart_script_callback(self, query, script_id: str):
        """Restart script callback"""
        try:
            await query.edit_message_text("🔄 Restarting script...")
            
            success, message = self.script_manager.restart_script(script_id)
            status_emoji = "✅" if success else "❌"
            
            result_text = f"{status_emoji} {message}"
            if success:
                result_text += f"\n\n🎯 Input ready: `/sinput {script_id} <text>`"
            
            await query.edit_message_text(result_text)
            
            # Show management menu after 3 seconds
            await asyncio.sleep(3)
            await self.script_management_menu(query, script_id)
            
        except Exception as e:
            logger.error(f"Error in restart_script_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def show_logs_callback(self, query, script_id: str):
        """Show script logs"""
        try:
            logs = self.script_manager.get_script_logs(script_id)
            
            if len(logs) > 4000:
                logs = logs[-4000:] + "\n\n... (truncated)"
            
            script = next((s for s in self.script_manager.list_scripts() if s['id'] == script_id), None)
            script_name = script['original_name'] if script else script_id
            
            text = f"📋 Logs for {script_name}\n\n```\n{logs}\n```"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Logs", callback_data=f"logs_{script_id}")],
                [InlineKeyboardButton("🔙 Back to Management", callback_data=f"manage_{script_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Error in show_logs_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def toggle_auto_restart_callback(self, query, script_id: str):
        """Toggle auto-restart callback"""
        try:
            success, message = self.script_manager.toggle_auto_restart(script_id)
            status_emoji = "✅" if success else "❌"
            
            await query.edit_message_text(f"{status_emoji} {message}")
            
            # Show management menu after 1 second
            await asyncio.sleep(1)
            await self.script_management_menu(query, script_id)
            
        except Exception as e:
            logger.error(f"Error in toggle_auto_restart_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def delete_script_callback(self, query, script_id: str):
        """Delete script callback"""
        try:
            await query.edit_message_text("🗑️ Deleting script...")
            
            success, message = self.script_manager.delete_script(script_id)
            status_emoji = "✅" if success else "❌"
            
            await query.edit_message_text(f"{status_emoji} {message}")
            
            # Go back to scripts list after 2 seconds
            await asyncio.sleep(2)
            await self.list_scripts_callback(query, None)
            
        except Exception as e:
            logger.error(f"Error in delete_script_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def list_scripts_callback(self, query, context):
        """List scripts callback"""
        try:
            scripts = self.script_manager.list_scripts()
            
            if not scripts:
                text = "📂 No scripts found\n\nUpload a .py, .sh, or .js file to get started!"
                keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
            else:
                text = "📂 Your Enhanced Scripts:\n\n"
                keyboard = []
                
                for script in sorted(scripts, key=lambda x: x['created_at'], reverse=True):
                    status_emoji = "🟢" if script['status'] == 'running' else "🔴"
                    auto_restart_emoji = "🔄" if script.get('auto_restart', False) else ""
                    input_ready_emoji = "🎯" if script['id'] in self.script_manager.script_stdin_pipes else ""
                    
                    text += f"{status_emoji} {script['original_name']} {auto_restart_emoji}{input_ready_emoji}\n"
                    text += f"   • Status: {script['status']}\n"
                    text += f"   • Type: {script['script_type']}\n"
                    if input_ready_emoji:
                        text += f"   • Input: `/sinput {script['id']} <text>`\n"
                    text += "\n"
                    
                    keyboard.append([
                        InlineKeyboardButton(f"⚙️ {script['original_name'][:15]}", 
                                           callback_data=f"manage_{script['id']}")
                    ])
                
                text += "🎯 = Input Ready | 🔄 = Auto-restart | 🟢 = Running\n"
                keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="list_scripts")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in list_scripts_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def server_status_callback(self, query, context):
        """Server status callback"""
        try:
            status_parts = []
            
            # System metrics with error handling
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                status_parts.append(f"• CPU: {cpu_percent}%")
            except Exception:
                status_parts.append("• CPU: Unable to read")
            
            try:
                memory = psutil.virtual_memory()
                status_parts.append(f"• Memory: {memory.percent}% ({memory.used // (1024**3)}GB / {memory.total // (1024**3)}GB)")
            except Exception:
                status_parts.append("• Memory: Unable to read")
            
            try:
                disk = psutil.disk_usage('/')
                status_parts.append(f"• Disk: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)")
            except Exception:
                status_parts.append("• Disk: Unable to read")
                
            try:
                running_scripts = len([s for s in self.script_manager.list_scripts() if s['status'] == 'running'])
                total_scripts = len(self.script_manager.scripts)
                scripts_with_input = len(self.script_manager.script_stdin_pipes)
            except Exception:
                running_scripts = 0
                total_scripts = 0
                scripts_with_input = 0
            
            active_terminals = len(self.script_manager.interactive_processes)
            
            status_text = f"""📊 Enhanced Server Status

⚡ Performance:
{chr(10).join(status_parts)}

🔄 Scripts Status:
• Running: {running_scripts}/{total_scripts}
• Interactive Ready: {scripts_with_input}
• Total Managed: {total_scripts}

🖥️ Terminal Sessions:
• Active Interactive: {active_terminals}

🔋 Health: 🟢 Enhanced & Operational"""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="server_status")],
                [InlineKeyboardButton("📂 Scripts", callback_data="list_scripts")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(status_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in server_status_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def toggle_terminal_callback(self, query, context):
        """Toggle terminal callback"""
        try:
            user_id = query.from_user.id
            
            if user_id in self.script_manager.terminal_sessions:
                # Stop interactive terminal
                self.script_manager.stop_interactive_terminal(user_id)
                del self.script_manager.terminal_sessions[user_id]
                
                await query.edit_message_text(
                    "🖥️ **Interactive Terminal Disabled**\n\n"
                    "✅ Terminal session ended\n"
                    "🔙 Back to normal bot mode\n\n"
                    "💡 Script input commands still available:\n"
                    "• `/sinput <script_id> <text>`\n"
                    "• `/pinput <pid> <text>`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Start interactive terminal
                success, message = self.script_manager.start_interactive_terminal(user_id)
                
                if success:
                    self.script_manager.terminal_sessions[user_id] = {
                        'enabled': True,
                        'started_at': datetime.now().isoformat()
                    }
                    
                    await query.edit_message_text(
                        "🖥️ Interactive Terminal Enabled\n\n"
                        "✅ Terminal session started\n"
                        "📝 Every message = shell command\n"
                        "⌨️ Input Commands Available:\n"
                        "• /enter <text> - Send input + Enter\n"
                        "• /space - Send space key\n"
                        "• /ctrl_c - Send Ctrl+C\n"
                        "• /input <text> - Send raw input\n\n"
                        "🎯 Script Input Still Works:\n"
                        "• /sinput <script_id> <text>\n"
                        "• /pinput <pid> <text>\n\n"
                        "🚨 Enhanced: No more freezing issues!\n"
                        "Type /terminal again to disable."
                    )
                else:
                    await query.edit_message_text(f"❌ Failed to start terminal: {message}")
                
        except Exception as e:
            logger.error(f"Error in toggle_terminal_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def list_processes_callback(self, query, context):
        """List processes callback"""
        try:
            processes = []
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    try:
                        proc_info = proc.info
                        if proc_info['cpu_percent'] > 0 or proc_info['memory_percent'] > 0.1:
                            processes.append(proc_info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
            except Exception as e:
                await query.edit_message_text(f"❌ Error accessing process list: {str(e)}")
                return
            
            # Sort by CPU usage
            processes.sort(key=lambda x: x.get('cpu_percent', 0), reverse=True)
            processes = processes[:20]  # Top 20
            
            if not processes:
                text = "🔄 No active processes found\n\nThis may be due to system permission restrictions."
            else:
                text = "🔄 Top Running Processes:\n\n"
                for proc in processes:
                    cpu = proc.get('cpu_percent', 0)
                    mem = proc.get('memory_percent', 0)
                    name = proc.get('name', 'Unknown')
                    pid = proc.get('pid', 'Unknown')
                    text += f"• PID {pid}: {name}\n"
                    text += f"  CPU: {cpu:.1f}% | RAM: {mem:.1f}%\n\n"
            
            keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="list_processes")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in list_processes_callback: {e}")
            try:
                await query.edit_message_text(f"❌ Error: {str(e)}")
            except:
                pass

    async def export_backup_callback(self, query, context):
        """Export backup callback"""
        try:
            await query.edit_message_text("🔄 Creating backup...")
            
            success, message, backup_path = self.script_manager.create_backup(is_automatic=False)
            
            if success and backup_path:
                await query.edit_message_text("✅ Backup created! Now uploading...")
                try:
                    await query.message.reply_document(
                        document=open(backup_path, 'rb'),
                        caption=f"Here is your backup file.\n\n{message}"
                    )
                    await query.delete_message()
                except Exception as e:
                    await query.edit_message_text(f"❌ Failed to upload backup: {e}")
                finally:
                    # Clean up the local file after sending
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
            else:
                await query.edit_message_text(f"❌ Backup failed: {message}")
                
        except Exception as e:
            logger.error(f"Error in export_backup_callback: {e}")
            await query.edit_message_text(f"❌ An error occurred: {e}")


    def run(self):
        """Run the bot"""
        try:
            # Create application
            self.application = Application.builder().token(BOT_TOKEN).build()
            
            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("status", self.server_status))
            self.application.add_handler(CommandHandler("scripts", self.list_scripts))
            self.application.add_handler(CommandHandler("cmd", self.execute_command))
            self.application.add_handler(CommandHandler("ps", self.list_processes))
            self.application.add_handler(CommandHandler("kill", self.kill_process))
            self.application.add_handler(CommandHandler("sinput", self.send_script_input))
            self.application.add_handler(CommandHandler("pinput", self.send_pid_input))
            self.application.add_handler(CommandHandler("enter", self.send_enter_input))
            self.application.add_handler(CommandHandler("space", self.send_space))
            self.application.add_handler(CommandHandler("ctrl_c", self.send_ctrl_c))
            self.application.add_handler(CommandHandler("input", self.send_raw_input))
            self.application.add_handler(CommandHandler("terminal", self.toggle_terminal))
            self.application.add_handler(CommandHandler("export", self.export_backup))
            self.application.add_handler(CommandHandler("importlink", self.import_from_link))
            self.application.add_handler(CommandHandler("test", self.test_command))
            self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
            self.application.add_handler(CallbackQueryHandler(self.button_callback))
            
            logger.info("🚀 Enhanced Advanced Hosting Bot Started!")
            
            # Run the bot
            self.application.run_polling(drop_pending_updates=True)
            
        except Exception as e:
            logger.error(f"❌ Error starting bot: {e}")

def main():
    """Main function"""
    try:
        # Handle shutdown gracefully
        def signal_handler(signum, frame):
            logger.info("🛑 Received shutdown signal")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start the bot
        bot = TelegramBot()
        bot.run()
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()