import os
import sys
import subprocess
import glob
import difflib
import logging
import json
import platform
from typing import Dict, Tuple, Optional, Any

try:
    import src.logger as logger
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("AppLauncher")

class AppLauncher:
    """
    Cross-platform, scalable application launcher/closer.

    - Builds an index of installed applications (Windows, macOS, Linux).
    - Supports fuzzy matching for user-friendly names ("epic game store" -> "Epic Games Launcher").
    - Exposes:
        * refresh_index()        -> rebuild the index
        * find_and_launch(name)  -> open an app
        * find_and_close(name)   -> close an app (best-effort, using process name)
    """

    def __init__(self) -> None:
        self.os_type: str = platform.system()
        self.apps_cache: Dict[str, Dict[str, Any]] = {}
        self.refresh_index()

    def _normalize(self, name: str) -> str:
        """Removes spaces, casing, and common punctuation for better matching."""
        return (
            (name or "")
            .lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .strip()
        )

    def refresh_index(self) -> None:
        """Builds the index of installed apps based on OS."""
        logger.info(f"Indexing installed applications for {self.os_type}...")
        self.apps_cache = {}

        try:
            if self.os_type == "Windows":
                self._index_windows()
            elif self.os_type == "Darwin":
                self._index_macos()
            elif self.os_type == "Linux":
                self._index_linux()

            logger.info(f"Indexed {len(self.apps_cache)} applications.")
        except Exception as e:
            logger.error(f"Failed to index apps: {e}")

    def _index_windows(self) -> None:
        """
        Uses PowerShell to get Start Menu apps.
        Robustness fixes:
        - Uses errors='ignore' to handle non-UTF8 characters in app names.
        - Checks for NoneType on stdout.
        - Tries to infer a process_name for non-UWP .exe-based apps so we can close them.
        """
        ps_script = "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json"
        try:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", ps_script]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )

            if not result.stdout or not result.stdout.strip():
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    errors="ignore",
                )
                if not result.stdout or not result.stdout.strip():
                    return

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning("Could not parse PowerShell JSON output.")
                return

            if isinstance(data, dict):
                data = [data]

            for item in data:
                name = item.get("Name", "")
                app_id = item.get("AppID", "")
                if not name or not app_id:
                    continue

                clean = self._normalize(name)

                process_name: Optional[str] = None
                lower_id = str(app_id).lower()
                if lower_id.endswith(".exe"):
                    try:
                        process_name = os.path.basename(str(app_id))
                    except Exception:
                        process_name = None

                self.apps_cache[clean] = {
                    "real_name": name,
                    "launch_cmd": f"explorer.exe shell:AppsFolder\\{app_id}",
                    "type": "shell",
                    "process_name": process_name,
                }
        except Exception as e:
            logger.error(f"Windows indexing error: {e}")

    def _index_macos(self) -> None:
        """Scans standard Application folders."""
        app_dirs = [
            "/Applications",
            "/System/Applications",
            os.path.expanduser("~/Applications"),
        ]
        for d in app_dirs:
            if not os.path.exists(d):
                continue
            for app_path in glob.glob(os.path.join(d, "*.app")):
                filename = os.path.basename(app_path)
                name = filename.replace(".app", "")
                clean = self._normalize(name)

                self.apps_cache[clean] = {
                    "real_name": name,
                    "launch_cmd": ["open", app_path],
                    "type": "subprocess",
                    "process_name": name,
                }

    def _index_linux(self) -> None:
        """Parses .desktop files in standard locations."""
        desktop_dirs = [
            "/usr/share/applications",
            "/usr/local/share/applications",
            os.path.expanduser("~/.local/share/applications"),
        ]

        for d in desktop_dirs:
            for filepath in glob.glob(os.path.join(d, "*.desktop")):
                try:
                    name: Optional[str] = None
                    exec_cmd: Optional[str] = None
                    with open(filepath, "r", errors="ignore") as f:
                        for line in f:
                            if line.startswith("Name=") and not name:
                                name = line.strip().split("=", 1)[1]
                            if line.startswith("Exec=") and not exec_cmd:
                                exec_cmd = line.strip().split("=", 1)[1]
                                exec_cmd = exec_cmd.split("%")[0].strip()

                    if name and exec_cmd:
                        clean = self._normalize(name)
                        first_token = exec_cmd.split()[0]
                        process_name = os.path.basename(first_token)

                        self.apps_cache[clean] = {
                            "real_name": name,
                            "launch_cmd": exec_cmd.split(),
                            "type": "subprocess",
                            "process_name": process_name,
                        }
                except Exception:
                    continue

    def _resolve_app_info(self, user_query: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a user query into an app_info dict using:
        1) exact match
        2) substring match
        3) fuzzy match (with safe cutoff)
        Returns: app_info dict or None
        """
        query_norm = self._normalize(user_query)

        if query_norm in self.apps_cache:
            return self.apps_cache[query_norm]

        candidates = [
            (key, info)
            for key, info in self.apps_cache.items()
            if query_norm in key or key in query_norm
        ]
        if candidates:
            best_key, best_info = sorted(candidates, key=lambda x: len(x[0]))[0]
            return best_info

        keys = list(self.apps_cache.keys())
        matches = difflib.get_close_matches(query_norm, keys, n=1, cutoff=0.65)

        if matches:
            best_match_key = matches[0]
            app_info = self.apps_cache[best_match_key]
            logger.info(
                f"Fuzzy matched '{user_query}' ({query_norm}) -> "
                f"'{best_match_key}' ({app_info['real_name']})"
            )
            return app_info

        return None

    def find_and_launch(self, user_query: str) -> Tuple[bool, str]:
        """
        Resolve and launch an app by name.
        Returns: (success: bool, message: str)
        """
        app_info = self._resolve_app_info(user_query)
        if not app_info:
            return False, f"Could not find an app named '{user_query}'."
        return self._execute(app_info)

    def _execute(self, app_info: Dict[str, Any]) -> Tuple[bool, str]:
        """Safely executes the launch command."""
        real_name = app_info.get("real_name", "the app")
        cmd = app_info.get("launch_cmd")

        logger.info(f"Launching {real_name} via {cmd}")

        try:
            if app_info.get("type") == "shell":
                subprocess.Popen(cmd, shell=True)
            else:
                subprocess.Popen(cmd)
            return True, f"Opening {real_name}..."
        except Exception as e:
            logger.error(f"Launch failed for {real_name}: {e}")
            return False, f"Found {real_name}, but failed to launch it: {e}"

    def _close(
        self,
        app_info: Dict[str, Any],
        user_query: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Attempt to close an application using its process_name.
        Returns: (success: bool, message: str)
        """
        real_name = app_info.get("real_name", "the app")
        proc_name = app_info.get("process_name")
        label = user_query or real_name

        if not proc_name:
            msg = (
                f"I found {real_name}, but I don't know its process name "
                f"to close it safely."
            )
            logger.info(msg)
            return False, msg

        logger.info(f"Attempting to close {real_name} via process '{proc_name}'")

        try:
            if self.os_type == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", proc_name],
                    check=False,
                )
            else:
                subprocess.run(
                    ["pkill", "-f", proc_name],
                    check=False,
                )

            msg = f"Attempted to close {label}."
            logger.info(msg)
            return True, msg
        except Exception as e:
            logger.error(f"Failed to close {real_name} ({proc_name}): {e}")
            return False, f"Failed to close {label}: {e}"

    def find_and_close(self, user_query: str) -> Tuple[bool, str]:
        """
        Resolve and close an app by name using the dynamic index.
        Returns: (success: bool, message: str)
        """
        app_info = self._resolve_app_info(user_query)
        if not app_info:
            return False, f"Could not find an app named '{user_query}'."

        return self._close(app_info, user_query=user_query)

launcher = AppLauncher()
