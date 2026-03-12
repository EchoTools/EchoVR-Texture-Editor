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
import webbrowser
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def get_cache_dir():
    # Check Settings folder first (Preferred)
    settings_path = get_settings_path("texture_cache")
    if os.path.exists(settings_path) and os.path.isdir(settings_path):
        return settings_path
    
    base = get_base_dir()
    # Check legacy/root location
    legacy_path = os.path.join(base, "texture_cache")
    if os.path.exists(legacy_path) and os.path.isdir(legacy_path):
        return legacy_path
        
    # Default to Settings folder
    return settings_path

CONFIG_FILE = get_settings_path("config.json")
CACHE_DIR = get_cache_dir()  # Store cache in Settings folder for persistence (or root if exists)
CACHE2_FILE = get_settings_path("cache2.json")
LEGACY_CACHE_FILE = get_settings_path("cache.json")
MAPPING_FILE = get_settings_path("texture_mapping.json")
NAMES_FILE = get_settings_path("names.json")

# --- CONSTANTS ---
PCVR_TEXTURE_ID = "beac1969cb7b8861"
PCVR_METADATA_ID = "4a4c32c49300b8a0"
QUEST_TEXTURE_ID = "489b7b69cb19e0e9"
QUEST_METADATA_ID = "e2ef0854d0cd69b8"

# App version for updates
APP_VERSION = "2.0.0"
GITHUB_REPO = "heisthecat31/EchoVR-Texture-Editor"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

DECODE_CACHE = {}


def compare_versions(v1, v2):
    """Compare two version strings (e.g., '1.0.0' vs '1.1.0'). Returns True if v2 > v1"""
    try:
        parts1 = [int(x) for x in v1.split('.')]
        parts2 = [int(x) for x in v2.split('.')]
        
        # Pad with zeros
        while len(parts1) < len(parts2):
            parts1.append(0)
        while len(parts2) < len(parts1):
            parts2.append(0)
        
        for p1, p2 in zip(parts1, parts2):
            if p2 > p1:
                return True
            elif p2 < p1:
                return False
        return False
    except:
        return False


def check_for_updates():
    """Check GitHub for latest release. Returns (has_update, latest_version, download_url) or (False, None, None)"""
    try:
        response = urllib.request.urlopen(GITHUB_API_URL, timeout=5)
        data = json.loads(response.read().decode('utf-8'))
        
        if 'tag_name' in data:
            latest_version = data['tag_name'].lstrip('v')  # Remove 'v' prefix if present
            download_url = data.get('html_url', '')  # Link to releases page
            
            if compare_versions(APP_VERSION, latest_version):
                return True, latest_version, download_url
    except Exception as e:
        pass  # Silent fail - don't break if network unavailable
    
    return False, None, None


def _dir_nonempty(path):
    """Return True if directory exists and has at least one entry (no full listdir)."""
    try:
        with os.scandir(path) as it:
            return next(it, None) is not None
    except (OSError, TypeError):
        return False


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
            except Exception:
                return subprocess.CompletedProcess(cmd, -1)
    else:
        try:
            if capture_output:
                return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
            else:
                return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, -1, "", "Timeout expired")
        except Exception:
            return subprocess.CompletedProcess(cmd, -1, "", "Command failed")

# --- CACHE MANAGER ---
class TextureCacheManager:
    @staticmethod
    def load_cache():
        if os.path.exists(CACHE2_FILE):
            try:
                with open(CACHE2_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    @staticmethod
    def save_cache(cache_data):
        try:
            with open(CACHE2_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def get_cached_files(folder_path):
        cache = TextureCacheManager.load_cache()
        if not cache: return None
        
        norm_path = os.path.normpath(folder_path).lower()
        for key in cache:
            if os.path.normpath(key).lower() == norm_path:
                return cache[key]
        return None

    @staticmethod
    def update_cache(folder_path, file_list):
        cache = TextureCacheManager.load_cache()
        cache[os.path.normpath(folder_path)] = file_list
        TextureCacheManager.save_cache(cache)

class ConfigManager:
    @staticmethod
    def load_config():
        base_dir = get_base_dir()
        settings_dir = os.path.join(base_dir, SETTINGS_DIR_NAME)
        
        if not os.path.exists(settings_dir):
            try:
                os.makedirs(settings_dir)
            except: pass
        
        default_config = {
            'output_folder': None,
            'data_folder': None,
            'extracted_folder': os.path.join(settings_dir, "pcvr-extracted"),
            'repacked_folder': os.path.join(settings_dir, "output-both"),
            'pcvr_input_folder': os.path.join(settings_dir, "input-pcvr"),
            'quest_input_folder': os.path.join(settings_dir, "input-quest"),
            'backup_folder': None,
            'renderdoc_path': None
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
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
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Config save error: {e}")

class NameManager:
    def __init__(self, path):
        self.mapping = {}
        self.load_names(path)

    def load_names(self, path):
        if not os.path.exists(path):
            return

        def is_hash(s):
            if not isinstance(s, str) or len(s) < 12:
                return False
            return all(c in '0123456789abcdef' for c in s.lower())

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, dict):
                for category, items in data.items():
                    if isinstance(items, list):
                        unnamed_counter = 1
                        i = 0
                        while i < len(items):
                            hash_key = items[i]
                            
                            if (i + 1) < len(items) and not is_hash(items[i+1]):
                                name = items[i+1]
                                self.mapping[hash_key.lower()] = name
                                i += 2
                            else:
                                if hash_key.lower() not in self.mapping:
                                    category_base = category[:-1] if category.endswith('s') else category
                                    category_base = category_base.replace('_', ' ').title()
                                    self.mapping[hash_key.lower()] = f"{category_base} {unnamed_counter}"
                                    unnamed_counter += 1
                                i += 1
        except Exception as e:
            print(f"Error loading names.json: {e}")

    def get_name(self, filename):
        # Normalize filename (lowercase, remove extension)
        filename_lower = filename.lower()
        base_name = os.path.splitext(filename_lower)[0]
        
        # Check mapping
        if base_name in self.mapping:
            return self.mapping[base_name]
        if filename_lower in self.mapping:
            return self.mapping[filename_lower]
            
        return filename

class ToolTip(object):
    """
    create a tooltip for a given widget
    """
    def __init__(self, widget, text='widget info'):
        self.waittime = 500     #miliseconds
        self.wraplength = 180   #pixels
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        self.id = None
        self.tw = None

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.waittime, self.showtip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x = y = 0
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        # creates a toplevel window
        self.tw = tk.Toplevel(self.widget)
        # Leaves only the label and removes the app window
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(self.tw, text=self.text, justify='left',
                       background="#ffffe0", relief='solid', borderwidth=1,
                       wraplength = self.wraplength,
                       font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tw
        self.tw= None
        if tw:
            tw.destroy()

class TutorialPopup:
    """Step-by-step guided tutorial with highlight boxes showing what to click in order."""
    HIGHLIGHT_BG = "#2d5a27"
    HIGHLIGHT_BORDER = 4
    PANEL_BG = "#333333"

    @staticmethod
    def _get_widget(app, attr):
        try:
            return getattr(app, attr, None)
        except Exception:
            return None

    @staticmethod
    def show(parent, app=None):
        if app is None:
            app = parent
        steps = [
            ("data_folder_btn", "Step 1: Data Folder", "Click the **Select** button next to Data Folder to choose your EchoVR game folder (the one containing 'manifests' and 'packages')."),
            ("extracted_folder_btn", "Step 2: Extracted Folder", "Click **Select** next to Extracted Folder to choose where extracted textures will be saved (e.g. a new empty folder)."),
            ("extract_btn", "Step 3: Extract Package", "Click **Extract Package**. Choose 'Textures Only' for a fast extract, or 'Full Package' if you need everything."),
            ("file_list", "Step 4: Texture List", "After extraction, textures appear here. Click one or more (Ctrl/Shift for multi-select) to choose which texture to replace."),
            ("replacement_canvas", "Step 5: Replacement Texture", "Click the **right canvas** (Replacement area) to open a file picker and choose your replacement image (PNG/DDS)."),
            ("replace_btn", "Step 6: Replace Texture", "Click **Replace Texture** to apply your replacement image to all selected textures. Files go to input-pcvr or input-quest."),
            ("repack_btn", "Step 7: Repack Modified", "After editing, click **Repack Modified** to build the output. Use the default 'output-both' folder when asked."),
            ("push_quest_btn", "Step 8: Deploy", "Quest: use **Push Files To Quest** to deploy. PCVR: use **Update EchoVR** in the header to copy files into your game folder."),
        ]
        panel = tk.Toplevel(parent)
        panel.title("Tutorial")
        panel.configure(bg=TutorialPopup.PANEL_BG)
        panel.resizable(False, False)
        panel.geometry("340x165")
        panel.transient(parent)
        panel.attributes("-topmost", True)
        try:
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 340) // 2)
            py = parent.winfo_rooty() + parent.winfo_height() - 185
            if py < parent.winfo_rooty():
                py = parent.winfo_rooty() + 20
            panel.geometry(f"+{px}+{py}")
        except Exception:
            pass
        current_step = [0]
        saved_style = {}

        def _clear_highlight():
            w = saved_style.get("widget")
            if w and w.winfo_exists():
                try:
                    for k, v in saved_style.get("config", {}).items():
                        try:
                            w.config(**{k: v})
                        except Exception:
                            pass
                except Exception:
                    pass
            saved_style.clear()

        def _apply_highlight(widget):
            if not widget or not widget.winfo_exists():
                return
            try:
                orig = {}
                for key in ("bg", "relief", "bd", "highlightbackground", "highlightthickness"):
                    try:
                        orig[key] = widget.cget(key)
                    except Exception:
                        pass
                saved_style["widget"] = widget
                saved_style["config"] = orig
                for attr, value in [
                    ("bg", TutorialPopup.HIGHLIGHT_BG),
                    ("relief", tk.SOLID),
                    ("bd", TutorialPopup.HIGHLIGHT_BORDER),
                    ("highlightbackground", "#4cd964"),
                    ("highlightthickness", TutorialPopup.HIGHLIGHT_BORDER),
                ]:
                    try:
                        widget.config(**{attr: value})
                    except Exception:
                        pass
            except Exception:
                saved_style.clear()

        def _go(step_index):
            _clear_highlight()
            current_step[0] = step_index
            idx = current_step[0]
            step_label.config(text=f"Step {idx + 1} of {len(steps)}")
            title_label.config(text=steps[idx][1])
            desc_label.config(text=steps[idx][2])
            widget = TutorialPopup._get_widget(app, steps[idx][0])
            _apply_highlight(widget)
            prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
            is_last = idx >= len(steps) - 1
            next_btn.config(state=tk.NORMAL, text="Close" if is_last else "Next →")

        def _next():
            if current_step[0] >= len(steps) - 1:
                _skip()
            else:
                _go(current_step[0] + 1)

        def _prev():
            if current_step[0] > 0:
                _go(current_step[0] - 1)

        def _skip():
            _clear_highlight()
            panel.destroy()

        content = tk.Frame(panel, bg=TutorialPopup.PANEL_BG, padx=10, pady=8)
        content.pack(fill=tk.BOTH, expand=True)
        step_label = tk.Label(content, text=f"Step 1 of {len(steps)}", font=("Arial", 8), fg="#888888", bg=TutorialPopup.PANEL_BG)
        step_label.pack(anchor="w")
        title_label = tk.Label(content, text=steps[0][1], font=("Arial", 10, "bold"), fg="#4cd964", bg=TutorialPopup.PANEL_BG, anchor="w")
        title_label.pack(fill=tk.X, pady=(2, 4))
        desc_label = tk.Label(content, text=steps[0][2], font=("Arial", 9), fg="#eeeeee", bg=TutorialPopup.PANEL_BG, justify=tk.LEFT, anchor="w", wraplength=310)
        desc_label.pack(fill=tk.X)
        btn_frame = tk.Frame(content, bg=TutorialPopup.PANEL_BG)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        prev_btn = tk.Button(btn_frame, text="← Prev", command=_prev, state=tk.DISABLED, bg="#4a4a4a", fg="#ffffff", font=("Arial", 8), relief=tk.RAISED, bd=1, padx=6, pady=4)
        prev_btn.pack(side=tk.LEFT, padx=(0, 6))
        next_btn = tk.Button(btn_frame, text="Next →", command=_next, bg="#4cd964", fg="#000000", font=("Arial", 8, "bold"), relief=tk.RAISED, bd=1, padx=6, pady=4)
        next_btn.pack(side=tk.LEFT, padx=(0, 6))
        skip_btn = tk.Button(btn_frame, text="Skip", command=_skip, bg="#555555", fg="#ffffff", font=("Arial", 8), relief=tk.RAISED, bd=1, padx=6, pady=4)
        skip_btn.pack(side=tk.RIGHT)
        panel.protocol("WM_DELETE_WINDOW", _skip)
        _go(0)

class ProgressDialog:
    """Simple progress dialog for long-running operations"""
    def __init__(self, parent, title="Processing", message="Please wait...", show_bar=True):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        height = 150 if show_bar else 100
        self.dialog.geometry(f"400x{height}")
        self.dialog.configure(bg='#1a1a1a')
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center on parent
        try:
            x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
            y = parent.winfo_y() + (parent.winfo_height() - 150) // 2
            self.dialog.geometry(f"+{x}+{y}")
        except:
            pass
        
        # Message label
        tk.Label(self.dialog, text=message, font=("Arial", 11), fg="#ffffff", bg='#1a1a1a').pack(pady=(20, 10))
        
        self.show_bar = show_bar
        if show_bar:
            # Progress bar
            self.progress = ttk.Progressbar(self.dialog, length=300, mode='determinate', value=0)
            self.progress.pack(pady=10, padx=50)
            
            # Status label
            self.status_label = tk.Label(self.dialog, text="0%", font=("Arial", 9), fg="#4cd964", bg='#1a1a1a')
            self.status_label.pack(pady=5)
        else:
            self.progress = None
            self.status_label = None
        
        # Cancel button
        self.cancel_requested = False
        self.cancel_btn = tk.Button(self.dialog, text="Cancel", command=self.request_cancel, 
                                   bg='#ff3b30', fg='#ffffff', font=("Arial", 9, "bold"), 
                                   relief=tk.RAISED, bd=2, padx=20, pady=5)
        self.cancel_btn.pack(pady=10)
        
        self.dialog.protocol("WM_DELETE_WINDOW", self.request_cancel)
    
    def update(self, current, total):
        """Update progress (0-100)"""
        if not self.dialog.winfo_exists():
            return False
        if self.show_bar and self.progress and self.status_label:
            percent = int((current / total) * 100) if total > 0 else 0
            self.progress['value'] = percent
            self.status_label.config(text=f"{percent}%")
        self.dialog.update_idletasks()
        return not self.cancel_requested
    
    def request_cancel(self):
        self.cancel_requested = True
        self.cancel_btn.config(state=tk.DISABLED, text="Cancelling...")
        self.dialog.update_idletasks()
    
    def close(self):
        """Close the progress dialog"""
        try:
            self.dialog.destroy()
        except:
            pass

class UpdateNotificationDialog:
    """Dialog for notifying user about app updates"""
    def __init__(self, parent, latest_version, download_url):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("📥 Update Available")
        self.dialog.geometry("500x250")
        self.dialog.configure(bg='#1a1a1a')
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center on parent
        try:
            x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
            y = parent.winfo_y() + (parent.winfo_height() - 250) // 2
            self.dialog.geometry(f"+{x}+{y}")
        except:
            pass
        
        # Title
        tk.Label(self.dialog, text="🎉 Update Available", font=("Arial", 14, "bold"), 
                fg="#4cd964", bg='#1a1a1a').pack(pady=(20, 10))
        
        # Version info
        info_text = f"A new version is available!\n\nCurrent: v{APP_VERSION}\nLatest: v{latest_version}\n\nClick 'Download' to visit the releases page."
        tk.Label(self.dialog, text=info_text, font=("Arial", 10), fg="#cccccc", bg='#1a1a1a', justify=tk.LEFT).pack(pady=10, padx=20)
        
        # Buttons frame
        btn_frame = tk.Frame(self.dialog, bg='#1a1a1a')
        btn_frame.pack(pady=20)
        
        download_btn = tk.Button(btn_frame, text="📥 Download", command=self.download, 
                                bg='#007aff', fg='#ffffff', font=("Arial", 10, "bold"), 
                                relief=tk.RAISED, bd=2, padx=20, pady=8)
        download_btn.pack(side=tk.LEFT, padx=5)
        
        remind_btn = tk.Button(btn_frame, text="Remind Later", command=self.dialog.destroy, 
                              bg='#4a4a4a', fg='#ffffff', font=("Arial", 10), 
                              relief=tk.RAISED, bd=2, padx=20, pady=8)
        remind_btn.pack(side=tk.LEFT, padx=5)
        
        self.download_url = download_url
    
    def download(self):
        """Open download page in default browser"""
        try:
            webbrowser.open(self.download_url)
            self.dialog.destroy()
        except:
            messagebox.showerror("Error", "Could not open browser. Please visit:\n" + self.download_url)

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
            self.config['backup_folder'] = result
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
        
        # Show progress dialog
        progress = ProgressDialog(self.popup, "Updating Game Files", "Moving files to game folder...")
        
        # Start Thread
        threading.Thread(target=self.update_packages_thread, args=(output_folder, data_folder, progress), daemon=True).start()

    def update_packages_thread(self, output_folder, data_folder, progress):
        try:
            files_moved = 0
            total_files = 0
            
            # Count total files first
            for folder in ['packages', 'manifests']:
                src_path = os.path.join(output_folder, folder)
                if os.path.exists(src_path):
                    total_files += len([f for f in os.listdir(src_path) if os.path.isfile(os.path.join(src_path, f))])
            
            if total_files == 0:
                total_files = 1  # Avoid division by zero
            
            # Move files
            for folder in ['packages', 'manifests']:
                src_path = os.path.join(output_folder, folder)
                dst_path = os.path.join(data_folder, folder)
                
                if os.path.exists(src_path):
                    os.makedirs(dst_path, exist_ok=True)
                    
                    for filename in os.listdir(src_path):
                        if not progress.update(files_moved, total_files):
                            self.popup.after(0, lambda: self.on_update_complete(False, "Operation cancelled"))
                            return
                        
                        src_file = os.path.join(src_path, filename)
                        dst_file = os.path.join(dst_path, filename)
                        
                        if os.path.isfile(src_file):
                            shutil.move(src_file, dst_file)
                            files_moved += 1
            
            progress.update(total_files, total_files)
            
            try:
                for folder in ['packages', 'manifests']:
                    folder_path = os.path.join(output_folder, folder)
                    if os.path.exists(folder_path):
                        shutil.rmtree(folder_path)
            except Exception as wipe_error:
                self.popup.after(0, lambda: self.log_info(f"⚠ Could not completely wipe output-both: {wipe_error}"))
            
            self.popup.after(0, lambda: self.on_update_complete(True, files_moved, progress))

        except Exception as e:
            self.popup.after(0, lambda: self.on_update_complete(False, str(e), progress))

    def on_update_complete(self, success, result, progress=None):
        if progress:
            progress.close()
        
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


class ModificationsViewerPopup:
    """Shows modified textures with checkboxes + a live thumbnail grid. Metadata is hidden
    but automatically toggled alongside its paired texture file."""

    TEXTURE_IDS = {PCVR_TEXTURE_ID, QUEST_TEXTURE_ID}
    METADATA_IDS = {PCVR_METADATA_ID, QUEST_METADATA_ID}
    TEXTURE_TO_META = {
        PCVR_TEXTURE_ID: PCVR_METADATA_ID,
        QUEST_TEXTURE_ID: QUEST_METADATA_ID,
    }

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app

        self.popup = tk.Toplevel(parent)
        self.popup.title("View Existing Modifications")
        self.popup.geometry("1100x600")
        self.popup.configure(bg='#1a1a1a')
        self.popup.resizable(True, True)
        self.popup.transient(parent)
        self.popup.grab_set()

        try:
            x = parent.winfo_x() + (parent.winfo_width() - 1100) // 2
            y = parent.winfo_y() + (parent.winfo_height() - 600) // 2
            self.popup.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self._platforms = self._resolve_platforms()
        self._status_var = tk.StringVar(value="")
        self._loaded_images = {}
        self._thumb_size = 120
        self._all_items = []
        self._row_widgets = {}
        # Keyed by (plat_label, rel_path) → (BooleanVar, list_label, input_dir, backup_dir)
        self._key_to_toggle = {}

        self._build_ui()

    # ── Platform resolution ──────────────────────────────────────────────
    def _resolve_platforms(self):
        base = get_base_dir()
        settings_dir = os.path.join(base, SETTINGS_DIR_NAME)
        backups_root = os.path.join(settings_dir, "mod_backups")
        pcvr_dir = getattr(self.app, 'pcvr_input_folder', None) or os.path.join(settings_dir, "input-pcvr")
        quest_dir = getattr(self.app, 'quest_input_folder', None) or os.path.join(settings_dir, "input-quest")
        is_pcvr = getattr(self.app, 'is_pcvr_textures', False)
        is_quest = getattr(self.app, 'is_quest_textures', False)
        if is_pcvr and not is_quest:
            return [("PCVR", pcvr_dir, os.path.join(backups_root, "pcvr"))]
        elif is_quest and not is_pcvr:
            return [("Quest", quest_dir, os.path.join(backups_root, "quest"))]
        else:
            return [
                ("PCVR", pcvr_dir, os.path.join(backups_root, "pcvr")),
                ("Quest", quest_dir, os.path.join(backups_root, "quest")),
            ]

    # ── File scanning ────────────────────────────────────────────────────
    def _scan_all(self, input_dir, backup_dir):
        """Walk input_dir and backup_dir; return dict with 'Textures' and 'Misc' keys.
        Metadata files are intentionally excluded from the returned dict.
        Each entry: (rel_path, enabled:bool, abs_path)
        """
        cats = {'Textures': [], 'Misc': []}
        seen = set()
        for (root_dir, enabled) in [(input_dir, True), (backup_dir, False)]:
            if not os.path.isdir(root_dir):
                continue
            for dirpath, _, filenames in os.walk(root_dir):
                for fname in filenames:
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, root_dir)
                    if rel_path in seen:
                        continue
                    seen.add(rel_path)
                    top = rel_path.split(os.sep)[0] if os.sep in rel_path else ""
                    if top in self.METADATA_IDS:
                        continue  # hide metadata from UI
                    if top in self.TEXTURE_IDS:
                        cats['Textures'].append((rel_path, enabled, abs_path))
                    else:
                        cats['Misc'].append((rel_path, enabled, abs_path))
        cats['Textures'].sort()
        cats['Misc'].sort()
        return cats

    def _find_paired_meta(self, tex_rel, input_dir, backup_dir, currently_enabled):
        """Return (meta_rel_path, absolute_path) of the paired metadata file, or (None, None)."""
        parts = tex_rel.split(os.sep)
        meta_folder = self.TEXTURE_TO_META.get(parts[0]) if parts else None
        if not meta_folder:
            return None, None
        meta_rel = os.path.join(meta_folder, *parts[1:])
        check_dir = input_dir if currently_enabled else backup_dir
        candidate = os.path.join(check_dir, meta_rel)
        if os.path.exists(candidate):
            return meta_rel, candidate
        return None, None

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.popup, bg='#1a1a1a')
        hdr.pack(fill=tk.X, padx=14, pady=(12, 6))
        tk.Label(hdr, text="Existing Modifications", font=("Arial", 13, "bold"),
                 fg="#4cd964", bg='#1a1a1a').pack(side=tk.LEFT)
        tk.Label(hdr, text="   Uncheck to disable · check to re-enable   (metadata moves automatically)",
                 font=("Arial", 9), fg="#aaaaaa", bg='#1a1a1a').pack(side=tk.LEFT)

        # Split pane: left list | right grid
        pane = tk.Frame(self.popup, bg='#1a1a1a')
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        pane.columnconfigure(0, weight=0, minsize=300)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)

        # ---- Left: scrollable checklist ----
        list_outer = tk.Frame(pane, bg='#242424', relief=tk.GROOVE, bd=1)
        list_outer.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        list_canvas = tk.Canvas(list_outer, bg='#242424', highlightthickness=0, width=290)
        list_sb = tk.Scrollbar(list_outer, orient="vertical", command=list_canvas.yview)
        self._list_frame = tk.Frame(list_canvas, bg='#242424')
        self._list_frame.bind("<Configure>",
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        list_canvas.configure(yscrollcommand=list_sb.set)
        list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_sb.pack(side=tk.RIGHT, fill=tk.Y)
        list_canvas.bind("<MouseWheel>",
            lambda e: list_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # ---- Right: thumbnail grid ----
        grid_outer = tk.LabelFrame(pane, text=" Texture Preview ",
                                   font=("Arial", 9, "bold"), fg="#4cd964",
                                   bg='#1a1a1a', relief=tk.GROOVE, bd=1)
        grid_outer.grid(row=0, column=1, sticky='nsew')
        grid_canvas = tk.Canvas(grid_outer, bg='#1a1a1a', highlightthickness=0)
        grid_sb = tk.Scrollbar(grid_outer, orient="vertical", command=grid_canvas.yview)
        self._grid_frame = tk.Frame(grid_canvas, bg='#1a1a1a')
        self._grid_frame.bind("<Configure>",
            lambda e: grid_canvas.configure(scrollregion=grid_canvas.bbox("all")))
        grid_canvas.create_window((0, 0), window=self._grid_frame, anchor="nw")
        grid_canvas.configure(yscrollcommand=grid_sb.set)
        grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        grid_sb.pack(side=tk.RIGHT, fill=tk.Y)
        grid_canvas.bind("<MouseWheel>",
            lambda e: grid_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Populate left list and collect all items for the grid
        any_files = False
        for (plat_label, input_dir, backup_dir) in self._platforms:
            cats = self._scan_all(input_dir, backup_dir)
            total = sum(len(v) for v in cats.values())
            if total == 0:
                continue
            any_files = True
            self._build_list_section(plat_label, cats, input_dir, backup_dir)
            for cat_items in cats.values():
                for it in cat_items:
                    # key = (plat_label, rel_path) to avoid cross-platform collisions
                    self._all_items.append(it + (input_dir, backup_dir, plat_label))

        if not any_files:
            tk.Label(self._list_frame, text="No texture modifications found.",
                     font=("Arial", 10), fg="#888888", bg='#242424').pack(pady=30, padx=10)

        # Bottom bar
        bot = tk.Frame(self.popup, bg='#1a1a1a')
        bot.pack(fill=tk.X, padx=10, pady=(2, 8))
        tk.Label(bot, textvariable=self._status_var, font=("Arial", 9), fg="#4cd964",
                 bg='#1a1a1a', anchor="w", wraplength=900).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(bot, text="Close", command=self.popup.destroy,
                  bg='#4a4a4a', fg='#ffffff', font=("Arial", 9, "bold"),
                  relief=tk.RAISED, bd=2, padx=20, pady=5).pack(side=tk.RIGHT)

        if self._all_items:
            self.popup.after(200, self._load_grid_thumbnails)

    def _build_list_section(self, plat_label, cats, input_dir, backup_dir):
        """Build a platform section with Textures and Misc sub-sections."""
        section = tk.LabelFrame(self._list_frame, text=f"  {plat_label}  ",
                                font=("Arial", 9, "bold"), fg="#ffffff",
                                bg='#242424', relief=tk.GROOVE, bd=1)
        section.pack(fill=tk.X, padx=4, pady=4)

        for cat_name in ('Textures', 'Misc'):
            items = cats.get(cat_name, [])
            if not items:
                continue
            cat_lbl = tk.Label(section,
                               text=f"{cat_name} ({sum(1 for r, e, a in items if e)} enabled / {len(items)} total)",
                               font=("Arial", 8, "bold"), fg="#4cd964", bg='#242424', anchor='w')
            cat_lbl.pack(fill=tk.X, padx=6, pady=(4, 0))
            for (rel_path, enabled, _abs) in items:
                row = tk.Frame(section, bg='#242424')
                row.pack(fill=tk.X, padx=8, pady=1)
                var = tk.BooleanVar(value=enabled)
                lbl = tk.Label(row, text=os.path.basename(rel_path), font=("Arial", 9),
                               anchor='w', fg='#cccccc' if enabled else '#888888', bg='#242424')
                lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
                ToolTip(lbl, rel_path)
                tk.Checkbutton(row, variable=var, bg='#242424', activebackground='#242424',
                               selectcolor='#1a1a1a',
                               command=lambda rp=rel_path, v=var, l=lbl,
                                              inp=input_dir, bkp=backup_dir:
                                   self._toggle_mod(rp, v, l, inp, bkp)
                               ).pack(side=tk.RIGHT)
                self._row_widgets[rel_path] = lbl
                # Store toggle state so thumbnail clicks can trigger the same action
                self._key_to_toggle[(plat_label, rel_path)] = (var, lbl, input_dir, backup_dir)

    # ── Move logic ───────────────────────────────────────────────────────
    def _click_thumb(self, key):
        """Called when the user clicks a thumbnail in the grid.
        key = (plat_label, rel_path).  Looks up the corresponding BooleanVar
        and list-label, flips the toggle, then delegates to _toggle_mod.
        """
        state = self._key_to_toggle.get(key)
        if state is None:
            return
        var, lbl, input_dir, backup_dir = state
        # Flip the var (simulates checking/unchecking the list checkbox)
        var.set(not var.get())
        self._toggle_mod(key[1], var, lbl, input_dir, backup_dir)

    def _move_file(self, rel_path, enabling, input_dir, backup_dir):
        """Move rel_path from backup→input (enabling=True) or input→backup (enabling=False).
        Returns True on success."""
        src = os.path.join(backup_dir if enabling else input_dir, rel_path)
        dst = os.path.join(input_dir if enabling else backup_dir, rel_path)
        if not os.path.exists(src):
            return False
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        # Prune empty dirs from input side when disabling
        if not enabling:
            p = os.path.dirname(os.path.join(input_dir, rel_path))
            while os.path.normpath(p) != os.path.normpath(input_dir):
                try:
                    if not os.listdir(p):
                        os.rmdir(p)
                    else:
                        break
                except OSError:
                    break
                p = os.path.dirname(p)
        return True

    def _toggle_mod(self, rel_path, var, lbl_widget, input_dir, backup_dir):
        enabling = var.get()  # True = user just checked it (wants it enabled)
        # Before the move, the file was in the opposite location
        was_enabled = not enabling
        try:
            if not self._move_file(rel_path, enabling, input_dir, backup_dir):
                self._status_var.set(f"⚠ Source not found: {os.path.basename(rel_path)}")
                var.set(was_enabled)
                return
            # Auto-move paired metadata
            meta_rel, _ = self._find_paired_meta(rel_path, input_dir, backup_dir, was_enabled)
            if meta_rel:
                try:
                    self._move_file(meta_rel, enabling, input_dir, backup_dir)
                except Exception:
                    pass
            action = "enabled" if enabling else "disabled"
            self._status_var.set(f"✓ {os.path.basename(rel_path)} {action}.")
            lbl_widget.config(fg='#cccccc' if enabling else '#888888')
            self._refresh_grid()
        except Exception as exc:
            self._status_var.set(f"✗ Error: {exc}")
            var.set(was_enabled)

    # ── Thumbnail grid ───────────────────────────────────────────────────
    def _clear_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._loaded_images.clear()

    def _refresh_grid(self):
        self._clear_grid()
        # Re-scan and collect only enabled textures+misc, keyed by (plat, rel_path) to avoid duplication
        seen_keys = set()
        enabled_items = []
        for (plat_label, input_dir, backup_dir) in self._platforms:
            cats = self._scan_all(input_dir, backup_dir)
            for cat_items in cats.values():
                for (rel_path, enabled, abs_path) in cat_items:
                    if not enabled:
                        continue
                    key = (plat_label, rel_path)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    enabled_items.append((key, abs_path))
        if enabled_items:
            threading.Thread(target=self._load_thumbs, args=(enabled_items,), daemon=True).start()
        else:
            tk.Label(self._grid_frame, text="No enabled modifications.",
                     font=("Arial", 10), fg="#888888", bg='#1a1a1a'
                     ).grid(row=0, column=0, padx=20, pady=20)

    def _load_grid_thumbnails(self):
        """Initial thumbnail load — only enabled textures+misc, deduplicated by (plat, rel_path)."""
        seen_keys = set()
        items = []
        for (rp, en, ap, _inp, _bkp, plat) in self._all_items:
            if not en:
                continue
            key = (plat, rp)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            items.append((key, ap))
        if not items:
            self.popup.after(0, lambda: tk.Label(
                self._grid_frame, text="No enabled modifications to preview.",
                font=("Arial", 10), fg="#888888", bg='#1a1a1a'
            ).grid(row=0, column=0, padx=20, pady=20))
            return
        threading.Thread(target=self._load_thumbs, args=(items,), daemon=True).start()

    def _load_thumbs(self, items):
        """Background thread: load each texture and place contiguously in the grid.
        items = list of ((plat, rel_path), abs_path)
        Uses display_idx (not item idx) so skipped files never create gaps.
        """
        COLS = 4
        display_idx = 0
        for (key, abs_path) in items:
            if not os.path.exists(abs_path):
                continue
            try:
                img = self._read_texture_direct(abs_path)
                if img is None:
                    continue
                img.thumbnail((self._thumb_size, self._thumb_size), Image.Resampling.LANCZOS)
                r, c = divmod(display_idx, COLS)
                rel_path = key[1]  # rel_path part of the key tuple
                self.popup.after(0, lambda i=img, k=key, row=r, col=c:
                                 self._add_thumb(i, k, row, col))
                display_idx += 1
            except Exception:
                continue

    def _read_texture_direct(self, abs_path):
        """Load a texture file skipping texture_cache. Returns PIL Image or None."""
        try:
            return Image.open(abs_path).convert("RGBA")
        except Exception:
            pass
        # Fallback: texconv for BC6/BC7 formats
        texconv_path = get_tool_path("texconv.exe")
        if texconv_path and os.path.exists(texconv_path):
            try:
                with tempfile.TemporaryDirectory(prefix="modview_") as tmp:
                    tmp_in = os.path.join(tmp, os.path.basename(abs_path))
                    shutil.copy2(abs_path, tmp_in)
                    run_hidden_command([texconv_path, "-ft", "png", "-o", tmp, "-y", tmp_in], timeout=15)
                    out = os.path.join(tmp, os.path.splitext(os.path.basename(tmp_in))[0] + ".png")
                    if os.path.exists(out):
                        return Image.open(out).convert("RGBA")
            except Exception:
                pass
        return None

    def _add_thumb(self, img, key, row, col):
        """key = (plat_label, rel_path). Click on the cell to toggle enable/disable."""
        if not self.popup.winfo_exists():
            return
        try:
            photo = ImageTk.PhotoImage(img)
            self._loaded_images[key] = photo  # keyed by (plat, rel_path) — no collision

            cell = tk.Frame(self._grid_frame, bg='#2a2a2a', relief=tk.GROOVE, bd=1,
                            cursor='hand2')
            cell.grid(row=row, column=col, padx=5, pady=5, sticky='n')

            img_lbl = tk.Label(cell, image=photo, bg='#2a2a2a', borderwidth=0,
                               cursor='hand2')
            img_lbl.pack()

            name = os.path.basename(key[1])
            short = name[:14] + "\u2026" if len(name) > 14 else name
            name_lbl = tk.Label(cell, text=short, font=("Arial", 8), fg='#aaaaaa',
                                bg='#2a2a2a', cursor='hand2')
            name_lbl.pack(fill=tk.X)
            ToolTip(name_lbl, f"[{key[0]}] {key[1]}\nClick to enable/disable")

            # Hover highlight
            def _enter(e, c=cell):
                c.config(bg='#3a3a3a')
            def _leave(e, c=cell):
                c.config(bg='#2a2a2a')
            for w in (cell, img_lbl, name_lbl):
                w.bind('<Enter>', _enter)
                w.bind('<Leave>', _leave)

            # Click = toggle enable/disable (same action as the list checkbox)
            def _click(e, k=key):
                self._click_thumb(k)
            for w in (cell, img_lbl, name_lbl):
                w.bind('<Button-1>', _click)

        except Exception:
            pass




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
    
    def extract_package(self, data_dir, package_name, output_dir, export_type=""):
        if not self.tool_path:
            return False, "evrFileTools.exe not found"
        
        try:
            cmd = [
                self.tool_path, "-mode", "extract", "-package", package_name,
                "-data", data_dir, "-output", output_dir,
                "-force"
            ]
            if export_type:
                cmd.extend(["--export", export_type])
                cmd.extend(["-export", export_type])
            
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
    
    def repack_package(self, output_dir, package_name, data_dir, input_dir, quick_mode=False):
        if not self.tool_path:
            return False, "evrFileTools.exe not found"
        
        try:
            cmd = [
                self.tool_path, "-mode", "build",
                "-package", package_name,
                "-data", data_dir,
                "-input", input_dir, "-output", output_dir,
                "-force"
            ]
            if quick_mode:
                cmd.append("-quick")
            
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
        0: "DXGI_FORMAT_UNKNOWN", 26: "DXGI_FORMAT_R11G11B10_FLOAT", 61: "DXGI_FORMAT_R8_UNORM",
        71: "DXGI_FORMAT_BC1_UNORM", 77: "DXGI_FORMAT_BC3_UNORM", 
        80: "DXGI_FORMAT_BC4_UNORM", 83: "DXGI_FORMAT_BC5_UNORM",
        91: "DXGI_FORMAT_B8G8R8A8_UNORM_SRGB",
        87: "DXGI_FORMAT_B8G8R8A8_TYPELESS",
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
                        if format_code in [26, 72, 78, 87]: is_problematic = True
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
    CACHE_MAX_FILES = 1000  # Limit cache to 1000 files to prevent disk bloat
    
    @staticmethod
    def get_cache_path(texture_path):
        # CACHE_DIR is now an absolute path from get_settings_path()
        os.makedirs(CACHE_DIR, exist_ok=True)
        original_name = os.path.basename(texture_path)
        png_name = os.path.splitext(original_name)[0] + ".png"
        return os.path.join(CACHE_DIR, png_name)
    
    @staticmethod
    def cleanup_cache():
        """Placeholder - cache cleanup disabled to protect user files"""
        # Cache files are now protected and never deleted by the app
        # Users must manually delete cache files if needed
        pass
    
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
                    # Only save to cache if file doesn't already exist (never overwrite)
                    if not os.path.exists(cache_path):
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
                # Only save to cache if file doesn't already exist (never overwrite)
                if not os.path.exists(cache_path):
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
            cmd = [texconv_path, "decode", temp_input.name, converted_file]
            result = run_hidden_command(cmd)
            
            if os.path.exists(converted_file):
                img = Image.open(converted_file).convert("RGBA")
                if cache_path:
                    # Only save to cache if file doesn't already exist (never overwrite)
                    if not os.path.exists(cache_path):
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
    def convert_to_dds(source_path, target_width, target_height):
        """Convert image to DDS using the bundled texconv. Returns (output_dds_path, file_size) or (None, 0) on failure."""
        texconv_path = get_tool_path("texconv.exe")
        if not texconv_path or not os.path.exists(texconv_path):
            return None, 0
        try:
            img = Image.open(source_path).convert("RGBA")
            if img.width != target_width or img.height != target_height:
                img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            
            with tempfile.TemporaryDirectory(prefix="pcvr_dds_") as tmp:
                temp_png = os.path.join(tmp, "temp.png")
                img.save(temp_png, "PNG")
                
                out_dds = os.path.join(tmp, "output.dds")
                
                # Correctly call the Go texconv tool, which uses 'encode <in> <out>'
                cmd = [texconv_path, "encode", temp_png, out_dds]
                result = run_hidden_command(cmd, timeout=60)

                if result.returncode != 0:
                    return None, 0 # Conversion failed

                if not os.path.isfile(out_dds):
                    return None, 0 # Output file not created

                size = os.path.getsize(out_dds)
                base = os.path.splitext(os.path.basename(source_path))[0]
                final_path = os.path.join(tempfile.gettempdir(), f"pcvr_replace_{os.getpid()}_{base}.dds")
                shutil.copy2(out_dds, final_path)
                return final_path, size
        except Exception:
            return None, 0

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
    def replace_pcvr_texture(output_folder, pcvr_input_folder, original_texture_path, replacement_texture_path, replacement_size=None):
        try:
            orig_info = DDSHandler.get_dds_info(original_texture_path)
            if not orig_info or 'width' not in orig_info:
                return False, "Could not read original texture dimensions"
            target_w = orig_info['width']
            target_h = orig_info['height']

            is_dds = replacement_texture_path.lower().endswith(".dds") and os.path.isfile(replacement_texture_path)
            repl_info = DDSHandler.get_dds_info(replacement_texture_path) if is_dds else None
            needs_convert = not is_dds or (repl_info and (repl_info.get('width') != target_w or repl_info.get('height') != target_h))
            if needs_convert or not is_dds:
                dds_path, replacement_size = TextureReplacer.convert_to_dds(replacement_texture_path, target_w, target_h)
                if dds_path is None:
                    return False, "DDS conversion via texconv.exe failed. Check tool and file paths."
            else:
                dds_path = replacement_texture_path
                if replacement_size is None:
                    replacement_size = os.path.getsize(replacement_texture_path)

            input_textures_folder = os.path.join(pcvr_input_folder, PCVR_TEXTURE_ID)
            input_corresponding_folder = os.path.join(pcvr_input_folder, PCVR_METADATA_ID)
            os.makedirs(input_textures_folder, exist_ok=True)
            os.makedirs(input_corresponding_folder, exist_ok=True)

            texture_name = os.path.basename(original_texture_path)
            output_corresponding_file = os.path.join(output_folder, PCVR_METADATA_ID, texture_name)
            input_texture_path = os.path.join(input_textures_folder, texture_name)
            input_corresponding_path = os.path.join(input_corresponding_folder, texture_name)

            shutil.copy2(dds_path, input_texture_path)
            if dds_path != replacement_texture_path and os.path.isfile(dds_path):
                try:
                    os.remove(dds_path)
                except Exception:
                    pass

            if os.path.exists(output_corresponding_file):
                shutil.copy2(output_corresponding_file, input_corresponding_path)
                if TextureReplacer.hex_edit_file_size(input_corresponding_path, replacement_size):
                    return True, f"PCVR texture replaced. Size updated to {replacement_size} bytes."
                return False, "Failed to update file size"
            return False, "Corresponding file not found"
        except Exception as e:
            return False, f"PCVR replacement error: {str(e)}"

    @staticmethod
    def replace_quest_texture(output_folder, quest_input_folder, original_texture_path, replacement_texture_path, texture_cache):
        try:
            input_textures_folder = os.path.join(quest_input_folder, QUEST_TEXTURE_ID)
            input_corresponding_folder = os.path.join(quest_input_folder, QUEST_METADATA_ID)
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
            
            # Update corresponding metadata file size
            output_corresponding_file = os.path.join(output_folder, QUEST_METADATA_ID, texture_name)
            if os.path.exists(output_corresponding_file):
                input_corresponding_path = os.path.join(input_corresponding_folder, texture_name)
                shutil.copy2(output_corresponding_file, input_corresponding_path)
                TextureReplacer.hex_edit_file_size(input_corresponding_path, final_size)
        
            
            try: os.remove(temp_output)
            except: pass
            return True, f"Quest texture replaced. Size updated to {final_size} bytes."
        except Exception as e:
            return False, f"Quest replacement error: {str(e)}"

# --- NEW GRID POPUP CLASS WITH PAGINATION ---
class TextureGridPopup:
    GRID_COLS = 8
    ROWS_PER_PAGE = 12
    TEXTURES_PER_PAGE = GRID_COLS * ROWS_PER_PAGE
    THUMB_SIZE = (100, 100)
    
    def __init__(self, parent, app, image_files, folder_path, is_quest):
        self.parent = parent
        self.app = app
        self.image_files = image_files
        self.folder_path = folder_path
        self.is_quest = is_quest
        
        self.window = tk.Toplevel(parent)
        self.window.title(f"Texture Gallery ({len(image_files)} total)")
        self.window.geometry("1000x800")
        self.window.configure(bg='#1a1a1a')
        
        self.loaded_images = {}
        self.current_page = 0
        self.total_pages = max(1, (len(image_files) + self.TEXTURES_PER_PAGE - 1) // self.TEXTURES_PER_PAGE)
        self.loading_generation = 0  # To invalidate old threads
        
        # Store texture metadata for sorting
        self.texture_info = {}  # filename -> {'width': int, 'height': int, 'pixels': int, 'size': int}
        self.sort_mode = "name"  # name, width, height, pixels
        
        self.setup_ui()
        self.load_page(0)

    def setup_ui(self):
        top_frame = tk.Frame(self.window, bg='#2a2a2a', height=60)
        top_frame.pack(fill=tk.X)
        
        # Info and sort controls
        info_label = tk.Label(top_frame, text="Click an image to select it", fg='#cccccc', bg='#2a2a2a', font=("Arial", 9))
        info_label.pack(side=tk.LEFT, padx=10, pady=5)
        
        sort_label = tk.Label(top_frame, text="Sort by:", fg='#ffffff', bg='#2a2a2a', font=("Arial", 9))
        sort_label.pack(side=tk.RIGHT, padx=(10, 5), pady=5)
        
        self.sort_var = tk.StringVar(value="name")
        self.sort_dropdown = ttk.Combobox(top_frame, textvariable=self.sort_var, 
                                         values=["Name", "Pixels (Large to Small)", "Pixels (Small to Large)"],
                                         state="readonly", width=20, font=("Arial", 9))
        self.sort_dropdown.pack(side=tk.RIGHT, padx=(0, 10), pady=5)
        self.sort_dropdown.bind('<<ComboboxSelected>>', self.on_sort_change)
        
        # Navigation Frame (Bottom)
        nav_frame = tk.Frame(self.window, bg='#2a2a2a', height=50)
        nav_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.prev_btn = tk.Button(nav_frame, text="<< Previous", command=self.prev_page, 
                                 bg='#4a4a4a', fg='#ffffff', font=("Arial", 9, "bold"), relief=tk.RAISED, bd=1, state=tk.DISABLED)
        self.prev_btn.pack(side=tk.LEFT, padx=20, pady=10)
        
        self.page_label = tk.Label(nav_frame, text=f"Page 1 / {self.total_pages}", font=("Arial", 10, "bold"), fg='#ffffff', bg='#2a2a2a')
        self.page_label.pack(side=tk.LEFT, expand=True)
        
        self.next_btn = tk.Button(nav_frame, text="Next >>", command=self.next_page, 
                                 bg='#4a4a4a', fg='#ffffff', font=("Arial", 9, "bold"), relief=tk.RAISED, bd=1)
        self.next_btn.pack(side=tk.RIGHT, padx=20, pady=10)
        
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

    def prev_page(self):
        if self.current_page > 0:
            self.load_page(self.current_page - 1)
            
    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.load_page(self.current_page + 1)

    def load_page(self, page_num):
        self.current_page = page_num
        self.loading_generation += 1
        current_gen = self.loading_generation
        
        # Update controls
        self.page_label.config(text=f"Page {page_num + 1} / {self.total_pages}")
        self.prev_btn.config(state=tk.NORMAL if page_num > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if page_num < self.total_pages - 1 else tk.DISABLED)
        
        # Clear grid
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.loaded_images.clear()
        self.canvas.yview_moveto(0)
        
        start_idx = page_num * self.TEXTURES_PER_PAGE
        end_idx = min(start_idx + self.TEXTURES_PER_PAGE, len(self.image_files))
        
        # Show loading indicator
        loading_lbl = tk.Label(self.scroll_frame, text="Loading...", fg="white", bg="#1a1a1a")
        loading_lbl.grid(row=0, column=0, columnspan=self.GRID_COLS, pady=20)
        
        threading.Thread(target=self._load_page_worker, args=(start_idx, end_idx, current_gen, loading_lbl), daemon=True).start()

    def _load_page_worker(self, start_idx, end_idx, generation, loading_lbl):
        for idx in range(start_idx, end_idx):
            if not self.window.winfo_exists() or self.loading_generation != generation:
                return
            
            filename = self.image_files[idx]
            file_path = os.path.join(self.folder_path, filename)
            
            try:
                img = TextureLoader.load_texture(file_path, self.is_quest)
                if img:
                    img.thumbnail(self.THUMB_SIZE)
                    
                    # Calculate row/col relative to this page
                    rel_idx = idx - start_idx
                    row = rel_idx // self.GRID_COLS
                    col = rel_idx % self.GRID_COLS
                    
                    self.window.after(0, lambda i=img, f=filename, r=row, c=col: self.add_thumbnail(i, f, r, c))
            except Exception:
                pass
        
        self.window.after(0, lambda: loading_lbl.destroy())

    def add_thumbnail(self, img, filename, row, col):
        """Add a thumbnail to the grid"""
        if not self.window.winfo_exists():
            return
        
        try:
            # Store texture resolution info
            self.texture_info[filename] = {
                'width': img.width,
                'height': img.height,
                'pixels': img.width * img.height,
                'size': os.path.getsize(os.path.join(self.folder_path, filename))
            }
            
            photo = ImageTk.PhotoImage(img)
            self.loaded_images[filename] = photo
            
            frame = tk.Frame(self.scroll_frame, bg='#333333', bd=1, relief=tk.SOLID)
            frame.grid(row=row, column=col, padx=4, pady=4, sticky='nsew')
            
            btn = tk.Button(frame, image=photo, command=lambda f=filename: self.on_click(f), bg='#1a1a1a', borderwidth=0)
            btn.image = photo
            btn.pack()
            
            label = tk.Label(frame, text=filename[:12]+"...", font=("Arial", 8), fg='#aaaaaa', bg='#333333')
            display_name = self.app.name_manager.get_name(filename)
            label_text = display_name[:15] + "..." if len(display_name) > 15 else display_name
            label = tk.Label(frame, text=label_text, font=("Arial", 8), fg='#aaaaaa', bg='#333333')
            label.pack(fill=tk.X)
        except Exception:
            pass
    
    def on_sort_change(self, event=None):
        """Handle sort mode change"""
        sort_selection = self.sort_var.get()
        
        # Sort image_files based on selected mode
        if sort_selection == "Name":
            self.image_files.sort()
        elif sort_selection == "Pixels (Large to Small)":
            self.image_files.sort(key=lambda f: self.texture_info.get(f, {}).get('pixels', 0), reverse=True)
        elif sort_selection == "Pixels (Small to Large)":
            self.image_files.sort(key=lambda f: self.texture_info.get(f, {}).get('pixels', 0), reverse=False)
        
        # Reload page 0
        self.load_page(0)

class EchoVRTextureViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("EchoVR Texture Editor - PCVR & Quest Support")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600)
        
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
        
        self.ensure_settings_folders()
        self.name_manager = NameManager(NAMES_FILE)
        self.setup_ui()
        self.auto_detect_folders()
        self.check_external_tools()
        
        if self.output_folder and os.path.exists(self.output_folder):
            self.set_output_folder(self.output_folder)
        if self.data_folder and os.path.exists(self.data_folder):
            self.set_data_folder(self.data_folder)
        if self.extracted_folder and os.path.exists(self.extracted_folder):
            self.set_extracted_folder(self.extracted_folder)
            
        # Save defaults to config if they were missing
        ConfigManager.save_config(**self.config)
    
    def ensure_settings_folders(self):
        base_dir = get_base_dir()
        settings_dir = os.path.join(base_dir, SETTINGS_DIR_NAME)
        
        folders = [
            "input-pcvr", "input-quest", 
            "pcvr-extracted", "quest-extracted", 
            "output-both", "texture_cache"
        ]
        
        for folder in folders:
            path = os.path.join(settings_dir, folder)
            if not os.path.exists(path):
                try:
                    os.makedirs(path)
                except: pass

    def check_external_tools(self):
        """Check if external tools are runnable and warn about missing DLLs"""
        tools = [
            ("texconv.exe", "Texture Converter"),
            ("evrtools.exe", "EVR Tools")
        ]
        
        for tool_name, desc in tools:
            path = get_tool_path(tool_name)
            if os.path.exists(path):
                try:
                    # Run with no args. texconv exits 1 normally.
                    # If DLLs are missing, Windows returns 0xC0000135 (-1073741515)
                    cmd = [path]
                    if sys.platform == 'win32':
                        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, 
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                        
                        # Check for STATUS_DLL_NOT_FOUND
                        if result.returncode == 3221225781 or result.returncode == -1073741515:
                            self.log_info(f"❌ {desc} ({tool_name}) is missing DLLs!")
                            self.log_info(f"   Please copy libsquish-0.dll, libstdc++-6.dll,")
                            self.log_info(f"   and libgcc_s_seh-1.dll to the same folder as {tool_name}")
                except Exception:
                    pass
    
    def auto_detect_folders(self):
        base_dir = get_base_dir()
        settings_dir = os.path.join(base_dir, SETTINGS_DIR_NAME)
        
        pcvr_folder = os.path.join(settings_dir, "input-pcvr")
        if os.path.exists(pcvr_folder):
            self.pcvr_input_folder = pcvr_folder
            self.log_info(f"Auto-detected PCVR input folder: {pcvr_folder}")
            
        quest_folder = os.path.join(settings_dir, "input-quest")
        if os.path.exists(quest_folder):
            self.quest_input_folder = quest_folder
            self.log_info(f"Auto-detected Quest input folder: {quest_folder}")
        
        output_both = os.path.join(settings_dir, "output-both")
        if os.path.exists(output_both):
            self.repacked_folder = output_both
            self.log_info(f"Auto-detected output-both folder: {output_both}")
    
    def setup_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        main_frame = tk.Frame(self.root, bg=self.colors['bg_dark'])
        main_frame.grid(row=0, column=0, sticky='nsew', padx=10, pady=10)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        header_frame = tk.Frame(main_frame, bg=self.colors['bg_dark'])
        header_frame.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        self.tutorial_btn = tk.Button(header_frame, text="📚 Tutorial", command=lambda: TutorialPopup.show(self.root, self), bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=8)
        self.tutorial_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.check_updates_btn = tk.Button(header_frame, text="🔄 Check Updates", command=self.check_app_updates, bg=self.colors['accent_blue'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=12, pady=8)
        self.check_updates_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        title_label = tk.Label(header_frame, text="ECHO VR TEXTURE EDITOR", font=("Arial", 16, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_dark'])
        title_label.pack(side=tk.LEFT, expand=True)

        self.update_echo_btn = tk.Button(header_frame, text="⚠ Update EchoVR", command=lambda: UpdateEchoPopup(self.root, self, self.config), bg=self.colors['accent_red'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=8)
        self.update_echo_btn.pack(side=tk.RIGHT, padx=(10, 0))

        self.share_mods_btn = tk.Button(header_frame, text="📤 Share Mods", command=self.share_modifications, bg='#4cd964', fg='#000000', font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=8)
        self.share_mods_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
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
        
        tk.Label(evr_frame, text="Extracted Folder:", font=("Arial", 9), fg=self.colors['text_light'], bg=self.colors['bg_dark']).grid(row=1, column=0, sticky='w', padx=10, pady=5)
        
        self.extracted_folder_label = tk.Label(evr_frame, text="Not selected", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.extracted_folder_label.grid(row=1, column=1, sticky='w', padx=5, pady=5)
        
        self.extracted_folder_btn = tk.Button(evr_frame, text="Select", command=self.select_extracted_folder, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 9), relief=tk.RAISED, bd=1, padx=10, pady=3)
        self.extracted_folder_btn.grid(row=1, column=2, padx=10, pady=5)
        
        button_frame = tk.Frame(evr_frame, bg=self.colors['bg_dark'])
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)
        
        self.extract_btn = tk.Button(button_frame, text="Extract Package", command=self.extract_package, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=20, pady=8, state=tk.DISABLED)
        self.extract_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.extract_btn, "Extract game assets from the selected package so they can be viewed and edited.")
        
        self.repack_btn = tk.Button(button_frame, text="Repack Modified", command=self.repack_package, bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED, bd=2, padx=20, pady=8, state=tk.DISABLED)
        self.repack_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.repack_btn, "Build a new package containing your modified textures.")

        self.evr_status_label = tk.Label(evr_frame, text="Ready", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        self.evr_status_label.grid(row=3, column=0, columnspan=3, pady=(0, 10))
        
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
        self.file_list.bind('<MouseWheel>', self._on_listbox_scroll)
        self.file_list.bind('<Button-4>', self._on_listbox_scroll)  # Linux scroll up
        self.file_list.bind('<Button-5>', self._on_listbox_scroll)  # Linux scroll down
        
        # Track listbox scroll state for lazy loading
        self.listbox_visible_end = 500  # Initial visible items
        
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
        
        self.view_mods_btn = tk.Button(action_frame, text="View existing modifications", command=self.view_modifications, bg=self.colors['accent_blue'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5)
        self.view_mods_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.view_mods_btn, "View and manage all files currently staged as modifications.")
        
        self.replace_btn = tk.Button(action_frame, text="Replace Texture", command=self.replace_texture, bg=self.colors['accent_green'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5, state=tk.DISABLED)
        self.replace_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.replace_btn, "Apply the replacement image to the selected texture.")
        
        self.download_btn = tk.Button(action_frame, text="Download All Textures", command=self.download_textures, bg=self.colors['accent_blue'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.download_btn, "Download a pre-generated cache of all textures (approx 400MB). Recommended for first time users.")
        
        self.load_all_btn = tk.Button(action_frame, text="Load/Cache All", command=self.load_all_textures, bg=self.colors['accent_blue'], fg=self.colors['text_light'], font=("Arial", 9, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=5)
        self.load_all_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.load_all_btn, "Process all textures in the current folder to generate thumbnails. May take a while.")
        
        self.resolution_status = tk.Label(button_panel, text="", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_dark'])
        
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
    
    def _on_listbox_scroll(self, event):
        """Load more items as user scrolls near the bottom"""
        try:
            # Get the current visible range
            visible_items = self.file_list.yview()
            if visible_items[1] > 0.9:  # Bottom 10% of the scrollbar
                # Load more items if available
                current_count = self.file_list.size()
                total_available = len(self.filtered_textures)
                if current_count < total_available:
                    # Load next chunk
                    chunk_size = 500
                    next_items = min(current_count + chunk_size, total_available)
                    # Remove the "load more" indicator
                    if current_count > 0:
                        last_item = self.file_list.get(current_count - 1)
                        if "Scroll down to load" in last_item or "more items" in last_item:
                            self.file_list.delete(current_count - 1)
                    # Add more items
                    for i in range(current_count - 1, next_items):
                        if i >= 0:
                            self.file_list.insert(tk.END, self.filtered_textures[i])
                            display_name = self.name_manager.get_name(self.filtered_textures[i])
                            self.file_list.insert(tk.END, display_name)
                    # Add indicator if more remain
                    if next_items < total_available:
                        remaining = total_available - next_items
                        self.file_list.insert(tk.END, f"[Loading {remaining} more items...]")
        except:
            pass
        pass
    
    
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
            self._set_package_from_manifests(manifests_path)
            self.log_info(f"✓ Data folder set: {path}")
        else:
            self.log_info("✗ Could not find manifests and packages folders")
        
        ConfigManager.save_config(data_folder=self.data_folder)
        self.config['data_folder'] = self.data_folder
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
        self.config['extracted_folder'] = self.extracted_folder
        self.log_info(f"✓ Extracted folder set: {path}")
    
    PACKAGE_TEXTURES = "48037dc70b0ecab2"

    def _set_package_from_manifests(self, manifests_path):
        try:
            packages = []
            packages_dir = os.path.join(os.path.dirname(manifests_path), "packages")
            with os.scandir(manifests_path) as it:
                for e in it:
                    if not e.is_file():
                        continue
                    file_name = e.name
                    package_file = os.path.join(packages_dir, file_name)
                    package_file_0 = os.path.join(packages_dir, f"{file_name}_0")
                    if os.path.exists(package_file) or os.path.exists(package_file_0):
                        packages.append(file_name)
            if self.PACKAGE_TEXTURES in packages:
                self.package_name = self.PACKAGE_TEXTURES
            elif packages:
                self.package_name = packages[0]
            else:
                self.package_name = None
            self.update_evr_buttons_state()
            if packages:
                self.log_info(f"Using package: {self.package_name}")
            else:
                self.log_info("No valid packages found")
        except Exception as e:
            self.log_info(f"Error reading manifests: {e}")
            self.package_name = None
    
    def update_evr_buttons_state(self):
        if self.data_folder and self.package_name and self.extracted_folder:
            self.extract_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
            if os.path.exists(self.extracted_folder) and _dir_nonempty(self.extracted_folder):
                self.repack_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
            else:
                self.repack_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
        else:
            self.extract_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            self.repack_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])

    def view_modifications(self):
        """Open the modifications viewer popup."""
        ModificationsViewerPopup(self.root, self)
    
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
        tk.Label(popup, text="Textures Only is faster and is recommended.", font=("Arial", 9), fg=self.colors['text_muted'], bg=self.colors['bg_medium']).pack(pady=(0, 5))

        btn_frame = tk.Frame(popup, bg=self.colors['bg_medium'])
        btn_frame.pack(fill=tk.X, padx=20)

        def do_extract(textures_only):
            popup.destroy()
            self._run_extraction(textures_only)

        tk.Button(btn_frame, text="Extract Textures Only (Recommended)", command=lambda: do_extract(True), bg=self.colors['accent_green'], fg=self.colors['text_light'], font=("Arial", 10, "bold"), relief=tk.RAISED).pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="Extract Full Package", command=lambda: do_extract(False), bg=self.colors['bg_light'], fg=self.colors['text_light'], font=("Arial", 10), relief=tk.RAISED).pack(fill=tk.X, pady=5)

    def _run_extraction(self, textures_only):
        os.makedirs(self.extracted_folder, exist_ok=True)
        mode_text = "Textures Only" if textures_only else "Full Package"
        
        # Show progress dialog
        progress = ProgressDialog(self.root, "Extracting Package", f"Extracting {mode_text}...\n\nThis may take a few minutes...", show_bar=False)
        
        self.evr_status_label.config(text=f"Extracting package ({mode_text})...", fg=self.colors['accent_green'])
        self.root.update_idletasks()
        
        def extraction_thread():
            export_type = "textures" if textures_only else ""
            success, message = self.evr_tools.extract_package(self.data_folder, self.package_name, self.extracted_folder, export_type=export_type)
            self.root.after(0, lambda: self.on_extraction_complete(success, message, progress))
        
        threading.Thread(target=extraction_thread, daemon=True).start()

    def on_extraction_complete(self, success, message, progress=None):
        if progress:
            progress.close()
        
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
        target_names = {PCVR_TEXTURE_ID, QUEST_TEXTURE_ID}
        for root, dirs, _ in os.walk(base_dir):
            for d in dirs:
                if d in target_names:
                    return root
        return None
    
    def repack_package(self):
        if not all([self.data_folder, self.package_name, self.extracted_folder]):
            messagebox.showerror("Error", "Please select data folder, package, and extraction folder first.")
            return

        input_folder = self.extracted_folder
        if not input_folder or not os.path.exists(input_folder):
            messagebox.showerror("Error", "Extracted folder not set or found. Please perform a full extraction first.")
        if self.is_quest_textures and self.quest_input_folder:
            input_folder = self.quest_input_folder
            self.log_info("🎯 Using Quest input folder for repacking")
        elif self.is_pcvr_textures and self.pcvr_input_folder:
            input_folder = self.pcvr_input_folder
            self.log_info("🎮 Using PCVR input folder for repacking")
        else:
            messagebox.showerror("Error", "Input folder not found. Please check input-pcvr/input-quest folders.")
            return
        
        self.log_info(f"📦 Using '{os.path.basename(input_folder)}' as input for repacking.")
        
        # Popup for Repack Mode
        popup = tk.Toplevel(self.root)
        popup.title("Select Repack Mode")
        popup.geometry("500x330")
        popup.configure(bg=self.colors['bg_medium'])
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()
        
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 330) // 2
            popup.geometry(f"+{x}+{y}")
        except: pass

        tk.Label(popup, text="Choose Repack Method", font=("Arial", 12, "bold"), fg=self.colors['text_light'], bg=self.colors['bg_medium']).pack(pady=(20, 10))
        
        btn_frame = tk.Frame(popup, bg=self.colors['bg_medium'])
        btn_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        def do_repack(quick):
            popup.destroy()
            self._run_repack(input_folder, quick)

        def do_revert():
            popup.destroy()
            try:
                manifest_dir = os.path.join(self.data_folder, "manifests")
                packages_dir = os.path.join(self.data_folder, "packages")
                
                target_manifest = os.path.join(manifest_dir, "48037dc70b0ecab2")
                backup_manifest = os.path.join(manifest_dir, "48037dc70b0ecab2.bak")
                target_package = os.path.join(packages_dir, "48037dc70b0ecab2_3")
                
                if os.path.exists(target_manifest):
                    os.remove(target_manifest)
                
                if os.path.exists(backup_manifest):
                    os.rename(backup_manifest, target_manifest)
                
                if os.path.exists(target_package):
                    os.remove(target_package)
                    
                messagebox.showinfo("Revert Complete", "Successfully reverted to backup!")
            except Exception as e:
                messagebox.showerror("Revert Error", f"Failed to revert backup:\n{str(e)}")

        # Full Repack Button
        full_btn = tk.Button(btn_frame, text="Full Repack (Standard)\nCreates new files in 'output-both' folder.\nSafe, leaves original files untouched.", 
                            command=lambda: do_repack(False), bg=self.colors['bg_light'], fg=self.colors['text_light'], 
                            font=("Arial", 10), relief=tk.RAISED, justify=tk.LEFT, padx=10, pady=5)
        full_btn.pack(fill=tk.X, pady=5)
        
        # Quick Repack Button
        quick_btn = tk.Button(btn_frame, text="Quick Repack (Experimental)\nDirectly modifies game files in-place.\nFastest, but requires a backup!", 
                             command=lambda: do_repack(True), bg=self.colors['accent_orange'], fg=self.colors['text_light'], 
                             font=("Arial", 10, "bold"), relief=tk.RAISED, justify=tk.LEFT, padx=10, pady=5)
        quick_btn.pack(fill=tk.X, pady=5)

        # Revert to backup Button (Conditional)
        backup_manifest_path = os.path.join(self.data_folder, "manifests", "48037dc70b0ecab2.bak")

        
        if os.path.exists(backup_manifest_path):
            revert_btn = tk.Button(btn_frame, text="Revert to Backup\nRestores the original files.\nDeletes your modifications.", 
                                 command=do_revert, bg=self.colors['accent_red'], fg=self.colors['text_light'], 
                                 font=("Arial", 10, "bold"), relief=tk.RAISED, justify=tk.LEFT, padx=10, pady=5)
            revert_btn.pack(fill=tk.X, pady=5)

    def _run_repack(self, input_folder, quick_mode):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = self.repacked_folder
        
        if quick_mode:
            confirm = messagebox.askyesno("Confirm Quick Repack", "⚠ WARNING: Quick Repack modifies your game files directly.\n\nEnsure you have a backup before proceeding.\n\nContinue?")
            if not confirm: return
        else:
            confirm = messagebox.askyesno("Confirm Repack", f"Repack modified files to:\n{output_dir}\n\nContinue?")
            if not confirm: return
        
        # Show progress dialog
        mode_str = "Quick Repack" if quick_mode else "Full Repack"
        progress = ProgressDialog(self.root, "Repacking Package", f"{mode_str} in progress...\n\nThis may take a few minutes...", show_bar=False)
        
        self.evr_status_label.config(text=f"{mode_str}...", fg=self.colors['accent_green'])
        self.root.update_idletasks()
        
        def repacking_thread():
            success, message = self.evr_tools.repack_package(output_dir, self.package_name, self.data_folder, input_folder, quick_mode=quick_mode)
            self.root.after(0, lambda: self.on_repacking_complete(success, message, output_dir, progress, quick_mode))
        
        threading.Thread(target=repacking_thread, daemon=True).start()
    
    def on_repacking_complete(self, success, message, output_dir, progress=None, quick_mode=False):
        if progress:
            progress.close()
        
        if success:
            self.evr_status_label.config(text="Repacking successful!", fg=self.colors['success'])
            self.log_info(f"✓ REPACKING: {message}")
            
            if quick_mode:
                self.log_info("✓ Game files updated directly.")
                messagebox.showinfo("Repacking Result", "Quick Repack Complete!\nGame files have been updated.")
            else:
                packages_path = os.path.join(output_dir, "packages")
                manifests_path = os.path.join(output_dir, "manifests")
                if os.path.exists(packages_path) and os.path.exists(manifests_path):
                    self.log_info(f"✓ Packages and manifests created in: {output_dir}")
                    self.update_quest_push_button()
                else:
                    self.log_info("⚠ Packages or manifests folders not found in output directory")
                messagebox.showinfo("Repacking Result", message)
        else:
            self.evr_status_label.config(text="Repacking failed", fg=self.colors['error'])
            self.log_info(f"✗ REPACKING FAILED: {message}")
            messagebox.showinfo("Repacking Result", message)
    
    def check_app_updates(self):
        """Check for app updates on GitHub"""
        self.log_info("🔄 Checking for updates...")
        self.check_updates_btn.config(state=tk.DISABLED, text="Checking...")
        self.root.update_idletasks()
        
        def check_thread():
            has_update, latest_version, download_url = check_for_updates()
            self.root.after(0, lambda: self.on_update_check_complete(has_update, latest_version, download_url))
        
        threading.Thread(target=check_thread, daemon=True).start()
    
    def on_update_check_complete(self, has_update, latest_version, download_url):
        self.check_updates_btn.config(state=tk.NORMAL, text="🔄 Check Updates")
        
        if has_update:
            self.log_info(f"✅ Update available: v{latest_version}")
            UpdateNotificationDialog(self.root, latest_version, download_url)
        else:
            self.log_info(f"✅ You are running the latest version (v{APP_VERSION})")
            messagebox.showinfo("Updates", f"You are running the latest version!\n\nCurrent: v{APP_VERSION}")
    
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

    def share_modifications(self):
        data_folder = self.config.get('data_folder')
        if not data_folder or not os.path.exists(data_folder):
            messagebox.showerror("Error", "Game data folder not found.\nPlease select your EchoVR data folder first.")
            return
        
        manifest_src = os.path.join(data_folder, "manifests", "48037dc70b0ecab2")
        package_src = os.path.join(data_folder, "packages", "48037dc70b0ecab2_3")
        
        missing = []
        if not os.path.exists(manifest_src):
            missing.append("manifests/48037dc70b0ecab2")
        if not os.path.exists(package_src):
            missing.append("packages/48037dc70b0ecab2_3")
        
        if missing:
            messagebox.showerror("Share Error", f"Could not find the following required files:\n" + "\n".join(missing) + "\n\nPlease run Quick Repack first.")
            return
        
        shared_mods_dir = get_settings_path("SharedMods")
        try:
            # Clear and recreate the SharedMods folder
            if os.path.exists(shared_mods_dir):
                shutil.rmtree(shared_mods_dir)
            os.makedirs(shared_mods_dir, exist_ok=True)
            
            # Copy each file flat into SharedMods
            shutil.copy2(manifest_src, os.path.join(shared_mods_dir, "48037dc70b0ecab2"))
            shutil.copy2(package_src, os.path.join(shared_mods_dir, "48037dc70b0ecab2_3"))
            
            self.log_info(f"✓ Modifications shared to: {shared_mods_dir}")
            messagebox.showinfo("Share Complete", f"Modification files copied to:\n{shared_mods_dir}\n\nSend the contents of this folder to others and ensure files are in correct place!")
            
            # Open folder in Explorer
            os.startfile(shared_mods_dir)
        except Exception as e:
            messagebox.showerror("Share Error", f"Failed to share modifications:\n{str(e)}")
    
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
            self.textures_folder = os.path.join(path, QUEST_TEXTURE_ID)
            self.corresponding_folder = os.path.join(path, QUEST_METADATA_ID)
            self.platform_label.config(text="Platform: Quest (ASTC)", fg=self.colors['success'])
            self.log_info("🎯 Switched to Quest mode")
        elif "pcvr" in folder_name:
            self.is_quest_textures = False
            self.is_pcvr_textures = True
            self.textures_folder = os.path.join(path, PCVR_TEXTURE_ID)
            self.corresponding_folder = os.path.join(path, PCVR_METADATA_ID)
            self.platform_label.config(text="Platform: PCVR (DDS)", fg=self.colors['accent_blue'])
            self.push_quest_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            self.log_info("🎮 Switched to PCVR mode")
        else:
            quest_textures_folder = os.path.join(path, QUEST_TEXTURE_ID)
            pcvr_textures_folder = os.path.join(path, PCVR_TEXTURE_ID)
            
            if getattr(sys, 'frozen', False):
                parent_dir = os.path.dirname(os.path.dirname(path))
                if not os.path.exists(quest_textures_folder):
                    quest_textures_folder = os.path.join(parent_dir, os.path.basename(path), QUEST_TEXTURE_ID)
                if not os.path.exists(pcvr_textures_folder):
                    pcvr_textures_folder = os.path.join(parent_dir, os.path.basename(path), PCVR_TEXTURE_ID)
            
            if os.path.exists(quest_textures_folder):
                self.textures_folder = quest_textures_folder
                self.corresponding_folder = os.path.join(path, QUEST_METADATA_ID)
                self.is_quest_textures = True
                self.is_pcvr_textures = False
                self.platform_label.config(text="Platform: Quest (ASTC)", fg=self.colors['success'])
                self.log_info("🎯 Auto-detected Quest textures")
            elif os.path.exists(pcvr_textures_folder):
                self.textures_folder = pcvr_textures_folder
                self.corresponding_folder = os.path.join(path, PCVR_METADATA_ID)
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
            self.config['output_folder'] = self.output_folder
            self.update_quest_push_button()
    
    def filter_textures(self, event=None):
        search_text = self.search_var.get().lower()
        self.file_list.delete(0, tk.END)
        self.filtered_textures = []
        
        if not search_text:
            self.filtered_textures = self.all_textures.copy()
        else:
            for texture in self.all_textures:
                display_name = self.name_manager.get_name(texture)
                if search_text in texture.lower() or search_text in display_name.lower():
                    self.filtered_textures.append(texture)
        
        for texture in self.filtered_textures:
            display_name = self.name_manager.get_name(texture)
            self.file_list.insert(tk.END, display_name)
    
    def clear_search(self):
        self.search_var.set("")
        self.filter_textures()
    
    def load_textures(self):
        self.file_list.delete(0, tk.END)
        self.file_list.insert(tk.END, "Loading textures...")
        self.update_canvas_placeholder(self.original_canvas, "Loading textures...")
        self.root.update_idletasks()
        threading.Thread(target=self._load_textures_worker, daemon=True).start()

    def _is_valid_texture_file(self, file_path):
        try:
            if not os.path.isfile(file_path): return False
            size = os.path.getsize(file_path)
            if size == 0: return False

            if not self.is_pcvr_textures and not self.is_quest_textures:
                return True

            with open(file_path, 'rb') as f:
                header = f.read(16)

            if self.is_pcvr_textures:
                return header.startswith(b'DDS ')
            
            if self.is_quest_textures:
                if header.startswith(b'\x13\xAB\xA1\x5C'): return True
                if header.startswith(b'\xABKTX 11') or header.startswith(b'\xABKTX 20'): return True
                if b'BcBP' in header: return True
                if header.startswith(b'PVR'): return True
                
                if size % 16 == 0:
                    if header.strip().startswith(b'{') or header.strip().startswith(b'<'):
                        return False
                    return True
                return False
                
            return True
        except:
            return False

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
            with os.scandir(self.textures_folder) as it:
                for e in it:
                    if e.is_file() and self._is_valid_texture_file(e.path):
                        valid_files.append(e.name)
            
            TextureCacheManager.update_cache(self.textures_folder, valid_files)
            self.root.after(0, lambda: self._on_textures_loaded(valid_files, len(valid_files)))
        except Exception as e:
            print(f"Scan Error: {e}")
            self.root.after(0, lambda: self._on_textures_loaded([], 0))

    def update_action_buttons(self):
        selection = self.file_list.curselection()
        if not selection:
            self.replace_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'], text="Replace Texture")
            self.edit_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            return

        # Enable replace button if anything is selected
        self.replace_btn.config(state=tk.NORMAL, bg=self.colors['accent_green'])
        
        if len(selection) > 1:
            self.replace_btn.config(text=f"Replace {len(selection)} Files")
            self.edit_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
        else:
            self.replace_btn.config(text="Replace Texture")
            # Edit button is handled by display_texture_result to ensure it's loaded

    def _on_textures_loaded(self, files, count):
        self.all_textures = sorted(files)
        self.filtered_textures = self.all_textures.copy()
        self.file_list.delete(0, tk.END)
        
        for texture in self.filtered_textures:
            display_name = self.name_manager.get_name(texture)
            self.file_list.insert(tk.END, display_name)
        
        # Cleanup cache to prevent disk bloat
        TextureLoader.cleanup_cache()
        
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
        self.update_action_buttons()
        
        if len(selection) > 1:
            self.update_canvas_placeholder(self.original_canvas, f"{len(selection)} files selected")
            return

        index = selection[0]
        texture_name = self.filtered_textures[index]
        self.current_texture = os.path.join(self.textures_folder, texture_name)

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
                if self.original_info is None:
                    try:
                        size = os.path.getsize(self.current_texture)
                    except:
                        size = 0
                    self.original_info = {
                        'file_size': size,
                        'format': 'DDS/Raw',
                        'width': image.width,
                        'height': image.height
                    }
            
            self.update_texture_info()
            self.edit_btn.config(state=tk.NORMAL, bg=self.colors['accent_blue'])
            self.update_action_buttons()
        else:
            self.update_canvas_placeholder(self.original_canvas, "Failed to load texture")
            self.edit_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
            self.update_action_buttons()
    
    def display_texture_error(self, error):
        self.log_info(f"Error loading texture: {error}")
        self.update_canvas_placeholder(self.original_canvas, "Error loading texture")
        self.edit_btn.config(state=tk.DISABLED, bg=self.colors['bg_light'])
        self.update_action_buttons()
    
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
                        elif file_path.lower().endswith(".png"):
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
                if self.replacement_info is None:
                    self.replacement_info = {
                        'format': 'PNG', 'width': image.width, 'height': image.height,
                        'file_size': os.path.getsize(file_path)
                    }
                    self.replacement_size = None
                else:
                    self.replacement_size = self.replacement_info.get('file_size')
            self.update_texture_info()
            self.check_resolution_match()
            self.update_action_buttons()
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
            
            mapped_name = self.name_manager.get_name(os.path.basename(self.current_texture))
            if mapped_name != os.path.basename(self.current_texture):
                info += f"Name: {mapped_name}\n\n"
        
        if self.replacement_info:
            info += "=== REPLACEMENT ===\n"
            info += f"File: {os.path.basename(self.replacement_texture)}\n"
            if 'width' in self.replacement_info:
                info += f"Dim: {self.replacement_info['width']} x {self.replacement_info['height']}\n"
            info += f"Format: {self.replacement_info['format']}\n"
        
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, info)
    
    def check_resolution_match(self):
        if self.original_info and self.replacement_info and 'width' in self.original_info and 'width' in self.replacement_info:
            ow, oh = self.original_info['width'], self.original_info['height']
            rw, rh = self.replacement_info['width'], self.replacement_info['height']
            if ow == rw and oh == rh:
                self.resolution_status.config(text="✓ Resolutions match", fg=self.colors['success'])
            else:
                self.resolution_status.config(
                    text=f"⚠ Resolution will be adjusted to {ow}×{oh} when replacing",
                    fg=self.colors['warning']
                )
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
        if not selection:
            return

        if len(selection) > 1:
            confirm = messagebox.askyesno("Multi-Replace", f"Are you sure you want to replace {len(selection)} textures with the selected image?")
            if not confirm:
                return

        replacement_size = None
        if not self.is_quest_textures and self.replacement_info and 'file_size' in self.replacement_info:
            replacement_size = self.replacement_info.get('file_size')

        def do_one(index):
            texture_name = self.filtered_textures[index]
            current_texture_path = os.path.join(self.textures_folder, texture_name)
            if self.is_quest_textures:
                return texture_name, TextureReplacer.replace_quest_texture(self.extracted_folder, self.quest_input_folder, current_texture_path, self.replacement_texture, self.texture_cache)
            return texture_name, TextureReplacer.replace_pcvr_texture(self.extracted_folder, self.pcvr_input_folder, current_texture_path, self.replacement_texture, replacement_size)

        results = []
        if len(selection) > 3:
            max_workers = min(4, len(selection), (os.cpu_count() or 2) + 1)
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(do_one, idx) for idx in selection]
                for f in as_completed(futures):
                    try:
                        results.append(f.result())
                    except Exception as e:
                        results.append((None, (False, str(e))))
        else:
            for index in selection:
                results.append(do_one(index))

        for texture_name, (success, message) in results:
            if texture_name is None:
                continue
            if success:
                self.log_info(f"✓ Replaced {texture_name}")
            else:
                self.log_info(f"✗ Failed {texture_name}: {message}")

        ok = sum(1 for _, (s, _) in results if s)
        fail = len(results) - ok
        msg = f"Replaced {ok} texture(s)." + (f" {fail} failed." if fail else "")
        messagebox.showinfo("Complete", msg)
        if len(selection) == 1:
            self.on_texture_selected(None)
    
    def download_textures(self):
        if self.is_downloading:
            self.log_info("Download already in progress...")
            return
        confirm = messagebox.askyesno("Download Textures", "Download texture cache archive (~400MB)?")
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
        # Extract into the persistent settings cache directory and protect existing files
        extract_to_path = CACHE_DIR
        temp_zip_path = os.path.join(tempfile.gettempdir(), "texture_cache.zip")
        try:
            self.root.after(0, lambda: self.log_info(f"Downloading from: {url}"))
            urllib.request.urlretrieve(url, temp_zip_path)
            self.root.after(0, lambda: self.log_info("✓ Download complete. Extracting..."))
            # Ensure cache dir exists
            os.makedirs(extract_to_path, exist_ok=True)

            # Safely extract zip entries one-by-one and do NOT overwrite existing files
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    # Skip directories
                    if member.is_dir():
                        continue

                    # Flatten any leading 'texture_cache/' from the zip entry path
                    member_path = member.filename
                    if member_path.startswith('texture_cache/'):
                        member_path = member_path[len('texture_cache/'):]
                    if member_path.startswith('/') or member_path.startswith('\\') or member_path == '':
                        continue

                    # Normalize the target path and avoid path traversal
                    target_path = os.path.normpath(os.path.join(extract_to_path, member_path))
                    if not target_path.startswith(os.path.normpath(extract_to_path) + os.sep) and os.path.normpath(extract_to_path) != os.path.normpath(target_path):
                        # Unsafe path - skip
                        continue

                    target_dir = os.path.dirname(target_path)
                    if not os.path.exists(target_dir):
                        try:
                            os.makedirs(target_dir, exist_ok=True)
                        except:
                            pass

                    # If file already exists, skip extracting to avoid overwrite
                    if os.path.exists(target_path):
                        continue

                    # Extract this single file
                    try:
                        with zip_ref.open(member, 'r') as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                    except Exception:
                        # If extraction of this member fails, skip it and continue
                        continue
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

    def load_all_textures(self):
        if not self.textures_folder or not self.all_textures:
            messagebox.showinfo("Info", "No textures found to load.")
            return
            
        confirm = messagebox.askyesno("Load All Textures", f"This will load and cache {len(self.all_textures)} textures.\nThis process converts textures to PNG for previewing.\nIt may take a while depending on the number of files.\n\nContinue?")
        if not confirm: return

        self.load_all_btn.config(state=tk.DISABLED)
        progress = ProgressDialog(self.root, "Caching Textures", "Generating texture cache...", show_bar=True)
        
        threading.Thread(target=self._load_all_worker, args=(progress,), daemon=True).start()

    def _load_all_worker(self, progress):
        total = len(self.all_textures)
        failed = []
        skipped = 0
        success = 0
        
        for i, texture_name in enumerate(self.all_textures):
            if progress.cancel_requested:
                break
            
            full_path = os.path.join(self.textures_folder, texture_name)
            try:
                # Check if already cached to avoid unnecessary loading/decoding
                cache_path = TextureLoader.get_cache_path(full_path)
                if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                    skipped += 1
                else:
                    img = TextureLoader.load_texture(full_path, self.is_quest_textures)
                    if img:
                        success += 1
                    else:
                        # Determine format for report
                        fmt = "ASTC" if self.is_quest_textures else "Unknown"
                        if not self.is_quest_textures:
                            info = DDSHandler.get_dds_info(full_path)
                            if info: fmt = info.get('format', 'Unknown')
                        failed.append(f"{texture_name} ({fmt})")
            except Exception as e:
                failed.append(f"{texture_name} (Error: {str(e)})")
            
            if not progress.update(i + 1, total):
                break
        
        self.root.after(0, lambda: self._on_load_all_complete(progress, success, skipped, failed))

    def _on_load_all_complete(self, progress, success, skipped, failed):
        progress.close()
        self.load_all_btn.config(state=tk.NORMAL)
        
        msg = f"Processing Complete.\n\nCached: {success}\nSkipped (Already Cached): {skipped}\nFailed: {len(failed)}"
        if failed:
            msg += "\n\nFailures (First 20):\n" + "\n".join(failed[:20])
            if len(failed) > 20: msg += f"\n...and {len(failed)-20} more."
            
            try:
                with open("texture_load_failures.txt", "w") as f:
                    f.write("Failed Textures:\n" + "\n".join(failed))
                msg += "\n\nFull list saved to texture_load_failures.txt"
            except: pass
            messagebox.showwarning("Load Results", msg)
        else:
            messagebox.showinfo("Load Results", msg)

def main():
    root = tk.Tk()

    # Set app icon
    icon_path = os.path.join(get_base_dir(), "icon.ico")
    
    # Check if running as PyInstaller bundle (onefile) where resources are in _MEIPASS
    if hasattr(sys, '_MEIPASS'):
        bundled_icon = os.path.join(sys._MEIPASS, "icon.ico")
        if os.path.exists(bundled_icon):
            icon_path = bundled_icon
            
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass

    app = EchoVRTextureViewer(root)
    root.mainloop()

if __name__ == '__main__':
    main()