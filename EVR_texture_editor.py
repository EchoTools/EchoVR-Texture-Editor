import os
import sys
import struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import shutil
import tempfile
import subprocess
import threading
import json
import glob
import time
import zipfile
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    messagebox.showerror("Missing Dependencies", "Pillow library is required but not installed.\nPlease install it manually: pip install Pillow")
    sys.exit(1)

# --- SETTINGS & PATH MANAGEMENT ---
SETTINGS_DIR_NAME = "Settings"

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_settings_path(filename):
    base = get_base_dir()
    settings_dir = os.path.join(base, SETTINGS_DIR_NAME)
    if not os.path.exists(settings_dir):
        try:
            os.makedirs(settings_dir)
        except: pass
    return os.path.join(settings_dir, filename)

def get_tool_path(tool_name):
    # Check Settings folder first
    settings_path = get_settings_path(tool_name)
    if os.path.exists(settings_path):
        return settings_path
    
    # Fallback to script dir
    script_path = os.path.join(get_base_dir(), tool_name)
    if os.path.exists(script_path):
        return script_path
        
    return settings_path

CONFIG_FILE = get_settings_path("config.json")
CACHE_DIR = "texture_cache" 
CACHE2_FILE = get_settings_path("cache2.json")
LEGACY_CACHE_FILE = get_settings_path("cache.json")
MAPPING_FILE = get_settings_path("texture_mapping.json")

DECODE_CACHE = {}

def run_hidden_command(cmd, cwd=None, timeout=None, capture_output=True):
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        if capture_output:
            try:
                result = subprocess.run(
                    cmd, 
                    startupinfo=startupinfo,
                    capture_output=True, 
                    text=True, 
                    cwd=cwd,
                    timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return result
            except subprocess.TimeoutExpired:
                return subprocess.CompletedProcess(cmd, -1, "", "Timeout expired")
            except Exception:
                return subprocess.CompletedProcess(cmd, -1, "", "Command failed")
        else:
            try:
                result = subprocess.run(
                    cmd, 
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=cwd,
                    timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return result
            except:
                return subprocess.CompletedProcess(cmd, -1)
    else:
        if capture_output:
            return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        else:
            return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd, timeout=timeout)

# --- CACHE MANAGER ---
class TextureCacheManager:
    @staticmethod
    def load_cache():
        if os.path.exists(CACHE2_FILE):
            try:
                with open(CACHE2_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    @staticmethod
    def save_cache(cache_data):
        try:
            with open(CACHE2_FILE, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def get_cached_files(folder_path):
        cache = TextureCacheManager.load_cache()
        return cache.get(folder_path)

    @staticmethod
    def update_cache(folder_path, file_list):
        cache = TextureCacheManager.load_cache()
        cache[folder_path] = file_list
        TextureCacheManager.save_cache(cache)

class ConfigManager:
    @staticmethod
    def load_config():
        base_dir = get_base_dir()
        
        default_config = {
            'output_folder': None,
            'data_folder': None,
            'extracted_folder': None,
            'repacked_folder': os.path.join(base_dir, "output-both"),
            'pcvr_input_folder': os.path.join(base_dir, "input-pcvr"),
            'quest_input_folder': os.path.join(base_dir, "input-quest"),
            'backup_folder': None,
            'renderdoc_path': None
        }
        
        parent_dir = os.path.dirname(base_dir)
        for folder_key in ['repacked_folder', 'pcvr_input_folder', 'quest_input_folder']:
            if not os.path.exists(default_config[folder_key]):
                parent_path = os.path.join(parent_dir, os.path.basename(default_config[folder_key]))
                if os.path.exists(parent_path):
                    default_config[folder_key] = parent_path
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    loaded_config = json.load(f)
                    for key in default_config:
                        if key in loaded_config:
                            value = loaded_config[key]
                            if value is None:
                                continue
                            if isinstance(value, str) and (key.endswith('_folder') or key.endswith('_path')):
                                value = os.path.normpath(value)
                                if not os.path.exists(value) and key in ['repacked_folder', 'pcvr_input_folder', 'quest_input_folder']:
                                    parent_path = os.path.join(os.path.dirname(value), os.path.basename(value))
                                    if os.path.exists(parent_path):
                                        value = parent_path
                            default_config[key] = value
        except Exception as e:
            print(f"Config load error: {e}")
        
        return default_config
    
    @staticmethod
    def save_config(**kwargs):
        config = ConfigManager.load_config()
        config.update(kwargs)
        
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Config save error: {e}")

class TutorialPopup:
    @staticmethod
    def show(parent):
        popup = tk.Toplevel(parent)
        popup.title("EchoVR Texture Editor - Tutorial")
        popup.geometry("800x600")
        bg_color = '#333333' 
        popup.configure(bg=bg_color)
        popup.resizable(True, True)
        
        popup.transient(parent)
        popup.grab_set()
        
        popup.update_idletasks()
        try:
            x = parent.winfo_x() + (parent.winfo_width() - popup.winfo_reqwidth()) // 2
            y = parent.winfo_y() + (parent.winfo_height() - popup.winfo_reqheight()) // 2
            popup.geometry(f"+{x}+{y}")
        except:
            pass
        
        canvas = tk.Canvas(popup, bg=bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(popup, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        content = scrollable_frame
        
        style = ttk.Style()
        style.configure("Grey.TFrame", background=bg_color)
        scrollable_frame.configure(style="Grey.TFrame")
        
        title = tk.Label(content, text="📚 EchoVR Texture Editor Tutorial", font=("Arial", 16, "bold"), fg="#ffffff", bg=bg_color)
        title.pack(pady=20)
        
        sections = [
            {
                "title": "🎯 Getting Started",
                "content": """1. First, select your EchoVR Data Folder (contains 'manifests' and 'packages' folders)
2. Select an output folder for extracted textures"""
            },
            {
                "title": "📦 Extraction Process",
                "content": """1. Click 'Extract Package' to unpack game files
2. Textures will be loaded automatically after extraction
3. PCVR textures are stored in 'pcvr-extracted' folder
4. Quest textures are stored in 'quest-extracted' folder"""
            },
            {
                "title": "🎨 Texture Replacement",
                "content": """1. Select one or more textures from the list (Hold Ctrl/Shift for multiple)
2. Click on the right canvas to choose a replacement texture
3. Click 'Replace Texture' to apply changes to ALL selected files
4. Modified files go to the corresponding input folders"""
            },
            {
                "title": "🔧 Repacking & Deployment",
                "content": """1. After making changes, click 'Repack Modified'
2. Select 'output-both' as the output folder (default)
3. For Quest: Use 'Push Files To Quest' to deploy
4. For PCVR: Use 'Update EchoVR' to deploy"""
            }
        ]
        
        for section in sections:
            section_bg = '#444444'
            frame = tk.Frame(content, bg=section_bg, relief=tk.RAISED, bd=1)
            frame.pack(fill=tk.X, padx=20, pady=10)
            
            title_label = tk.Label(frame, text=section["title"], font=("Arial", 12, "bold"), fg="#4cd964", bg=section_bg, anchor="w")
            title_label.pack(fill=tk.X, padx=10, pady=(10, 5))
            
            content_label = tk.Label(frame, text=section["content"], font=("Arial", 10), fg="#eeeeee", bg=section_bg, justify=tk.LEFT, anchor="w", wraplength=700)
            content_label.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except Exception:
                pass
        
        def on_close():
            canvas.unbind_all("<MouseWheel>")
            popup.destroy()
            
        close_btn = tk.Button(content, text="Close Tutorial", command=on_close, bg='#4a4a4a', fg='#ffffff', font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=20, pady=10)
        close_btn.pack(pady=20)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        popup.protocol("WM_DELETE_WINDOW", on_close)

class UpdateEchoPopup:
    def __init__(self, parent, app, config):
        self.parent = parent
        self.app = app
        self.config = config
        self.backup_location = None
        
        self.popup = tk.Toplevel(parent)
        self.popup.title("⚠ Update EchoVR Game Files")
        self.popup.geometry("850x500")
        self.popup.configure(bg='#1a1a1a')
        self.popup.resizable(False, False)
        
        self.popup.transient(parent)
        self.popup.grab_set()
        
        self.popup.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.popup.winfo_reqwidth()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.popup.winfo_reqheight()) // 2
        self.popup.geometry(f"+{x}+{y}")
        
        self.setup_ui()
        self.refresh_backup_status()
    
    def setup_ui(self):
        title_frame = tk.Frame(self.popup, bg='#1a1a1a')
        title_frame.pack(fill=tk.X, padx=20, pady=20)
        
        warning_icon = "⚠️"
        title_label = tk.Label(title_frame, text=f"{warning_icon} WARNING: Update EchoVR", font=("Arial", 14, "bold"), fg="#ff6b6b", bg='#1a1a1a')
        title_label.pack()
        
        warning_text = """This menu allows you to update your EchoVR installation.
Always create a backup before proceeding."""
        
        warning_label = tk.Label(self.popup, text=warning_text, font=("Arial", 11), fg="#ffffff", bg='#1a1a1a', justify=tk.CENTER, wraplength=650)
        warning_label.pack(padx=20, pady=10)
        
        data_folder = self.config.get('data_folder', 'Not selected')
        data_frame = tk.Frame(self.popup, bg='#2a2a2a', relief=tk.RAISED, bd=1)
        data_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(data_frame, text="Game Data Folder:", font=("Arial", 10, "bold"), fg="#4cd964", bg='#2a2a2a').pack(anchor="w", padx=10, pady=(10, 0))
        
        folder_label = tk.Label(data_frame, text=data_folder, font=("Arial", 9), fg="#cccccc", bg='#2a2a2a', wraplength=620, justify=tk.LEFT)
        folder_label.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_folder = self.config.get('repacked_folder', os.path.join(script_dir, "output-both"))
        output_frame = tk.Frame(self.popup, bg='#2a2a2a', relief=tk.RAISED, bd=1)
        output_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(output_frame, text="Modified Files Source:", font=("Arial", 10, "bold"), fg="#4cd964", bg='#2a2a2a').pack(anchor="w", padx=10, pady=(10, 0))
        
        output_label = tk.Label(output_frame, text=output_folder, font=("Arial", 9), fg="#cccccc", bg='#2a2a2a', wraplength=620, justify=tk.LEFT)
        output_label.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        backup_frame = tk.Frame(self.popup, bg='#1a1a1a')
        backup_frame.pack(fill=tk.X, padx=20, pady=10)
        
        btn_frame = tk.Frame(backup_frame, bg='#1a1a1a')
        btn_frame.pack(pady=10)
        
        self.create_backup_btn = tk.Button(btn_frame, text="📁 Create Backup", command=self.create_backup, bg='#4a4a4a', fg='#ffffff', font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=10)
        self.create_backup_btn.pack(side=tk.LEFT, padx=5)
        
        self.restore_backup_btn = tk.Button(btn_frame, text="🔄 Restore Backup", command=self.restore_backup, bg='#4a4a4a', fg='#ffffff', font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=10, state=tk.DISABLED)
        self.restore_backup_btn.pack(side=tk.LEFT, padx=5)

        self.update_pkg_btn = tk.Button(btn_frame, text="📦 Update Packages", command=self.start_update_thread, bg='#007aff', fg='#ffffff', font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=10)
        self.update_pkg_btn.pack(side=tk.LEFT, padx=5)
        
        self.backup_status = tk.Label(backup_frame, text="Checking backup status...", font=("Arial", 9), fg="#ffcc00", bg='#1a1a1a')
        self.backup_status.pack()
        
        close_frame = tk.Frame(self.popup, bg='#1a1a1a')
        close_frame.pack(fill=tk.X, padx=20, pady=20)
        
        self.close_btn = tk.Button(close_frame, text="Close", command=self.popup.destroy, bg='#4a4a4a', fg='#ffffff', font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=30, pady=10)
        self.close_btn.pack()
    
    def log_info(self, message):
        if hasattr(self.app, 'log_info'):
            self.app.log_info(message)
    
    def check_backup_exists(self):
        backup_folder = self.config.get('backup_folder')
        if backup_folder:
            backup_folder = os.path.normpath(backup_folder)
            if os.path.exists(backup_folder):
                self.backup_location = backup_folder
                return True
        return False
    
    def refresh_backup_status(self):
        if self.check_backup_exists():
            self.backup_status.config(text=f"✓ Backup found: {os.path.basename(self.backup_location)}", fg="#4cd964")
            self.restore_backup_btn.config(state=tk.NORMAL)
        else:
            self.backup_status.config(text="No backup found - create one before updating", fg="#ffcc00")
            self.restore_backup_btn.config(state=tk.DISABLED)
    
    def create_backup(self):
        if not self.config.get('data_folder'):
            messagebox.showerror("Error", "Please select game data folder first")
            return
        
        backup_path = filedialog.askdirectory(title="Select Backup Location", initialdir=os.path.dirname(self.config['data_folder']))
        
        if not backup_path:
            return
        
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_folder = os.path.join(backup_path, f"EchoVR_Backup_{timestamp}")
            
            self.backup_status.config(text="Creating backup...", fg="#ffcc00")
            self.popup.update_idletasks()
            
            # Run in thread to prevent freeze
            def backup_task():
                try:
                    shutil.copytree(self.config['data_folder'], backup_folder)
                    self.popup.after(0, lambda: self.on_backup_complete(True, backup_folder))
                except Exception as e:
                    self.popup.after(0, lambda: self.on_backup_complete(False, str(e)))

            threading.Thread(target=backup_task, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start backup:\n{str(e)}")

    def on_backup_complete(self, success, result):
        if success:
            ConfigManager.save_config(backup_folder=result)
            self.backup_location = result
            self.refresh_backup_status()
            self.log_info(f"✓ Backup created: {result}")
            messagebox.showinfo("Success", f"Backup created successfully at:\n{result}")
        else:
            messagebox.showerror("Error", f"Failed to create backup:\n{result}")
            self.backup_status.config(text="Backup failed", fg="#ff3b30")

    def restore_backup(self):
        if not self.backup_location or not os.path.exists(self.backup_location):
            messagebox.showerror("Error", "Backup not found")
            return
        
        confirm = messagebox.askyesno("Confirm Restore", f"Restore game files from backup?\n\nBackup: {self.backup_location}\n\nThis will OVERWRITE your current game files.")
        
        if not confirm:
            return
        
        self.backup_status.config(text="Restoring backup... (Do not close)", fg="#ffcc00")
        self.restore_backup_btn.config(state=tk.DISABLED)
        self.popup.update_idletasks()

        def restore_task():
            try:
                if os.path.exists(self.config['data_folder']):
                    shutil.rmtree(self.config['data_folder'])
                shutil.copytree(self.backup_location, self.config['data_folder'])
                self.popup.after(0, lambda: self.on_restore_complete(True, self.backup_location))
            except Exception as e:
                self.popup.after(0, lambda: self.on_restore_complete(False, str(e)))

        threading.Thread(target=restore_task, daemon=True).start()

    def on_restore_complete(self, success, result):
        if success:
            self.log_info(f"✓ Game files restored from backup: {result}")
            messagebox.showinfo("Success", "Game files restored from backup!")
            self.popup.destroy()
        else:
            messagebox.showerror("Error", f"Failed to restore backup:\n{result}")
            self.backup_status.config(text="Restore failed", fg="#ff3b30")
            self.restore_backup_btn.config(state=tk.NORMAL)

    def start_update_thread(self):
        # Validation checks
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_folder = self.config.get('repacked_folder')
        if not output_folder:
            output_folder = os.path.join(script_dir, "output-both")
        
        data_folder = self.config.get('data_folder')
        
        if not os.path.exists(output_folder):
            messagebox.showerror("Error", f"Output folder not found:\n{output_folder}\n\nPlease repack your files first.")
            return
            
        if not data_folder or not os.path.exists(data_folder):
            messagebox.showerror("Error", "Game data folder not found.\nPlease select your EchoVR data folder first.")
            return
        
        packages_path = os.path.join(output_folder, "packages")
        manifests_path = os.path.join(output_folder, "manifests")
        
        if not os.path.exists(packages_path) or not os.path.exists(manifests_path):
            messagebox.showerror("Error", f"Required folders not found in:\n{output_folder}\n\nPlease repack your files first.")
            return
        
        if not self.backup_location:
            warning_result = messagebox.askyesno("⚠ WARNING - No Backup Found", f"No backup found! This operation will OVERWRITE your game files.\n\nContinue WITHOUT a backup?")
            if not warning_result:
                return
        
        confirm = messagebox.askyesno("Update Game Files", f"This will UPDATE your EchoVR installation.\n\nSource: {output_folder}\nTarget: {data_folder}\n\nOperation:\n1. Move files from output-both to game folder\n2. Wipe output-both folder\n\nContinue?")
        
        if not confirm:
            return

        # Disable buttons
        self.update_pkg_btn.config(state=tk.DISABLED, text="Updating...")
        self.close_btn.config(state=tk.DISABLED)
        self.backup_status.config(text="Updating game files... DO NOT CLOSE", fg="#007aff")
        
        # Start Thread
        threading.Thread(target=self.update_packages_thread, args=(output_folder, data_folder), daemon=True).start()

    def update_packages_thread(self, output_folder, data_folder):
        try:
            files_moved = 0
            
            for folder in ['packages', 'manifests']:
                src_path = os.path.join(output_folder, folder)
                dst_path = os.path.join(data_folder, folder)
                
                if os.path.exists(src_path):
                    os.makedirs(dst_path, exist_ok=True)
                    
                    for filename in os.listdir(src_path):
                        src_file = os.path.join(src_path, filename)
                        dst_file = os.path.join(dst_path, filename)
                        
                        if os.path.isfile(src_file):
                            shutil.move(src_file, dst_file)
                            files_moved += 1
            
            try:
                for folder in ['packages', 'manifests']:
                    folder_path = os.path.join(output_folder, folder)
                    if os.path.exists(folder_path):
                        shutil.rmtree(folder_path)
            except Exception as wipe_error:
                self.popup.after(0, lambda: self.log_info(f"⚠ Could not completely wipe output-both: {wipe_error}"))
            
            self.popup.after(0, lambda: self.on_update_complete(True, files_moved))

        except Exception as e:
            self.popup.after(0, lambda: self.on_update_complete(False, str(e)))

    def on_update_complete(self, success, result):
        self.update_pkg_btn.config(state=tk.NORMAL, text="📦 Update Packages")
        self.close_btn.config(state=tk.NORMAL)
        
        if success:
            self.log_info(f"✓ Moved {result} files to game folder")
            self.log_info(f"✓ Wiped output-both folder")
            messagebox.showinfo("Success", f"Successfully updated game files!\n\nFiles moved: {result}")
            self.popup.destroy()
        else:
            messagebox.showerror("Error", f"Failed to update packages:\n{result}")
            self.backup_status.config(text="Update failed", fg="#ff3b30")

class ADBPlatformTools:
    @staticmethod
    def get_safe_install_directory():
        script_dir = os.path.dirname(os.path.abspath(__file__))
        install_dir = os.path.join(script_dir, "platform-tools")
        return install_dir

    @staticmethod
    def install_platform_tools():
        import platform
        system = platform.system().lower()
        
        download_urls = {
            'windows': 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip',
            'linux': 'https://dl.google.com/android/repository/platform-tools-latest-linux.zip', 
            'darwin': 'https://dl.google.com/android/repository/platform-tools-latest-darwin.zip'
        }
        
        url = download_urls.get(system)
        if not url:
            return False, f"Unsupported platform: {system}"
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        install_base = os.path.join(script_dir, "platform-tools")
        download_path = os.path.join(script_dir, "platform-tools-download.zip")
        
        try:
            os.makedirs(install_base, exist_ok=True)
            
            urllib.request.urlretrieve(url, download_path)
            
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(install_base)
            
            try:
                os.remove(download_path)
            except:
                pass
            
            adb_path = os.path.join(install_base, "platform-tools", "adb.exe" if system == 'windows' else "adb")
            if not os.path.exists(adb_path):
                adb_path = os.path.join(install_base, "adb.exe" if system == 'windows' else "adb")
            
            if os.path.exists(adb_path):
                if system != 'windows':
                    try:
                        os.chmod(adb_path, 0o755)
                    except:
                        pass

                adb_dir = os.path.dirname(adb_path)
                os.environ['PATH'] = adb_dir + os.pathsep + os.environ['PATH']
                
                return True, f"Platform Tools installed to: {adb_dir}"
            else:
                return False, "ADB executable not found after extraction"
                
        except Exception as e:
            return False, f"Installation failed: {str(e)}"

class ADBManager:
    @staticmethod
    def find_adb():
        safe_dir = ADBPlatformTools.get_safe_install_directory()
        local_paths = [
            os.path.join(safe_dir, "platform-tools", "adb.exe"),
            os.path.join(safe_dir, "platform-tools", "adb"),
            os.path.join(safe_dir, "adb.exe"), 
            os.path.join(safe_dir, "adb")
        ]
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_paths.extend([
            os.path.join(script_dir, "platform-tools", "adb.exe"),
            os.path.join(script_dir, "platform-tools", "adb"),
            os.path.join(script_dir, "adb.exe"),
            os.path.join(script_dir, "adb")
        ])
        
        for path in local_paths:
            if os.path.exists(path):
                return path
        
        try:
            result = run_hidden_command(['adb', 'version'], timeout=10)
            if result.returncode == 0:
                return 'adb'
        except:
            pass
            
        return None

    @staticmethod
    def check_adb():
        adb_path = ADBManager.find_adb()
        if not adb_path:
            return False, "ADB not found", None
        
        try:
            try:
                run_hidden_command([adb_path, 'kill-server'], timeout=5)
            except:
                pass
            
            result = run_hidden_command([adb_path, 'devices'], timeout=10)
            if result.returncode == 0:
                lines = [line for line in result.stdout.strip().split('\n') if '\tdevice' in line]
                if lines:
                    devices = []
                    for line in lines:
                        device_id = line.split('\t')[0]
                        info_result = run_hidden_command([adb_path, '-s', device_id, 'shell', 'getprop', 'ro.product.model'], timeout=10)
                        model = info_result.stdout.strip() if info_result.returncode == 0 else "Unknown"
                        devices.append(f"{device_id} ({model})")
                    
                    return True, f"Connected: {', '.join(devices)}", adb_path
                else:
                    return True, "No devices connected", adb_path
            return False, "ADB command failed", adb_path
        except subprocess.TimeoutExpired:
            return False, "ADB timeout", adb_path
        except Exception as e:
            return False, f"ADB error: {str(e)}", adb_path

    @staticmethod
    def push_to_quest(local_folder, quest_path):
        adb_path = ADBManager.find_adb()
        if not adb_path:
            return False, "ADB not available"
        
        try:
            # Optimize: Attempt to push the directory contents at once first
            # "adb push local_folder/. remote_folder/"
            # This is vastly faster than iterating files.
            
            # Ensure remote dir exists
            run_hidden_command([adb_path, 'shell', 'mkdir', '-p', quest_path], timeout=30)
            
            # Use trailing /. to push contents
            cmd = [adb_path, 'push', local_folder + "/.", quest_path + "/"]
            result = run_hidden_command(cmd, timeout=600) # 10 minute timeout
            
            if result.returncode == 0:
                return True, "Successfully pushed all items (Bulk Mode)"
            
            # Fallback to file-by-file if bulk fails (rare but safer)
            success_count = 0
            total_count = 0
            errors = []
            
            for item in os.listdir(local_folder):
                item_path = os.path.join(local_folder, item)
                if os.path.exists(item_path):
                    total_count += 1
                    result = run_hidden_command([adb_path, 'push', item_path, quest_path], timeout=60)
                    
                    if result.returncode == 0:
                        success_count += 1
                    else:
                        error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                        errors.append(f"{item}: {error_msg}")
            
            if success_count == total_count:
                return True, f"Successfully pushed all {success_count} items"
            elif success_count > 0:
                return True, f"Partially successful: {success_count}/{total_count}. Errors: {len(errors)}"
            else:
                return False, f"Failed to push items. Errors: {len(errors)}"
                    
        except subprocess.TimeoutExpired:
            return False, "Push operation timed out"
        except Exception as push_error:
            return False, f"Push error: {str(push_error)}"

    @staticmethod
    def install_adb_tools():
        return ADBPlatformTools.install_platform_tools()

class ASTCTools:
    @staticmethod
    def load_texture_mapping(mapping_file):
        if not os.path.exists(mapping_file):
            return {}
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            return mapping
        except Exception as e:
            print(f"Mapping load error: {e}")
            return {}

    @staticmethod
    def find_texture_info(texture_name, mapping):
        if texture_name in mapping:
            return mapping[texture_name]
        suffixes = ['_d', '_n', '_s', '_e', '_a', '_r', '_m', '_h']
        for suffix in suffixes:
            if texture_name.endswith(suffix):
                base_name = texture_name[:-len(suffix)]
                if base_name in mapping:
                    return mapping[base_name]
        return None

    @staticmethod
    def wrap_raw_astc(raw_path, wrapped_path, width, height, block_width=4, block_height=4):
        try:
            magic = struct.pack("<I", 0x5CA1AB13)
            block_dims = struct.pack("3B", block_width, block_height, 1)
            def dim3(x): return struct.pack("<I", x)[:3]
            image_dims = dim3(width) + dim3(height) + dim3(1)
            header = magic + block_dims + image_dims
            data = raw_path.read_bytes()
            wrapped_path.write_bytes(header + data)
            return True
        except Exception as e:
            print(f"Wrap failed: {e}")
            return False

    @staticmethod
    def decode_with_config(astcenc_path, raw_file, output_file, width, height, block_w, block_h, cache_key=None):
        temp_astc = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.astc', delete=False) as f:
                temp_astc = Path(f.name)
            
            if not ASTCTools.wrap_raw_astc(raw_file, temp_astc, width, height, block_w, block_h):
                return False
            
            result = run_hidden_command([
                str(astcenc_path), "-dl", str(temp_astc), str(output_file)
            ], timeout=10)
            
            if result.returncode == 0 and output_file.exists():
                file_size = output_file.stat().st_size
                if file_size > 1000:
                    if cache_key:
                        DECODE_CACHE[cache_key] = {
                            'width': width, 'height': height, 
                            'block_w': block_w, 'block_h': block_h,
                            'original_size': raw_file.stat().st_size
                        }
                    return True
                else:
                    output_file.unlink()
                    return False
            else:
                if output_file.exists():
                    output_file.unlink()
                return False
        except Exception:
            if output_file.exists():
                output_file.unlink()
            return False
        finally:
            if temp_astc and temp_astc.exists():
                try: temp_astc.unlink()
                except: pass

    @staticmethod
    def get_common_block_sizes():
        return [(4, 4), (8, 8), (6, 6), (5, 5), (10, 10), (12, 12), (5, 4), (6, 5), (8, 5), (8, 6), (10, 5), (10, 6), (10, 8)]

    @staticmethod
    def decode_with_mapping(astcenc_path, texture_file, output_path, mapping):
        texture_name = texture_file.stem
        texture_info = ASTCTools.find_texture_info(texture_name, mapping)
        if not texture_info: return False
        
        pcvr_width = texture_info['width']
        pcvr_height = texture_info['height']
        
        for block_w, block_h in ASTCTools.get_common_block_sizes():
            output_file = output_path / f"{texture_file.stem}.png"
            if ASTCTools.decode_with_config(astcenc_path, texture_file, output_file, pcvr_width, pcvr_height, block_w, block_h, texture_name):
                return True
        return False

    @staticmethod
    def brute_force_decode(astcenc_path, texture_file, output_path):
        configurations = [
            (2048, 1024, 8, 8, "2Kx1K_8x8"), (2048, 1024, 6, 6, "2Kx1K_6x6"), (2048, 1024, 4, 4, "2Kx1K_4x4"),
            (1024, 512, 8, 8, "1Kx512_8x8"), (1024, 512, 6, 6, "1Kx512_6x6"), (1024, 512, 4, 4, "1Kx512_4x4"),
            (2048, 2048, 8, 8, "2K_square_8x8"), (1024, 1024, 8, 8, "1K_square_8x8"),
        ]
        file_size = texture_file.stat().st_size
        
        for width, height, block_w, block_h, desc in configurations:
            expected_size = ASTCTools.calculate_astc_size(width, height, block_w, block_h)
            if abs(expected_size - file_size) > 100:
                continue
            output_file = output_path / f"{texture_file.stem}_BF_{desc}.png"
            if ASTCTools.decode_with_config(astcenc_path, texture_file, output_file, width, height, block_w, block_h, texture_file.stem):
                return True
        return False

    @staticmethod
    def calculate_astc_size(width, height, block_w, block_h):
        blocks_x = (width + block_w - 1) // block_w
        blocks_y = (height + block_h - 1) // block_h
        return blocks_x * blocks_y * 16

    @staticmethod
    def pad_to_size(data, target_size):
        current_size = len(data)
        if current_size < target_size:
            padding = b'\x00' * (target_size - current_size)
            return data + padding
        elif current_size > target_size:
            return data[:target_size]
        else:
            return data

    @staticmethod
    def encode_texture(astcenc_path, input_png, output_file, width, height, block_w, block_h, quality="medium", target_size=None):
        temp_astc = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.astc', delete=False) as f:
                temp_astc = Path(f.name)
            
            result = run_hidden_command([
                str(astcenc_path), "-cl", str(input_png), str(temp_astc), f"{block_w}x{block_h}", f"-{quality}", "-silent"
            ], timeout=30)
            
            if result.returncode != 0: return False
            
            with open(temp_astc, 'rb') as f:
                astc_data = f.read()
            
            if len(astc_data) > 16 and astc_data[:4] == b'\x13\xAB\xA1\x5C':
                raw_data = astc_data[16:]
            else:
                raw_data = astc_data
            
            if target_size:
                expected_size = ASTCTools.calculate_astc_size(width, height, block_w, block_h)
                if len(raw_data) != target_size:
                    raw_data = ASTCTools.pad_to_size(raw_data, target_size)
            
            output_file.write_bytes(raw_data)
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
        finally:
            if temp_astc and temp_astc.exists():
                temp_astc.unlink(missing_ok=True)

    @staticmethod
    def encode_with_cache(astcenc_path, input_png, output_file, texture_name, quality="medium"):
        if texture_name not in DECODE_CACHE: return False
        config = DECODE_CACHE[texture_name]
        return ASTCTools.encode_texture(astcenc_path, input_png, output_file, config['width'], config['height'], config['block_w'], config['block_h'], quality, config['original_size'])

    @staticmethod
    def save_decode_cache(cache_file):
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(DECODE_CACHE, f, indent=2)
        except: pass

    @staticmethod
    def load_decode_cache(cache_file):
        global DECODE_CACHE
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    DECODE_CACHE = json.load(f)
            except: pass

class EVRToolsManager:
    def __init__(self):
        self.tool_path = self.find_tool()
        
    def find_tool(self):
        tool_names = ["evrFileTools.exe", "echoModifyFiles.exe", "echoFileTools.exe"]
        for name in tool_names:
            path = get_tool_path(name)
            if os.path.exists(path):
                return path
        return None
    
    def extract_package(self, data_dir, package_name, output_dir, textures_only=False):
        if not self.tool_path:
            return False, "evrFileTools.exe not found"
        
        try:
            cmd = [
                self.tool_path, "-mode", "extract", "-packageName", package_name,
                "-dataDir", data_dir, "-outputDir", output_dir
            ]
            if textures_only:
                cmd.append("-texturesonly")
            
            result = run_hidden_command(cmd, cwd=os.path.dirname(self.tool_path), timeout=2000)
            
            if result.returncode == 0:
                return True, f"Extracted to {output_dir}"
            else:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Extraction failed: {error_msg}"
        except subprocess.TimeoutExpired:
            return False, "Extraction timeout"
        except Exception as e:
            return False, f"Extraction error: {str(e)}"
    
    def repack_package(self, output_dir, package_name, data_dir, input_dir):
        if not self.tool_path:
            return False, "evrFileTools.exe not found"
        
        try:
            cmd = [
                self.tool_path, "-mode", "replace", "-packageName", package_name,
                "-dataDir", data_dir, "-inputDir", input_dir, "-outputDir", output_dir
            ]
            
            result = run_hidden_command(cmd, cwd=os.path.dirname(self.tool_path), timeout=2000)
            
            if result.returncode == 0:
                return True, f"Repacked to {output_dir}"
            else:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Repacking failed: {error_msg}"
        except subprocess.TimeoutExpired:
            return False, "Repacking timeout"
        except Exception as e:
            return False, f"Repacking error: {str(e)}"

class DDSHandler:
    DXGI_FORMAT = {
        0: "DXGI_FORMAT_UNKNOWN", 71: "DXGI_FORMAT_BC1_UNORM", 77: "DXGI_FORMAT_BC3_UNORM", 
        80: "DXGI_FORMAT_BC4_UNORM", 83: "DXGI_FORMAT_BC5_UNORM",
    }
    
    @staticmethod
    def get_dds_info(file_path):
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(4)
                if signature != b'DDS ': return None
                header = f.read(124)
                if len(header) < 124: return None
                
                height = struct.unpack('<I', header[8:12])[0]
                width = struct.unpack('<I', header[12:16])[0]
                mipmap_count = struct.unpack('<I', header[24:28])[0]
                pixel_format_flags = struct.unpack('<I', header[76:80])[0]
                four_cc = header[80:84]
                
                format_name = "Unknown"
                format_code = None
                is_problematic = False
                
                if four_cc == b'DXT1': format_name = "BC1/DXT1"
                elif four_cc == b'DXT3': format_name = "BC2/DXT3"
                elif four_cc == b'DXT5': format_name = "BC3/DXT5"
                elif four_cc == b'DX10':
                    extended_header = f.read(20)
                    if len(extended_header) >= 20:
                        format_code = struct.unpack('<I', extended_header[0:4])[0]
                        format_name = DDSHandler.DXGI_FORMAT.get(format_code, f"DXGI Format {format_code}")
                        if format_code in [26, 72, 78]: is_problematic = True
                elif pixel_format_flags & 0x40: format_name = "RGB"
                
                return {
                    'width': width, 'height': height, 'mipmaps': mipmap_count,
                    'format': format_name, 'file_size': os.path.getsize(file_path),
                    'format_code': format_code, 'is_problematic': is_problematic
                }
        except Exception:
            return None
    
    @staticmethod
    def create_format_preview(width, height, format_name, file_path):
        img = Image.new('RGB', (max(256, width), max(256, height)), '#1a1a1a')
        draw = ImageDraw.Draw(img)
        grid_size = 32
        for x in range(0, img.width, grid_size):
            draw.line([(x, 0), (x, img.height)], fill='#2a2a2a', width=1)
        for y in range(0, img.height, grid_size):
            draw.line([(0, y), (img.width, y)], fill='#2a2a2a', width=1)
        
        y_pos = 20
        draw.text((20, y_pos), f"Format: {format_name}", fill='#4cd964')
        y_pos += 25
        draw.text((20, y_pos), f"Size: {width}x{height}", fill='#ffffff')
        y_pos += 25
        draw.text((20, y_pos), f"File: {os.path.basename(file_path)}", fill='#cccccc')
        return img

class TextureLoader:
    @staticmethod
    def get_cache_path(texture_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.join(script_dir, CACHE_DIR)
        os.makedirs(cache_dir, exist_ok=True)
        original_name = os.path.basename(texture_path)
        png_name = os.path.splitext(original_name)[0] + ".png"
        return os.path.join(cache_dir, png_name)
    
    @staticmethod
    def get_astcenc_path():
        return get_tool_path("astcenc-avx2.exe")

    @staticmethod
    def load_texture(texture_path, is_quest_texture=False):
        try:
            cache_path = TextureLoader.get_cache_path(texture_path)
            if os.path.exists(cache_path):
                try:
                    img = Image.open(cache_path).convert("RGBA")
                    return img
                except Exception:
                    try: os.remove(cache_path)
                    except: pass
            
            if is_quest_texture:
                return TextureLoader.load_quest_texture(texture_path, cache_path)
            else:
                return TextureLoader.load_dds_texture(texture_path, cache_path)
        except Exception:
            return DDSHandler.create_format_preview(256, 256, "Error Loading", texture_path)

    @staticmethod
    def load_quest_texture(texture_path, cache_path):
        try:
            astcenc_path = TextureLoader.get_astcenc_path()
            if not astcenc_path:
                return DDSHandler.create_format_preview(256, 256, "Missing astcenc", texture_path)
            
            temp_dir = tempfile.mkdtemp(prefix="astc_decode_")
            texture_file = Path(texture_path)
            output_path = Path(temp_dir)
            
            mapping = {}
            if os.path.exists(MAPPING_FILE):
                mapping = ASTCTools.load_texture_mapping(MAPPING_FILE)
            
            success = ASTCTools.decode_with_mapping(astcenc_path, texture_file, output_path, mapping)
            if not success:
                success = ASTCTools.brute_force_decode(astcenc_path, texture_file, output_path)
            
            if success:
                png_files = list(output_path.glob("*.png"))
                if png_files:
                    img = Image.open(png_files[0]).convert("RGBA")
                    try: img.save(cache_path)
                    except: pass
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return img
            
            shutil.rmtree(temp_dir, ignore_errors=True)
            return DDSHandler.create_format_preview(256, 256, "ASTC Decode Failed", texture_path)
        except Exception:
            return DDSHandler.create_format_preview(256, 256, "ASTC Error", texture_path)

    @staticmethod
    def load_dds_texture(dds_path, cache_path):
        dds_info = DDSHandler.get_dds_info(dds_path)
        if dds_info and dds_info.get("is_problematic", False):
            return TextureLoader.load_with_texconv(dds_path, cache_path)
        try:
            img = Image.open(dds_path)
            if img:
                try: img.save(cache_path)
                except: pass
                return img
        except Exception:
            pass
        return TextureLoader.load_with_texconv(dds_path, cache_path)

    @staticmethod
    def load_with_texconv(dds_path, cache_path=None):
        import struct
        temp_input = None
        temp_dir = None
        try:
            texconv_path = get_tool_path("texconv.exe")
            if not os.path.exists(texconv_path):
                return DDSHandler.create_format_preview(256, 256, "Missing texconv.exe", dds_path)

            with open(dds_path, "rb") as f:
                raw_data = f.read()
            
            is_dds = raw_data[:4] == b"DDS "
            temp_input = tempfile.NamedTemporaryFile(suffix=".dds", delete=False)
            temp_input.close()
            
            if is_dds:
                shutil.copy(dds_path, temp_input.name)
            else:
                # Basic DDS header reconstruction (skipped for brevity, assuming standard dds or valid raw)
                # If required, insert previous logic here
                shutil.copy(dds_path, temp_input.name)

            temp_dir = tempfile.mkdtemp(prefix="texconv_")
            cmd = [texconv_path, "-ft", "png", "-o", temp_dir, "-y", temp_input.name]
            result = run_hidden_command(cmd)
            
            base = os.path.splitext(os.path.basename(temp_input.name))[0]
            converted_file = os.path.join(temp_dir, base + ".png")
            
            if os.path.exists(converted_file):
                img = Image.open(converted_file).convert("RGBA")
                if cache_path:
                    try: img.save(cache_path)
                    except: pass
                return img
            else:
                return DDSHandler.create_format_preview(256, 256, "texconv failed", dds_path)
        except Exception:
            return DDSHandler.create_format_preview(256, 256, "texconv error", dds_path)
        finally:
            if temp_input and os.path.exists(temp_input.name):
                try: os.remove(temp_input.name)
                except: pass
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

class TextureReplacer:
    @staticmethod
    def hex_edit_file_size(file_path, new_size):
        try:
            with open(file_path, 'r+b') as f:
                data = bytearray(f.read())
                if len(data) >= 248:
                    file_size_bytes = struct.pack('<I', new_size)
                    data[244:248] = file_size_bytes
                    f.seek(0)
                    f.write(data)
                    f.truncate()
                    return True
                else:
                    return False
        except Exception:
            return False
    
    @staticmethod
    def replace_pcvr_texture(output_folder, pcvr_input_folder, original_texture_path, replacement_texture_path, replacement_size):
        try:
            input_textures_folder = os.path.join(pcvr_input_folder, "0", "-4707359568332879775")
            input_corresponding_folder = os.path.join(pcvr_input_folder, "0", "5353709876897953952")
            os.makedirs(input_textures_folder, exist_ok=True)
            os.makedirs(input_corresponding_folder, exist_ok=True)
            
            texture_name = os.path.basename(original_texture_path)
            output_corresponding_file = os.path.join(output_folder, "5353709876897953952", texture_name)
            
            input_texture_path = os.path.join(input_textures_folder, texture_name)
            input_corresponding_path = os.path.join(input_corresponding_folder, texture_name)
            
            shutil.copy2(replacement_texture_path, input_texture_path)
            
            if os.path.exists(output_corresponding_file):
                shutil.copy2(output_corresponding_file, input_corresponding_path)
                if TextureReplacer.hex_edit_file_size(input_corresponding_path, replacement_size):
                    return True, f"PCVR texture replaced. Size updated to {replacement_size} bytes."
                else:
                    return False, "Failed to update file size"
            else:
                return False, "Corresponding file not found"
        except Exception as e:
            return False, f"PCVR replacement error: {str(e)}"

    @staticmethod
    def replace_quest_texture(output_folder, quest_input_folder, original_texture_path, replacement_texture_path, texture_cache):
        try:
            input_textures_folder = os.path.join(quest_input_folder, "0", "5231972605540061417")
            input_corresponding_folder = os.path.join(quest_input_folder, "0", "-2094201140079393352")
            os.makedirs(input_textures_folder, exist_ok=True)
            os.makedirs(input_corresponding_folder, exist_ok=True)
            
            texture_name = os.path.basename(original_texture_path)
            original_size = os.path.getsize(original_texture_path)
            
            astcenc_path = TextureLoader.get_astcenc_path()
            if not astcenc_path: return False, "astcenc not found"
            
            mapping = {}
            if os.path.exists(MAPPING_FILE):
                mapping = ASTCTools.load_texture_mapping(MAPPING_FILE)
            
            temp_output = os.path.join(tempfile.gettempdir(), f"encoded_{texture_name}")
            texture_name_no_ext = os.path.splitext(texture_name)[0]
            success = False
            
            if texture_name_no_ext in DECODE_CACHE:
                success = ASTCTools.encode_with_cache(astcenc_path, Path(replacement_texture_path), Path(temp_output), texture_name_no_ext, "medium")
            elif mapping:
                if texture_name_no_ext in mapping:
                     success = ASTCTools.encode_texture(astcenc_path, Path(replacement_texture_path), Path(temp_output), 
                                                     mapping[texture_name_no_ext]['width'], mapping[texture_name_no_ext]['height'], 
                                                     8, 8, "medium", original_size)
            
            if not success: return False, "Failed to encode/find texture info"
            
            input_texture_path = os.path.join(input_textures_folder, texture_name)
            shutil.copy2(temp_output, input_texture_path)
            final_size = os.path.getsize(temp_output)
            
            output_corresponding_file = os.path.join(output_folder, "-2094201140079393352", texture_name)
            if os.path.exists(output_corresponding_file):
                input_corresponding_path = os.path.join(input_corresponding_folder, texture_name)
                shutil.copy2(output_corresponding_file, input_corresponding_path)
                TextureReplacer.hex_edit_file_size(input_corresponding_path, final_size)
            
            try: os.remove(temp_output)
            except: pass
            return True, f"Quest texture replaced. Size updated to {final_size} bytes."
        except Exception as e:
            return False, f"Quest replacement error: {str(e)}"

# --- NEW GRID POPUP CLASS ---
class TextureGridPopup:
    def __init__(self, parent, app, image_files, folder_path, is_quest):
        self.parent = parent
        self.app = app
        self.image_files = image_files
        self.folder_path = folder_path
        self.is_quest = is_quest
        
        self.window = tk.Toplevel(parent)
        self.window.title(f"Texture Gallery ({len(image_files)} items)")
        self.window.geometry("1000x700")
        self.window.configure(bg='#1a1a1a')
        
        self.thumb_size = (100, 100)
        self.grid_cols = 8
        self.loaded_images = {}
        
        self.setup_ui()
        self.load_images_thread()

    def setup_ui(self):
        top_frame = tk.Frame(self.window, bg='#2a2a2a', height=40)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="Click an image to select it in the main window", fg='#cccccc', bg='#2a2a2a').pack(pady=10)
        
        self.canvas = tk.Canvas(self.window, bg='#1a1a1a', highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg='#1a1a1a')
        
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        try: self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        except: pass

    def on_click(self, filename):
        self.app.select_texture_by_name(filename)
        self.parent.lift()

    def load_images_thread(self):
        def worker():
            row = 0
            col = 0
            count = 0
            for filename in self.image_files:
                if not self.window.winfo_exists(): break
                file_path = os.path.join(self.folder_path, filename)
                try:
                    img = TextureLoader.load_texture(file_path, self.is_quest)
                    if img:
                        img.thumbnail(self.thumb_size)
                        self.window.after(0, lambda i=img, f=filename, r=row, c=col: self.add_thumbnail(i, f, r, c))
                        col += 1
                        if col >= self.grid_cols:
                            col = 0
                            row += 1
                        count += 1
                        if count % 10 == 0: time.sleep(0.01)
                except: pass
        threading.Thread(target=worker, daemon=True).start()

    def add_thumbnail(self, img, filename, row, col):
        if not self.window.winfo_exists(): return
        try:
            photo = ImageTk.PhotoImage(img)
            self.loaded_images[filename] = photo 
            frame = tk.Frame(self.scroll_frame, bg='#333333', bd=1, relief=tk.SOLID)
            frame.grid(row=row, column=col, padx=4, pady=4)
            btn = tk.Button(frame, image=photo, command=lambda f=filename: self.on_click(f), bg='#1a1a1a', borderwidth=0)
            btn.image = photo
            btn.pack()
            tk.Label(frame, text=filename[:12]+"...", font=("Arial", 8), fg='#aaaaaa', bg='#333333').pack(fill=tk.X)
        except: pass

class EchoVRTextureViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("EchoVR Texture Editor - PCVR & Quest Support")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)
        
        self.colors = {
            'bg_dark': '#0a0a0a', 'bg_medium': '#1a1a1a', 'bg_light': '#2a2a2a',
            'accent_green': '#4cd964', 'accent_blue': '#007aff', 'accent_orange': '#ff9500',
            'accent_red': '#ff3b30', 'text_light': '#ffffff', 'text_muted': '#cccccc',
            'success': '#4cd964', 'warning': '#ffcc00', 'error': '#ff3b30'
        }
        
        self.root.configure(bg=self.colors['bg_dark'])
        self.config = ConfigManager.load_config()
        self.output_folder = self.config.get('output_folder')
        self.pcvr_input_folder = self.config.get('pcvr_input_folder')
        self.quest_input_folder = self.config.get('quest_input_folder')
        self.data_folder = self.config.get('data_folder')
        self.extracted_folder = self.config.get('extracted_folder')
        self.repacked_folder = self.config.get('repacked_folder')
        
        self.package_name = None
        self.evr_tools = EVRToolsManager()
        self.textures_folder = None
        self.corresponding_folder = None
        self.current_texture = None
        self.replacement_texture = None
        self.original_info = None
        self.replacement_info = None
        self.replacement_size = None
        self.is_quest_textures = False
        self.is_pcvr_textures = False
        self.texture_cache = {}
        self.all_textures = []
        self.filtered_textures = []
        self.is_downloading = False
        
        self.setup_ui()
        self.auto_detect_folders()
        
        if self.output_folder and os.path.exists(self.output_folder):
            self.set_output_folder(self.output_folder)
        if self.data_folder and os.path.exists(self.data_folder):
            self.set_data_folder(self.data_folder)
        if self.extracted_folder and os.path.exists(self.extracted_folder):
            self.set_extracted_folder(self.extracted_folder)
    
    def auto_detect_folders(self):
        if getattr(sys, 'frozen', False):
            application_path = os.path.dirname(sys.executable)
            parent_dir = os.path.dirname(application_path)
        else:
            application_path = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(application_path)
        
        for base_dir in [application_path, parent_dir]:
            pcvr_folder = os.path.join(base_dir, "input-pcvr")
            if os.path.exists(pcvr_folder):
                self.pcvr_input_folder = pcvr_folder
                self.log_info(f"Auto-detected PCVR input folder: {pcvr_folder}")
                break
            
        for base_dir in [application_path, parent_dir]:
            quest_folder = os.path.join(base_dir, "input-quest")
            if os.path.exists(quest_folder):
                self.quest_input_folder = quest_folder
                self.log_info(f"Auto-detected Quest input folder: {quest_folder}")
                break
        
        for base_dir in [application_path, parent_dir]:
            output_both = os.path.join(base_dir, "output-both")
            if os.path.exists(output_both):
                self.repacked_folder = output_both
                self.log_info(f"Auto-detected output-both folder: {output_both}")
                break
    
    def setup_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        main_frame = tk.Frame(self.root, bg=self.colors['bg_dark'])
        main_frame.grid(row=0, column=0, sticky='nsew', padx=10, pady=10)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        header_frame = tk.Frame(main_frame, bg=self.colors['bg_dark'])
        header_frame.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        self.tutorial_btn = tk.Button(header_frame, text="📚 Tutorial", command=lambda: TutorialPopup.show(self.root), bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=8)
        self.tutorial_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        title_label = tk.Label(header_frame, text="ECHO VR TEXTURE EDITOR", font=("Arial", 16, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'])
        title_label.pack(side=tk.LEFT, expand=True)
        
        self.update_echo_btn = tk.Button(header_frame, text="⚠ Update EchoVR", command=lambda: UpdateEchoPopup(self.root, self, self.config), bg=self.colors['accent_red'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=8)
        self.update_echo_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.status_label = tk.Label(main_frame, text="Welcome to EchoVR Texture Editor", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.status_label.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        self.platform_label = tk.Label(main_frame, text="Platform: Not detected", font=("Arial", 10, "bold"), fg=self.colors['warning'], bg=self.colors['bg_dark'])
        self.platform_label.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        evr_frame = tk.LabelFrame(main_frame, text="EVR TOOLS INTEGRATION", font=("Arial", 10, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'], relief=tk.RAISED, bd=2)
        evr_frame.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        evr_frame.columnconfigure(1, weight=1)
        
        tk.Label(evr_frame, text="Data Folder:", font=("Arial", 9), fg=self.colors['text_light'], bg=self.colors['bg_dark']).grid(row=0, column=0, sticky='w', padx=10, pady=5)
        
        self.data_folder_label = tk.Label(evr_frame, text="Not selected", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.data_folder_label.grid(row=0, column=1, sticky='w', padx=5, pady=5)
        
        self.data_folder_btn = tk.Button(evr_frame, text="Select", command=self.select_data_folder, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), relief=tk.RAISED, bd=1, padx=10, pady=3)
        self.data_folder_btn.grid(row=0, column=2, padx=10, pady=5)
        
        tk.Label(evr_frame, text="Package:", font=("Arial", 9), fg=self.colors['text_light'], bg=self.colors['bg_dark']).grid(row=1, column=0, sticky='w', padx=10, pady=5)
        
        self.package_var = tk.StringVar()
        self.package_dropdown = ttk.Combobox(evr_frame, textvariable=self.package_var, state="readonly", width=40)
        self.package_dropdown.grid(row=1, column=1, sticky='ew', padx=5, pady=5)
        self.package_dropdown.bind('<<ComboboxSelected>>', self.on_package_selected)
        
        tk.Label(evr_frame, text="Extracted Folder:", font=("Arial", 9), fg=self.colors['text_light'], bg=self.colors['bg_dark']).grid(row=2, column=0, sticky='w', padx=10, pady=5)
        
        self.extracted_folder_label = tk.Label(evr_frame, text="Not selected", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.extracted_folder_label.grid(row=2, column=1, sticky='w', padx=5, pady=5)
        
        self.extracted_folder_btn = tk.Button(evr_frame, text="Select", command=self.select_extracted_folder, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), relief=tk.RAISED, bd=1, padx=10, pady=3)
        self.extracted_folder_btn.grid(row=2, column=2, padx=10, pady=5)
        
        button_frame = tk.Frame(evr_frame, bg=self.colors['bg_dark'])
        button_frame.grid(row=3, column=0, columnspan=3, pady=10)
        
        self.extract_btn = tk.Button(button_frame, text="Extract Package", command=self.extract_package, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=20, pady=8, state=tk.DISABLED)
        self.extract_btn.pack(side=tk.LEFT, padx=5)
        
        self.repack_btn = tk.Button(button_frame, text="Repack Modified", command=self.repack_package, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=20, pady=8, state=tk.DISABLED)
        self.repack_btn.pack(side=tk.LEFT, padx=5)

        self.evr_status_label = tk.Label(evr_frame, text="Ready", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.evr_status_label.grid(row=4, column=0, columnspan=3, pady=(0, 10))
        
        content_frame = tk.Frame(main_frame, bg=self.colors['bg_dark'])
        content_frame.grid(row=4, column=0, columnspan=3, sticky='nsew')
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=2)
        content_frame.columnconfigure(2, weight=2)
        content_frame.rowconfigure(0, weight=1)
        
        left_frame = tk.LabelFrame(content_frame, text="AVAILABLE TEXTURES", font=("Arial", 10, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'], relief=tk.RAISED, bd=2)
        left_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)
        
        search_frame = tk.Frame(left_frame, bg=self.colors['bg_dark'])
        search_frame.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        
        tk.Label(search_frame, text="Search:", font=("Arial", 9), fg=self.colors['text_light'], bg=self.colors['bg_dark']).pack(side=tk.LEFT, padx=(0, 5))
        
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), insertbackground=self.colors['text_light'])
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.search_entry.bind('<KeyRelease>', self.filter_textures)
        
        clear_btn = tk.Button(search_frame, text="X", command=self.clear_search, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), relief=tk.RAISED, bd=1, width=3)
        clear_btn.pack(side=tk.LEFT)
        
        # Grid View Button
        self.grid_view_btn = tk.Button(left_frame, text="View Texture Grid", command=self.open_grid_view, bg=self.colors['accent_blue'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2)
        self.grid_view_btn.grid(row=2, column=0, sticky='ew', padx=5, pady=5)

        list_frame = tk.Frame(left_frame, bg=self.colors['bg_dark'])
        list_frame.grid(row=1, column=0, sticky='nsew', padx=5, pady=(0, 5))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # EXTENDED selectmode for multi-select
        self.file_list = tk.Listbox(list_frame, bg=self.colors['bg_light'], fg=self.colors['text_light'], selectbackground=self.colors['accent_green'], selectforeground=self.colors['text_light'], font=("Arial", 9), relief=tk.SUNKEN, bd=1, selectmode=tk.EXTENDED)
        
        scrollbar = tk.Scrollbar(list_frame, bg=self.colors['bg_light'])
        self.file_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.file_list.yview)
        
        self.file_list.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.file_list.bind('<<ListboxSelect>>', self.on_texture_selected)
        
        middle_frame = tk.LabelFrame(content_frame, text="ORIGINAL TEXTURE", font=("Arial", 10, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'], relief=tk.RAISED, bd=2)
        middle_frame.grid(row=0, column=1, sticky='nsew', padx=5)
        middle_frame.columnconfigure(0, weight=1)
        middle_frame.rowconfigure(0, weight=1)
        
        self.original_canvas = tk.Canvas(middle_frame, bg=self.colors['bg_medium'])
        self.original_canvas.grid(row=0, column=0, sticky='nsew')
        
        right_frame = tk.LabelFrame(content_frame, text="REPLACEMENT TEXTURE", font=("Arial", 10, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'], relief=tk.RAISED, bd=2)
        right_frame.grid(row=0, column=2, sticky='nsew', padx=(5, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)
        
        self.replacement_canvas = tk.Canvas(right_frame, bg=self.colors['bg_medium'])
        self.replacement_canvas.grid(row=0, column=0, sticky='nsew')
        self.replacement_canvas.bind("<Button-1>", self.browse_replacement_texture)
        
        button_panel = tk.Frame(main_frame, bg=self.colors['bg_dark'])
        button_panel.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        
        adb_frame = tk.Frame(button_panel, bg=self.colors['bg_dark'])
        adb_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        self.install_adb_btn = tk.Button(adb_frame, text="Install ADB Tools", command=self.install_adb_tools, bg=self.colors['accent_orange'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5)
        self.install_adb_btn.pack(side=tk.LEFT, padx=5)
        
        self.push_quest_btn = tk.Button(adb_frame, text="Push Files To Quest", command=self.push_to_quest, bg=self.colors['accent_orange'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5, state=tk.DISABLED)
        self.push_quest_btn.pack(side=tk.LEFT, padx=5)
        
        action_frame = tk.Frame(button_panel, bg=self.colors['bg_dark'])
        action_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.edit_btn = tk.Button(action_frame, text="Open in Editor", command=self.open_external_editor, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5, state=tk.DISABLED)
        self.edit_btn.pack(side=tk.LEFT, padx=5)
        
        self.replace_btn = tk.Button(action_frame, text="Replace Texture", command=self.replace_texture, bg=self.colors['accent_green'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5, state=tk.DISABLED)
        self.replace_btn.pack(side=tk.LEFT, padx=5)
        
        self.download_btn = tk.Button(action_frame, text="Download All Textures", command=self.download_textures, bg=self.colors['accent_blue'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        self.resolution_status = tk.Label(button_panel, text="", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.resolution_status.pack(side=tk.LEFT, padx=20)
        
        info_frame = tk.LabelFrame(main_frame, text="TEXTURE INFORMATION", font=("Arial", 10, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'], relief=tk.RAISED, bd=2)
        info_frame.grid(row=6, column=0, columnspan=3, sticky='nsew', pady=(10, 0))
        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(0, weight=1)
        
        self.info_text = scrolledtext.ScrolledText(info_frame, height=6, wrap=tk.WORD, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), relief=tk.SUNKEN, bd=1)
        self.info_text.grid(row=0, column=0, sticky='nsew', padx=2, pady=2)
        
        self.update_canvas_placeholder(self.original_canvas, "Select output folder to view textures")
        self.update_canvas_placeholder(self.replacement_canvas, "Click to select replacement texture")
    
    def update_canvas_placeholder(self, canvas, text):
        canvas.delete("all")
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width, canvas_height = 400, 300
        canvas.create_text(canvas_width//2, canvas_height//2, text=text, font=("Arial", 10), fill=self.colors['text_muted'], justify=tk.CENTER)
    
    def log_info(self, message):
        self.info_text.insert(tk.END, message + "\n")
        self.info_text.see(tk.END)
        self.info_text.update_idletasks()
    
    def select_data_folder(self):
        path = filedialog.askdirectory(title="Select Data Folder (contains manifests and packages)")
        if path:
            self.set_data_folder(path)
    
    def set_data_folder(self, path):
        self.data_folder = path
        self.data_folder_label.config(text=os.path.basename(path), fg=self.colors['text_light'])
        
        manifests_path = os.path.join(path, "manifests")
        packages_path = os.path.join(path, "packages")
        
        if not os.path.exists(manifests_path) or not os.path.exists(packages_path):
            parent_path = os.path.dirname(path)
            parent_manifests = os.path.join(parent_path, "manifests")
            parent_packages = os.path.join(parent_path, "packages")
            
            if os.path.exists(parent_manifests) and os.path.exists(parent_packages):
                path = parent_path
                manifests_path = parent_manifests
                packages_path = parent_packages
                self.data_folder = path
                self.data_folder_label.config(text=os.path.basename(path))
        
        if os.path.exists(manifests_path) and os.path.exists(packages_path):
            self.populate_package_dropdown(manifests_path)
            self.log_info(f"✓ Data folder set: {path}")
        else:
            self.log_info("✗ Could not find manifests and packages folders")
        
        ConfigManager.save_config(data_folder=self.data_folder)
        self.update_evr_buttons_state()
    
    def select_extracted_folder(self):
        path = filedialog.askdirectory(title="Select Extracted Folder")
        if path:
            self.set_extracted_folder(path)
    
    def set_extracted_folder(self, path):
        self.extracted_folder = path
        self.extracted_folder_label.config(text=os.path.basename(path), fg=self.colors['text_light'])
        self.set_output_folder(path)
        self.update_evr_buttons_state()
        ConfigManager.save_config(extracted_folder=self.extracted_folder)
        self.log_info(f"✓ Extracted folder set: {path}")
    
    def populate_package_dropdown(self, manifests_path):
        try:
            packages = []
            for file_name in os.listdir(manifests_path):
                if os.path.isfile(os.path.join(manifests_path, file_name)):
                    packages_path = os.path.join(os.path.dirname(manifests_path), "packages")
                    package_file = os.path.join(packages_path, file_name)
                    package_file_0 = os.path.join(packages_path, f"{file_name}_0")
                    if os.path.exists(package_file) or os.path.exists(package_file_0):
                        packages.append(file_name)
            
            filtered_packages = [pkg for pkg in packages if pkg == "48037dc70b0ecab2"]
            if not filtered_packages and packages:
                filtered_packages = [packages[0]]
            
            self.package_dropdown['values'] = filtered_packages
            if filtered_packages:
                self.package_dropdown.current(0)
                self.on_package_selected(None)
                self.log_info(f"Found {len(packages)} packages")
            else:
                self.log_info("No valid packages found")
        except Exception as e:
            self.log_info(f"Error reading manifests: {e}")
    
    def on_package_selected(self, event):
        self.package_name = self.package_var.get()
        self.update_evr_buttons_state()
    
    def update_evr_buttons_state(self):
        if self.data_folder and self.package_name and self.extracted_folder:
            self.extract_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
            if os.path.exists(self.extracted_folder) and any(os.listdir(self.extracted_folder)):
                self.repack_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
            else:
                self.repack_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
        else:
            self.extract_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            self.repack_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
    
    def extract_package(self):
        if not all([self.data_folder, self.package_name, self.extracted_folder]):
            messagebox.showerror("Error", "Please select data folder, package, and extraction folder first.")
            return

        popup = tk.Toplevel(self.root)
        popup.title("Extraction Mode")
        popup.geometry("400x180")
        popup.configure(bg=self.colors['bg_medium'])
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 180) // 2
            popup.geometry(f"+{x}+{y}")
        except: pass

        tk.Label(popup, text="Select Extraction Mode", font=("Arial", 12, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_medium']).pack(pady=(20, 10))
        tk.Label(popup, text="Texture mode is faster but only extracts texture files.", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_medium']).pack(pady=(0, 20))

        btn_frame = tk.Frame(popup, bg=self.colors['bg_medium'])
        btn_frame.pack(fill=tk.X, padx=20)

        def do_extract(textures_only):
            popup.destroy()
            self._run_extraction(textures_only)

        tk.Button(btn_frame, text="Extract Textures Only (Fast)", command=lambda: do_extract(True), bg=self.colors['accent_green'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED).pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="Extract Full Package (Slow)", command=lambda: do_extract(False), bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), relief=tk.RAISED).pack(fill=tk.X, pady=5)

    def _run_extraction(self, textures_only):
        os.makedirs(self.extracted_folder, exist_ok=True)
        mode_text = "Textures Only" if textures_only else "Full Package"
        self.evr_status_label.config(text=f"Extracting package ({mode_text})...", fg=self.colors['accent_green'])
        self.root.update_idletasks()
        
        def extraction_thread():
            success, message = self.evr_tools.extract_package(self.data_folder, self.package_name, self.extracted_folder, textures_only=textures_only)
            self.root.after(0, lambda: self.on_extraction_complete(success, message))
        
        threading.Thread(target=extraction_thread, daemon=True).start()
    
    def on_extraction_complete(self, success, message):
        if success:
            self.evr_status_label.config(text="Extraction successful!", fg=self.colors['success'])
            self.log_info(f"✓ EXTRACTION: {message}")
            extracted_textures_path = self.find_extracted_textures(self.extracted_folder)
            if extracted_textures_path:
                self.set_output_folder(extracted_textures_path)
            else:
                self.set_output_folder(self.extracted_folder)
            self.repack_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
        else:
            self.evr_status_label.config(text="Extraction failed", fg=self.colors['error'])
            self.log_info(f"✗ EXTRACTION FAILED: {message}")
            messagebox.showerror("Extraction Error", message)
    
    def find_extracted_textures(self, base_dir):
        for pattern in glob.glob(os.path.join(base_dir, "**"), recursive=True):
             if os.path.basename(pattern) in ["-4707359568332879775", "5231972605540061417"]:
                 if os.path.isdir(pattern):
                     return os.path.dirname(pattern)
        return None
    
    def repack_package(self):
        if not all([self.data_folder, self.package_name, self.extracted_folder]):
            messagebox.showerror("Error", "Please select data folder, package, and extraction folder first.")
            return

        if self.is_quest_textures and self.quest_input_folder:
            input_folder = self.quest_input_folder
            self.log_info("🎯 Using Quest input folder for repacking")
        elif self.is_pcvr_textures and self.pcvr_input_folder:
            input_folder = self.pcvr_input_folder
            self.log_info("🎮 Using PCVR input folder for repacking")
        else:
            messagebox.showerror("Error", "Input folder not found. Please check input-pcvr/input-quest folders.")
            return
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = self.repacked_folder
        
        confirm = messagebox.askyesno("Confirm Repack", f"Repack modified files to:\n{output_dir}\n\nContinue?")
        if not confirm: return
        
        self.evr_status_label.config(text="Repacking package...", fg=self.colors['accent_green'])
        self.root.update_idletasks()
        
        def repacking_thread():
            success, message = self.evr_tools.repack_package(output_dir, self.package_name, self.data_folder, input_folder)
            self.root.after(0, lambda: self.on_repacking_complete(success, message, output_dir))
        
        threading.Thread(target=repacking_thread, daemon=True).start()
    
    def on_repacking_complete(self, success, message, output_dir):
        if success:
            self.evr_status_label.config(text="Repacking successful!", fg=self.colors['success'])
            self.log_info(f"✓ REPACKING: {message}")
            packages_path = os.path.join(output_dir, "packages")
            manifests_path = os.path.join(output_dir, "manifests")
            if os.path.exists(packages_path) and os.path.exists(manifests_path):
                self.log_info(f"✓ Packages and manifests created in: {output_dir}")
                self.update_quest_push_button()
            else:
                self.log_info("⚠ Packages or manifests folders not found in output directory")
        else:
            self.evr_status_label.config(text="Repacking failed", fg=self.colors['error'])
            self.log_info(f"✗ REPACKING FAILED: {message}")
        messagebox.showinfo("Repacking Result", message)
    
    def install_adb_tools(self):
        self.log_info("Installing ADB Platform Tools...")
        def install_thread():
            success, message = ADBManager.install_adb_tools()
            self.root.after(0, lambda: self.on_adb_install_complete(success, message))
        threading.Thread(target=install_thread, daemon=True).start()
    
    def on_adb_install_complete(self, success, message):
        if success:
            self.log_info(f"✅ ADB Tools installed: {message}")
            messagebox.showinfo("Success", "ADB Platform Tools installed successfully!")
            self.test_adb_connection()
        else:
            self.log_info(f"❌ ADB installation failed: {message}")
            messagebox.showerror("Error", f"ADB installation failed: {message}")
    
    def test_adb_connection(self):
        def test_thread():
            success, message, adb_path = ADBManager.check_adb()
            self.root.after(0, lambda: self.on_adb_test_complete(success, message))
        threading.Thread(target=test_thread, daemon=True).start()
    
    def on_adb_test_complete(self, success, message):
        if success:
            self.log_info(f"✅ ADB: {message}")
            if self.is_quest_textures:
                self.push_quest_btn.config(state=tk.NORMAL, bg=self.colors['accent_orange'])
        else:
            self.log_info(f"❌ ADB: {message}")
            self.push_quest_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
    
    def update_quest_push_button(self):
        if self.is_quest_textures and self.output_folder:
            self.test_adb_connection()
        else:
            self.push_quest_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
    
    def push_to_quest(self):
        if not self.output_folder:
            messagebox.showerror("Error", "Please select output folder first")
            return
        success, message, _ = ADBManager.check_adb()
        if not success:
            messagebox.showerror("ADB Error", f"Cannot connect to Quest:\n{message}")
            return
        
        result = messagebox.askyesno("Push to Quest", "This will push files to your Quest headset.\n\nContinue?", icon='warning')
        if not result: return
        
        self.log_info("🚀 Starting Quest file push...")
        self.push_quest_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'], text="Pushing...")
        self.root.update_idletasks()
        
        def push_thread():
            try:
                push_folder = self.output_folder
                if self.repacked_folder and os.path.exists(self.repacked_folder):
                    if (os.path.exists(os.path.join(self.repacked_folder, "manifests")) or os.path.exists(os.path.join(self.repacked_folder, "packages"))):
                        push_folder = self.repacked_folder
                        self.log_info("📦 Using repacked folder")
                
                quest_dest_path = "/sdcard/readyatdawn/files/_data/5932408047/rad15/android"
                success, message = ADBManager.push_to_quest(push_folder, quest_dest_path)
                self.root.after(0, lambda: self.on_quest_push_complete(success, message))
            except Exception as thread_error:
                error_message = f"Push thread error: {str(thread_error)}"
                self.root.after(0, lambda: self.on_quest_push_complete(False, error_message))
        
        threading.Thread(target=push_thread, daemon=True).start()
    
    def on_quest_push_complete(self, success, message):
        if success:
            messagebox.showinfo("Success", f"Files pushed to Quest!\n\n{message}")
            self.log_info(f"✅ QUEST PUSH: {message}")
        else:
            messagebox.showerror("Error", f"Failed to push files:\n{message}")
            self.log_info(f"❌ QUEST PUSH FAILED: {message}")
        self.push_quest_btn.config(state=tk.NORMAL, bg=self.colors['accent_orange'], text="Push Files To Quest")
        self.update_quest_push_button()
    
    def set_output_folder(self, path):
        self.output_folder = path
        folder_name = os.path.basename(path).lower()
        if "quest" in folder_name:
            self.is_quest_textures = True
            self.is_pcvr_textures = False
            self.textures_folder = os.path.join(path, "5231972605540061417")
            self.corresponding_folder = os.path.join(path, "-2094201140079393352")
            self.platform_label.config(text="Platform: Quest (ASTC)", fg=self.colors['success'])
            self.log_info("🎯 Switched to Quest mode")
        elif "pcvr" in folder_name:
            self.is_quest_textures = False
            self.is_pcvr_textures = True
            self.textures_folder = os.path.join(path, "-4707359568332879775")
            self.corresponding_folder = os.path.join(path, "5353709876897953952")
            self.platform_label.config(text="Platform: PCVR (DDS)", fg=self.colors['accent_blue'])
            self.push_quest_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            self.log_info("🎮 Switched to PCVR mode")
        else:
            quest_textures_folder = os.path.join(path, "5231972605540061417")
            pcvr_textures_folder = os.path.join(path, "-4707359568332879775")
            if getattr(sys, 'frozen', False):
                parent_dir = os.path.dirname(os.path.dirname(path))
                if not os.path.exists(quest_textures_folder):
                    quest_textures_folder = os.path.join(parent_dir, os.path.basename(path), "5231972605540061417")
                if not os.path.exists(pcvr_textures_folder):
                    pcvr_textures_folder = os.path.join(parent_dir, os.path.basename(path), "-4707359568332879775")
            
            if os.path.exists(quest_textures_folder):
                self.textures_folder = quest_textures_folder
                self.corresponding_folder = os.path.join(path, "-2094201140079393352")
                self.is_quest_textures = True
                self.is_pcvr_textures = False
                self.platform_label.config(text="Platform: Quest (ASTC)", fg=self.colors['success'])
                self.log_info("🎯 Auto-detected Quest textures")
            elif os.path.exists(pcvr_textures_folder):
                self.textures_folder = pcvr_textures_folder
                self.corresponding_folder = os.path.join(path, "5353709876897953952")
                self.is_quest_textures = False
                self.is_pcvr_textures = True
                self.platform_label.config(text="Platform: PCVR (DDS)", fg=self.colors['accent_blue'])
                self.push_quest_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
                self.log_info("🎮 Auto-detected PCVR textures")
            else:
                self.textures_folder = path
                self.log_info("⚠ Could not determine platform structure, using root folder")

        if os.path.exists(self.textures_folder):
            platform_text = "Quest" if self.is_quest_textures else "PCVR"
            self.status_label.config(text=f"Output folder: {os.path.basename(path)} ({platform_text})")
            self.log_info(f"Output folder set: {path} ({platform_text})")
            self.load_textures()
            ConfigManager.save_config(output_folder=self.output_folder)
            self.update_quest_push_button()
    
    def filter_textures(self, event=None):
        search_text = self.search_var.get().lower()
        if not search_text:
            self.filtered_textures = self.all_textures.copy()
        else:
            self.filtered_textures = [texture for texture in self.all_textures if search_text in texture.lower()]
        self.file_list.delete(0, tk.END)
        for texture in self.filtered_textures:
            self.file_list.insert(tk.END, texture)
    
    def clear_search(self):
        self.search_var.set("")
        self.filter_textures()
    
    def load_textures(self):
        self.file_list.delete(0, tk.END)
        self.file_list.insert(tk.END, "Loading textures...")
        self.update_canvas_placeholder(self.original_canvas, "Loading textures...")
        self.root.update_idletasks()
        threading.Thread(target=self._load_textures_worker, daemon=True).start()

    def _load_textures_worker(self):
        if not self.textures_folder or not os.path.exists(self.textures_folder):
             self.root.after(0, lambda: self._on_textures_loaded([], 0))
             return

        cached_files = TextureCacheManager.get_cached_files(self.textures_folder)
        if cached_files is not None:
             self.root.after(0, lambda: self._on_textures_loaded(cached_files, len(cached_files)))
             return

        valid_files = []
        try:
            raw_file_list = os.listdir(self.textures_folder)
            valid_files = [f for f in raw_file_list if os.path.isfile(os.path.join(self.textures_folder, f))]
            TextureCacheManager.update_cache(self.textures_folder, valid_files)
            self.root.after(0, lambda: self._on_textures_loaded(valid_files, len(valid_files)))
        except Exception as e:
            print(f"Scan Error: {e}")
            self.root.after(0, lambda: self._on_textures_loaded([], 0))

    def _on_textures_loaded(self, files, count):
        self.all_textures = sorted(files)
        self.filtered_textures = self.all_textures.copy()
        self.file_list.delete(0, tk.END)
        for file_name in self.filtered_textures:
            self.file_list.insert(tk.END, file_name)
        platform_text = "Quest" if self.is_quest_textures else "PCVR"
        status_text = f"Found {count} {platform_text} texture files"
        self.status_label.config(text=status_text)
        self.log_info(f"Found {count} {platform_text} texture files")
        if count == 0:
            self.log_info("No texture files found.")
            self.update_canvas_placeholder(self.original_canvas, "No textures found")
        else:
            self.update_canvas_placeholder(self.original_canvas, "Select a texture to view")

    def on_texture_selected(self, event):
        if not self.file_list.curselection(): return
        
        # Multi-select: Show count if multiple
        selection = self.file_list.curselection()
        if len(selection) > 1:
            self.update_canvas_placeholder(self.original_canvas, f"{len(selection)} files selected")
            self.replace_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'], text=f"Replace {len(selection)} Files")
            self.edit_btn.config(state=tk.DISABLED)
            return

        index = selection[0]
        texture_name = self.filtered_textures[index]
        self.current_texture = os.path.join(self.textures_folder, texture_name)
        self.replace_btn.config(text="Replace Texture")

        try:
            self.update_canvas_placeholder(self.original_canvas, "Loading texture...")
            self.root.update_idletasks()
            def load_texture_thread():
                try:
                    image = TextureLoader.load_texture(self.current_texture, self.is_quest_textures)
                    self.root.after(0, lambda: self.display_texture_result(image))
                except Exception as e:
                    self.root.after(0, lambda: self.display_texture_error(e))
            threading.Thread(target=load_texture_thread, daemon=True).start()
        except Exception as e:
            self.log_info(f"Error loading texture: {e}")
            self.update_canvas_placeholder(self.original_canvas, "Error loading texture")
    
    def display_texture_result(self, image):
        if image:
            self.display_image_on_canvas(image, self.original_canvas)
            if self.is_quest_textures:
                self.original_info = {
                    'file_size': os.path.getsize(self.current_texture),
                    'format': 'ASTC', 'width': image.width, 'height': image.height
                }
            else:
                self.original_info = DDSHandler.get_dds_info(self.current_texture)
            
            self.update_texture_info()
            self.edit_btn.config(state=tk.NORMAL, bg=self.colors['accent_blue'])
            self.replace_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
        else:
            self.update_canvas_placeholder(self.original_canvas, "Failed to load texture")
            self.edit_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            self.replace_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
    
    def display_texture_error(self, error):
        self.log_info(f"Error loading texture: {error}")
        self.update_canvas_placeholder(self.original_canvas, "Error loading texture")
        self.edit_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
        self.replace_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
    
    def browse_replacement_texture(self, event):
        if not self.current_texture and len(self.file_list.curselection()) == 0:
            messagebox.showinfo("Info", "Please select an original texture first")
            return
        
        file_types = [("PNG files", "*.png"), ("DDS files", "*.dds"), ("All files", "*.*")]
        if self.is_quest_textures:
            file_types = [("PNG files", "*.png"), ("All files", "*.*")]
        
        file_path = filedialog.askopenfilename(title="Select Replacement Texture", filetypes=file_types)
        
        if file_path:
            self.replacement_texture = file_path
            try:
                def load_replacement_thread():
                    try:
                        if self.is_quest_textures:
                            image = Image.open(file_path).convert("RGBA")
                        else:
                            image = TextureLoader.load_texture(file_path, False)
                        self.root.after(0, lambda: self.display_replacement_result(image, file_path))
                    except Exception as e:
                        self.root.after(0, lambda: self.display_replacement_error(e))
                threading.Thread(target=load_replacement_thread, daemon=True).start()
            except Exception as e:
                self.log_info(f"Error loading replacement texture: {e}")
                self.update_canvas_placeholder(self.replacement_canvas, "Error loading replacement")
    
    def display_replacement_result(self, image, file_path):
        if image:
            self.display_image_on_canvas(image, self.replacement_canvas)
            if self.is_quest_textures:
                self.replacement_info = {
                    'file_size': os.path.getsize(file_path),
                    'format': 'PNG', 'width': image.width, 'height': image.height
                }
                self.replacement_size = None
            else:
                self.replacement_info = DDSHandler.get_dds_info(file_path)
                self.replacement_size = self.replacement_info['file_size']
            self.update_texture_info()
            self.check_resolution_match()
            self.log_info(f"Replacement loaded: {os.path.basename(file_path)}")
        else:
            self.update_canvas_placeholder(self.replacement_canvas, "Failed to load replacement")
    
    def display_replacement_error(self, error):
        self.log_info(f"Error loading replacement texture: {error}")
        self.update_canvas_placeholder(self.replacement_canvas, "Error loading replacement")
    
    def display_image_on_canvas(self, image, canvas):
        canvas.delete("all")
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width, canvas_height = 400, 300
        
        img_width, img_height = image.size
        ratio = min(canvas_width / img_width, canvas_height / img_height)
        new_size = (int(img_width * ratio), int(img_height * ratio))
        
        resized_image = image.resize(new_size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized_image)
        x_pos = (canvas_width - new_size[0]) // 2
        y_pos = (canvas_height - new_size[1]) // 2
        canvas.create_image(x_pos, y_pos, anchor=tk.NW, image=photo)
        canvas.image = photo
    
    def update_texture_info(self):
        info = ""
        if self.original_info:
            platform_text = "Quest" if self.is_quest_textures else "PCVR"
            info += f"=== ORIGINAL ({platform_text}) ===\n"
            info += f"File: {os.path.basename(self.current_texture)}\n"
            info += f"Size: {self.original_info['file_size']:,} bytes\n"
            if 'width' in self.original_info:
                info += f"Dim: {self.original_info['width']} x {self.original_info['height']}\n"
            info += f"Format: {self.original_info['format']}\n\n"
        
        if self.replacement_info:
            info += "=== REPLACEMENT ===\n"
            info += f"File: {os.path.basename(self.replacement_texture)}\n"
            if 'width' in self.replacement_info:
                info += f"Dim: {self.replacement_info['width']} x {self.replacement_info['height']}\n"
            info += f"Format: {self.replacement_info['format']}\n"
        
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, info)
    
    def check_resolution_match(self):
        if self.original_info and self.replacement_info and 'width' in self.original_info:
            if self.original_info['width'] == self.replacement_info['width'] and self.original_info['height'] == self.replacement_info['height']:
                self.resolution_status.config(text="✓ Resolutions match", fg=self.colors['success'])
            else:
                self.resolution_status.config(text="✗ Resolutions don't match", fg=self.colors['warning'])
        else:
            self.resolution_status.config(text="")
    
    def open_external_editor(self):
        if not self.current_texture: return
        try:
            if sys.platform == 'win32': os.startfile(self.current_texture)
            elif sys.platform == 'darwin': subprocess.call(('open', self.current_texture))
            else: subprocess.call(('xdg-open', self.current_texture))
        except Exception as e:
            messagebox.showerror("Error", f"Could not open external editor: {str(e)}")
    
    def replace_texture(self):
        if not self.replacement_texture or not self.output_folder:
            return
            
        selection = self.file_list.curselection()
        if not selection: return

        # Confirm multiple replacement
        if len(selection) > 1:
            confirm = messagebox.askyesno("Multi-Replace", f"Are you sure you want to replace {len(selection)} textures with the selected image?")
            if not confirm: return

        # Loop through selected items
        for index in selection:
            texture_name = self.filtered_textures[index]
            current_texture_path = os.path.join(self.textures_folder, texture_name)
            
            if self.is_quest_textures:
                if not self.quest_input_folder:
                    messagebox.showerror("Error", "Quest input folder not found.")
                    return
                success, message = TextureReplacer.replace_quest_texture(self.output_folder, self.quest_input_folder, current_texture_path, self.replacement_texture, self.texture_cache)
            else:
                if not self.pcvr_input_folder:
                    messagebox.showerror("Error", "PCVR input folder not found.")
                    return
                
                # For PCVR, we need the file size of the replacement usually, which requires DDS info.
                # If doing multi-replace, we assume replacement_info is valid from the loaded replacement.
                if self.replacement_info and 'file_size' in self.replacement_info:
                     replacement_size = self.replacement_info['file_size']
                     success, message = TextureReplacer.replace_pcvr_texture(self.output_folder, self.pcvr_input_folder, current_texture_path, self.replacement_texture, replacement_size)
                else:
                    self.log_info(f"Skipping {texture_name}: Replacement size unknown.")
                    continue

            if success:
                self.log_info(f"✓ Replaced {texture_name}")
            else:
                self.log_info(f"✗ Failed {texture_name}: {message}")

        messagebox.showinfo("Complete", "Texture replacement operation finished.")
        # Refresh current selection view if single
        if len(selection) == 1:
            self.on_texture_selected(None)
    
    def download_textures(self):
        if self.is_downloading:
            self.log_info("Download already in progress...")
            return
        confirm = messagebox.askyesno("Download Textures", "Download texture cache archive (~200MB)?")
        if not confirm: return
        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED, text="Downloading...", bg=self.colors['accent_orange'])
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        url = "https://github.com/heisthecat31/EchoVR-Texture-Editor/releases/download/quest/texture_cache.zip"
        if getattr(sys, 'frozen', False):
             application_path = os.path.dirname(sys.executable)
        else:
             application_path = os.path.dirname(os.path.abspath(__file__))
        extract_to_path = os.path.join(application_path, "_internal")
        temp_zip_path = os.path.join(tempfile.gettempdir(), "texture_cache.zip")
        try:
            self.root.after(0, lambda: self.log_info(f"Downloading from: {url}"))
            urllib.request.urlretrieve(url, temp_zip_path)
            self.root.after(0, lambda: self.log_info("✓ Download complete. Extracting..."))
            if not os.path.exists(extract_to_path): os.makedirs(extract_to_path)
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to_path)
            try: os.remove(temp_zip_path)
            except: pass
            self.root.after(0, lambda: self._on_download_finished(True, "Texture cache downloaded successfully!"))
        except Exception as e:
            self.root.after(0, lambda: self._on_download_finished(False, f"Download failed: {str(e)}"))
    
    def _on_download_finished(self, success, message):
        self.is_downloading = False
        self.download_btn.config(state=tk.NORMAL, text="Download All Textures", bg=self.colors['accent_blue'])
        if success:
            messagebox.showinfo("Success", message)
            self.log_info(f"✅ {message}")
        else:
            messagebox.showerror("Error", message)
            self.log_info(f"❌ {message}")

    # NEW METHODS FOR GRID VIEW
    def open_grid_view(self):
        if not self.textures_folder:
            messagebox.showerror("Error", "No textures loaded.")
            return
        TextureGridPopup(self.root, self, self.filtered_textures, self.textures_folder, self.is_quest_textures)

    def select_texture_by_name(self, filename):
        if filename in self.filtered_textures:
            idx = self.filtered_textures.index(filename)
            self.file_list.selection_clear(0, tk.END)
            self.file_list.selection_set(idx)
            self.file_list.see(idx)
            self.on_texture_selected(None)

def main():
    root = tk.Tk()
    app = EchoVRTextureViewer(root)
    root.mainloop()

if __name__ == '__main__':
    main()