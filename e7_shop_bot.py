"""
E7 Secret Shop Bot - reset automatique de la boutique secrète d'Epic Seven (client PC).

- Reconnaissance d'image (OpenCV) pour détecter les objets voulus.
- Lecture OCR (Tesseract) des cristaux / de l'or à droite de leur icône.
- Interface Tkinter (thème sombre) pour gérer positions, objets cibles, seuils et stats.

Raccourcis globaux : F9 = démarrer, F10 = arrêter.
Arrêt d'urgence : envoyer la souris dans le coin haut-gauche de l'écran.
"""

import ctypes
import ctypes.wintypes
import json
import os
import queue
import shutil
import sys
import threading
import time
import traceback
import winsound

# DPI awareness AVANT tkinter : sinon coordonnées écran / capture / clics décalés.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cv2
import mss
import numpy as np
import pyautogui
import pytesseract
from PIL import Image, ImageTk

try:
    from pynput import keyboard as pynput_keyboard
except Exception:  # pragma: no cover
    pynput_keyboard = None

# En .exe (PyInstaller) : réglages et captures à côté du .exe ; fichiers embarqués
# (Tesseract, icône) dans le dossier temporaire de décompression (_MEIPASS).
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
ICON_PATH = os.path.join(BUNDLE_DIR, "icone.ico")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.03

POINTS = [
    ("refresh", "Bouton « Actualiser »"),
    ("refresh_confirm", "Confirmer l'actualisation"),
    ("scroll_from", "Défilement : départ"),
    ("scroll_to", "Défilement : arrivée"),
    ("buy_confirm", "Confirmer l'achat (popup)"),
]

RESOURCES = [("skystone", "Cristaux"), ("gold", "Or")]

TESSERACT_CANDIDATES = [
    os.path.join(BUNDLE_DIR, "tesseract", "tesseract.exe"),  # Tesseract intégré au .exe
    os.path.join(BASE_DIR, "tesseract", "tesseract.exe"),    # ou posé à côté
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]

DEFAULT_CONFIG = {
    "points": {k: None for k, _ in POINTS},
    "targets": [],
    "resources": {
        "skystone": {"zone": None, "icon": None, "min": 0, "num_offset": 4, "num_width": 140, "enabled": True},
        "gold": {"zone": None, "icon": None, "min": 0, "num_offset": 4, "num_width": 200, "enabled": True},
    },
    "buy_offset": None,
    "autoclick": {"delay_ms": 100, "button": "left"},
    "settings": {
        "threshold": 0.85,
        "delay_click": 0.5,
        "delay_after_refresh": 1.2,
        "delay_after_scroll": 0.8,
        "delay_after_buy": 1.2,
        "max_refreshes": 0,
        "scan_attempts": 2,
        "scan_interval": 0.25,
        "scroll_up_first": False,
        "verify_name": True,
        "background": False,
        "window_title": "Epic Seven",
        "mode": "stop",
        "tesseract_path": "",
    },
}

# Palette du thème sombre
BG = "#111318"
SURF = "#1a1d24"
SURF2 = "#242833"
SURF3 = "#2e3341"
BORDER = "#2b303c"
TEXT = "#e7e9ee"
MUTED = "#8b92a5"
ACCENT = "#8b6cff"
ACCENT_H = "#9d83ff"
GOLD = "#f0c060"
GREEN = "#4cd28a"
RED = "#ff5f6d"
ORANGE = "#ffa84c"
FONT = "Segoe UI"
MONO = "Cascadia Mono"


# --------------------------------------------------------------------------- config

def _merge(default, loaded):
    if isinstance(default, dict) and isinstance(loaded, dict):
        out = dict(default)
        for k, v in loaded.items():
            out[k] = _merge(default.get(k), v) if k in default else v
        return out
    return loaded if loaded is not None else default


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return _merge(json.loads(json.dumps(DEFAULT_CONFIG)), json.load(f))
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def abs_path(rel):
    if not rel:
        return None
    return rel if os.path.isabs(rel) else os.path.join(BASE_DIR, rel)


def fmt_int(n):
    return f"{n:,}".replace(",", " ") if n is not None else "—"


# --------------------------------------------------------------------------- vision

# --------------------------------------------------------------------------- arrière-plan
# En mode arrière-plan, on capture directement la fenêtre du jeu (même recouverte) et on
# lui envoie des messages de clic : la vraie souris n'est jamais utilisée. Les coordonnées
# restent des coordonnées écran partout ailleurs : on convertit ici, au dernier moment.

BGMODE = {"on": False, "title": "Epic Seven"}

_u32 = ctypes.windll.user32
_gdi = ctypes.windll.gdi32


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", ctypes.wintypes.WORD), ("biBitCount", ctypes.wintypes.WORD),
                ("biCompression", ctypes.wintypes.DWORD), ("biSizeImage", ctypes.wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", ctypes.wintypes.DWORD), ("biClrImportant", ctypes.wintypes.DWORD)]


def game_window():
    hwnd = _u32.FindWindowW(None, BGMODE["title"])
    if not hwnd:
        raise RuntimeError(f"Fenêtre « {BG['title']} » introuvable : le jeu est-il ouvert ?")
    if _u32.IsIconic(hwnd):
        raise RuntimeError("La fenêtre du jeu est réduite : laisse-la ouverte (elle peut être derrière "
                           "d'autres fenêtres, mais pas dans la barre des tâches).")
    return hwnd


def client_origin(hwnd):
    p = ctypes.wintypes.POINT(0, 0)
    _u32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def capture_window(hwnd):
    """Capture la zone client de la fenêtre, même si elle est recouverte."""
    r = ctypes.wintypes.RECT()
    _u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    if w <= 0 or h <= 0:
        raise RuntimeError("Fenêtre du jeu de taille nulle.")
    hdc = _u32.GetDC(hwnd)
    mdc = _gdi.CreateCompatibleDC(hdc)
    bmp = _gdi.CreateCompatibleBitmap(hdc, w, h)
    old = _gdi.SelectObject(mdc, bmp)
    try:
        _u32.PrintWindow(hwnd, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
        bi = _BIH(biSize=ctypes.sizeof(_BIH), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        _gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    finally:
        _gdi.SelectObject(mdc, old)
        _gdi.DeleteObject(bmp)
        _gdi.DeleteDC(mdc)
        _u32.ReleaseDC(hwnd, hdc)
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()


def _lp(x, y):
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def post_click(x, y):
    """Clic en arrière-plan aux coordonnées ÉCRAN (x, y)."""
    hwnd = game_window()
    ox, oy = client_origin(hwnd)
    lp = _lp(x - ox, y - oy)
    _u32.PostMessageW(hwnd, 0x0200, 0, lp)        # WM_MOUSEMOVE
    time.sleep(0.03)
    _u32.PostMessageW(hwnd, 0x0201, 0x0001, lp)   # WM_LBUTTONDOWN
    time.sleep(0.06)
    _u32.PostMessageW(hwnd, 0x0202, 0, lp)        # WM_LBUTTONUP


def post_drag(a, b, duration=0.45, steps=18):
    hwnd = game_window()
    ox, oy = client_origin(hwnd)
    (x0, y0), (x1, y1) = (a[0] - ox, a[1] - oy), (b[0] - ox, b[1] - oy)
    _u32.PostMessageW(hwnd, 0x0200, 0, _lp(x0, y0))
    time.sleep(0.03)
    _u32.PostMessageW(hwnd, 0x0201, 0x0001, _lp(x0, y0))
    time.sleep(0.12)
    for i in range(1, steps + 1):
        t = i / steps
        _u32.PostMessageW(hwnd, 0x0200, 0x0001, _lp(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        time.sleep(duration / steps)
    time.sleep(0.2)
    _u32.PostMessageW(hwnd, 0x0202, 0, _lp(x1, y1))


def grab_screen():
    """Capture tout le bureau virtuel (tous les écrans). Renvoie (img BGR, offset_x, offset_y).
    En mode arrière-plan : capture de la fenêtre du jeu, l'offset étant sa position à l'écran."""
    if BGMODE["on"]:
        hwnd = game_window()
        ox, oy = client_origin(hwnd)
        return capture_window(hwnd), ox, oy
    with mss.mss() as sct:
        mon = sct.monitors[0]
        img = np.array(sct.grab(mon))[:, :, :3]
        return np.ascontiguousarray(img), mon["left"], mon["top"]


_tpl_cache = {}


def load_template(path):
    path = abs_path(path)
    if not path or not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    hit = _tpl_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    _tpl_cache[path] = (mtime, img)
    return img


def save_image(path, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(path)


_small_cache = {}


def small(img, key=None):
    """Version à 50 % (recherche 4× plus rapide). `key` = mise en cache (captures d'objets)."""
    if key is not None:
        hit = _small_cache.get(key)
        if hit is not None and hit[0] is img:
            return hit[1]
    out = cv2.resize(img, (max(1, img.shape[1] // 2), max(1, img.shape[0] // 2)), interpolation=cv2.INTER_AREA)
    if key is not None:
        _small_cache[key] = (img, out)
    return out


def crop_to_game(screen, ox, oy):
    """Limite la recherche à la fenêtre du jeu si on la trouve (bien plus rapide qu'en
    cherchant sur tous les écrans). Renvoie (image, ox, oy) recadrés."""
    try:
        hwnd = _u32.FindWindowW(None, BGMODE["title"])
        if not hwnd or _u32.IsIconic(hwnd):
            return screen, ox, oy
        r = ctypes.wintypes.RECT()
        _u32.GetClientRect(hwnd, ctypes.byref(r))
        gx, gy = client_origin(hwnd)
    except Exception:
        return screen, ox, oy
    x0, y0 = max(0, gx - ox), max(0, gy - oy)
    x1, y1 = min(screen.shape[1], gx - ox + r.right), min(screen.shape[0], gy - oy + r.bottom)
    if x1 - x0 < 100 or y1 - y0 < 100:
        return screen, ox, oy
    return screen[y0:y1, x0:x1], ox + x0, oy + y0


def find_all(screen, tpl, threshold, max_results=12, res=None):
    """Template matching avec suppression des doublons. Renvoie [(x, y, w, h, score)].
    `res` : résultat de cv2.matchTemplate déjà calculé (évite de le refaire)."""
    if tpl is None:
        return []
    h, w = tpl.shape[:2]
    if screen.shape[0] < h or screen.shape[1] < w:
        return []
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED) if res is None else res.copy()
    out = []
    while len(out) < max_results:
        _, maxv, _, (x, y) = cv2.minMaxLoc(res)
        if maxv < threshold:
            break
        out.append((x, y, w, h, float(maxv)))
        res[max(0, y - h // 2): y + h // 2 + 1, max(0, x - w // 2): x + w // 2 + 1] = -1
    return out


def find_tesseract(cfg_path):
    if cfg_path and os.path.exists(cfg_path):
        return cfg_path
    for c in TESSERACT_CANDIDATES:
        if os.path.exists(c):
            return c
    return shutil.which("tesseract")


def ocr_number(img_bgr, tesseract_path):
    """OCR d'un nombre (ex: '12,345,678'). Renvoie (valeur|None, image binarisée, texte brut)."""
    exe = find_tesseract(tesseract_path)
    if not exe:
        raise RuntimeError("Tesseract introuvable : installe-le ou indique son chemin dans Réglages.")
    pytesseract.pytesseract.tesseract_cmd = exe
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if np.mean(bw) < 127:  # texte clair sur fond sombre -> on inverse (texte noir sur blanc)
        bw = 255 - bw
    bw = cv2.copyMakeBorder(bw, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    txt = pytesseract.image_to_string(
        bw, config="--psm 7 -c tessedit_char_whitelist=0123456789,.")
    digits = "".join(c for c in txt if c.isdigit())
    return (int(digits) if digits else None), bw, txt.strip()


def _norm(s):
    """minuscules, sans accents, lettres et espaces seulement."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if c.isalpha() or c == " " or c == "\n")
    return " ".join(s.split())


def _bw_text(img_bgr, otsu=False):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if otsu:  # seuil adapté à la zone : le texte reste lisible même pâle (animation)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    else:
        _, bw = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)  # texte blanc -> noir sur blanc
    return bw


def _set_tess(tesseract_path):
    exe = find_tesseract(tesseract_path)
    if not exe:
        raise RuntimeError("Tesseract introuvable : installe-le ou indique son chemin dans Réglages.")
    pytesseract.pytesseract.tesseract_cmd = exe


def ocr_text(img_bgr, tesseract_path, psm=6, otsu=False):
    """OCR du texte clair (noms d'objets) d'une zone de l'écran."""
    _set_tess(tesseract_path)
    bw = cv2.copyMakeBorder(_bw_text(img_bgr, otsu), 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(bw, lang="eng", config=f"--psm {psm}")


def find_name_box(tpl, name, tesseract_path):
    """Repère où le nom de l'objet est écrit dans sa capture : [x, y, w, h] (coordonnées
    dans la capture), ou None. Permet ensuite de ne lire QUE le nom (pas le prix, etc.)."""
    from difflib import SequenceMatcher
    _set_tess(tesseract_path)
    d = pytesseract.image_to_data(_bw_text(tpl), lang="eng", config="--psm 11",
                                  output_type=pytesseract.Output.DICT)
    keys = [w for w in _norm(name).split() if len(w) >= 3] or _norm(name).split()
    boxes = []
    for i, word in enumerate(d["text"]):
        wn = _norm(word)
        if len(wn) >= 3 and max((SequenceMatcher(None, wn, k).ratio() for k in keys), default=0) >= 0.7:
            boxes.append((d["left"][i] // 2, d["top"][i] // 2,
                          (d["left"][i] + d["width"][i]) // 2, (d["top"][i] + d["height"][i]) // 2))
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    h, w = tpl.shape[:2]
    x0, y0 = max(0, x0 - 14), max(0, y0 - 8)          # marge : la position trouvée peut varier de 1-2 px
    x1, y1 = min(w, x1 + 14), min(h, y1 + 8)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def name_score(expected, ocr):
    """Ressemblance (0-1) entre le nom attendu et le meilleur passage du texte lu."""
    from difflib import SequenceMatcher
    exp, txt = _norm(expected), _norm(ocr).replace("\n", " ")
    if not exp or not txt:
        return 0.0
    n = len(exp)
    best = 0.0
    for i in range(0, max(1, len(txt) - n + 1)):
        for L in (n - 2, n, n + 2):
            seg = txt[i:i + max(1, L)]
            best = max(best, SequenceMatcher(None, exp, seg).ratio())
    return best


NAME_OK = 0.75  # ressemblance minimale du nom lu


def read_resource(screen, ox, oy, res_cfg, threshold, tesseract_path):
    """Lit le nombre d'une ressource.
    - Méthode principale : « zone » = rectangle tracé autour du nombre (coordonnées écran).
    - Ancienne méthode (si pas de zone) : icône trouvée à l'écran + lecture à sa droite."""
    zone = res_cfg.get("zone")
    if zone:
        x, y, w, h = zone
        x, y = x - ox, y - oy
        crop = screen[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            return None, {"error": "zone hors écran"}
        val, bw, txt = ocr_number(crop, tesseract_path)
        return val, {"crop": crop, "bw": bw, "txt": txt}
    tpl = load_template(res_cfg.get("icon"))
    if tpl is None:
        return None, None
    matches = find_all(screen, tpl, threshold)
    if not matches:
        return None, {"error": "icône non trouvée"}
    x, y, w, h, score = min(matches, key=lambda m: (m[1], m[0]))
    nx = x + w + int(res_cfg.get("num_offset", 4))
    y0, y1 = max(0, y - 2), min(screen.shape[0], y + h + 2)
    crop = screen[y0:y1, nx: nx + int(res_cfg.get("num_width", 150))]
    if crop.size == 0:
        return None, {"error": "zone chiffre hors écran"}
    val, bw, txt = ocr_number(crop, tesseract_path)
    return val, {"crop": crop, "bw": bw, "txt": txt, "icon": (x, y, w, h), "score": score}


# --------------------------------------------------------------------------- inputs

def click_at(x, y):
    if BGMODE["on"]:
        return post_click(x, y)
    pyautogui.moveTo(int(x), int(y), duration=0.08)
    pyautogui.mouseDown()
    time.sleep(0.06)
    pyautogui.mouseUp()


def drag(a, b):
    if BGMODE["on"]:
        return post_drag(a, b)
    pyautogui.moveTo(int(a[0]), int(a[1]), duration=0.08)
    pyautogui.mouseDown()
    time.sleep(0.12)
    pyautogui.moveTo(int(b[0]), int(b[1]), duration=0.45)
    time.sleep(0.2)
    pyautogui.mouseUp()


# --------------------------------------------------------------------------- auto click

class AutoClicker(threading.Thread):
    """Clique en boucle là où se trouve la souris. Arrêt : F8, ou souris en haut à gauche."""
    FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}

    def __init__(self, delay_ms, button="left"):
        super().__init__(daemon=True)
        self.delay = max(1, float(delay_ms)) / 1000.0
        self.down, self.up = self.FLAGS.get(button, self.FLAGS["left"])
        self.stop_event = threading.Event()
        self.count = 0
        self.started = time.time()
        self.reason = None

    def run(self):
        u32 = ctypes.windll.user32
        pt = ctypes.wintypes.POINT()
        ctypes.windll.winmm.timeBeginPeriod(1)  # timers précis à la milliseconde
        try:
            nxt = time.perf_counter()
            while not self.stop_event.is_set():
                if u32.GetCursorPos(ctypes.byref(pt)) and pt.x <= 1 and pt.y <= 1:
                    self.reason = "Arrêt d'urgence (souris dans le coin)."
                    break
                u32.mouse_event(self.down, 0, 0, 0, 0)
                u32.mouse_event(self.up, 0, 0, 0, 0)
                self.count += 1
                nxt += self.delay
                wait = nxt - time.perf_counter()
                if wait > 0:
                    self.stop_event.wait(wait)
                else:
                    nxt = time.perf_counter()  # on a pris du retard : on ne rattrape pas en rafale
        finally:
            ctypes.windll.winmm.timeEndPeriod(1)

    def stop(self):
        self.stop_event.set()


# --------------------------------------------------------------------------- bot

class Stopped(Exception):
    pass


class Bot(threading.Thread):
    def __init__(self, cfg, events, stop_event):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.ev = events
        self.stop_event = stop_event
        self.s = cfg["settings"]
        self.stats = {"refreshes": 0, "found": {}, "bought": {}, "skystone": None, "gold": None,
                      "skystone_start": None, "gold_start": None}
        self.read_failures = 0
        self._rejected = set()
        self._ocr_cache = {}  # noms déjà lus, par (vue, position)
        self._name_boxes = {}  # zone du nom dans chaque capture d'objet
        self._view = 0        # change à chaque défilement / actualisation
        self._bought_files = set()  # objets déjà achetés dans la boutique actuelle

    def shop_snapshot(self):
        """Petite image grise de la boutique, pour voir si l'actualisation a eu lieu."""
        screen, ox, oy = crop_to_game(*grab_screen())
        g = cv2.cvtColor(small(small(screen)), cv2.COLOR_BGR2GRAY)
        return g.astype(np.int16)

    def name_box(self, t, tpl):
        """Zone du nom dans la capture de l'objet (calculée une fois, puis gardée)."""
        if t["file"] not in self._name_boxes:
            try:
                nb = find_name_box(tpl, t["name"], self.s["tesseract_path"])
            except Exception:
                nb = None
            self._name_boxes[t["file"]] = nb
            if nb is None:
                self.log(f"⚠ Nom « {t['name']} » introuvable dans sa capture : lecture de toute la ligne. "
                         f"Renomme l'objet comme il est écrit en jeu.")
        return self._name_boxes[t["file"]]

    def new_view(self):
        self._view += 1
        if len(self._ocr_cache) > 200:
            self._ocr_cache.clear()

    # helpers
    def log(self, msg):
        self.ev.put(("log", msg))

    def push_stats(self):
        self.ev.put(("stats", json.loads(json.dumps(self.stats))))

    def wait(self, sec):
        if self.stop_event.wait(max(0.0, float(sec))):
            raise Stopped()

    def click_point(self, key, delay=None):
        pt = self.cfg["points"].get(key)
        if not pt:
            raise RuntimeError(f"Position « {key} » non définie.")
        if self.stop_event.is_set():
            raise Stopped()
        click_at(*pt)
        self.wait(self.s["delay_click"] if delay is None else delay)

    # étapes
    def check_resources(self):
        """Renvoie un message d'arrêt si une ressource passe sous son minimum, sinon None."""
        screen, ox, oy = grab_screen()
        for key, label in RESOURCES:
            r = self.cfg["resources"][key]
            if not r.get("enabled") or not (r.get("zone") or r.get("icon")):
                continue
            val, info = read_resource(screen, ox, oy, r, self.s["threshold"], self.s["tesseract_path"])
            if val is None:
                self.read_failures += 1
                why = (info or {}).get("error") or f"OCR illisible ('{(info or {}).get('txt', '')}')"
                self.log(f"⚠ Lecture {label} impossible : {why} ({self.read_failures}/3)")
                if self.read_failures >= 3:
                    return f"Impossible de lire {label} 3 fois de suite (sécurité)."
                continue
            self.read_failures = 0
            self.stats[key] = val
            if self.stats[key + "_start"] is None:
                self.stats[key + "_start"] = val
            if val < int(r.get("min", 0)):
                return f"{label} = {fmt_int(val)} < minimum {fmt_int(int(r['min']))}"
        self.push_stats()
        return None

    def scan(self, best=None, shot=None):
        """Renvoie les objets trouvés. Si `best` est un dict, il reçoit le meilleur score
        de chaque objet (même sous le seuil), pour signaler les « presque détectés ».

        Avec « Vérifier le nom » : l'image repère les candidats (seuil abaissé de 0.15), puis
        le nom écrit dans la zone est lu (OCR) et doit correspondre au nom de l'objet."""
        screen, ox, oy = shot or grab_screen()
        screen, ox, oy = crop_to_game(screen, ox, oy)  # on ne cherche que dans la fenêtre du jeu
        scr_s = small(screen)
        th = self.s["threshold"]
        verify = self.s.get("verify_name", True)
        img_th = max(0.6, th - 0.10) if verify else th
        found = []
        for t in self.cfg["targets"]:
            if not t.get("enabled", True):
                continue
            tpl = load_template(t["file"])
            if tpl is None or tpl.shape[0] > screen.shape[0] or tpl.shape[1] > screen.shape[1]:
                continue
            tpl_s = small(tpl, key=t["file"])
            res = cv2.matchTemplate(scr_s, tpl_s, cv2.TM_CCOEFF_NORMED)  # une seule fois, à 50 %
            sc = float(cv2.minMaxLoc(res)[1])
            if best is not None:
                best[t["name"]] = max(best.get(t["name"], -1.0), sc)
            if sc < img_th:
                continue  # rien d'assez ressemblant : inutile d'aller plus loin
            h, w = tpl.shape[:2]
            for (xs, ys, _, _, score) in find_all(scr_s, tpl_s, img_th, res=res):
                x, y = min(xs * 2, screen.shape[1] - w), min(ys * 2, screen.shape[0] - h)
                if verify:
                    # on ne lit que la zone du nom (repérée dans la capture), pas le prix ;
                    # et le nom d'une ligne ne change pas tant que la vue ne bouge pas : on le garde
                    nb = self.name_box(t, tpl)
                    if nb:
                        bx, by, bw_, bh = nb
                        crop = screen[y + by:y + by + bh, x + bx:x + bx + bw_]
                    else:
                        crop = screen[y:y + h, x:x + w]
                    # la luminosité fait partie de la clé : si la ligne est encore en train
                    # d'apparaître, la lecture suivante (image différente) n'est pas court-circuitée
                    key = (self._view, t["file"] if nb else "", (ox + x) // 30, (oy + y) // 30,
                           int(crop.mean()) // 6)
                    if key not in self._ocr_cache:
                        self._ocr_cache[key] = ocr_text(crop, self.s["tesseract_path"], psm=6, otsu=bool(nb))
                    ns = name_score(t["name"], self._ocr_cache[key])
                    # image quasi parfaite (≥ 0.95) : c'est l'objet même si le nom est mal lu
                    # (un autre objet ne dépasse pas ~0.8 dans les tests)
                    if ns < NAME_OK and score < 0.95:
                        lu = " ".join(self._ocr_cache[key].split())[:60]
                        note = (t["name"], _norm(lu)[:20])
                        if score >= th and note not in self._rejected:  # l'ancienne méthode l'aurait pris
                            self._rejected.add(note)
                            self.log(f"◎ Écarté : ressemble à {t['name']} (image {score:.2f}) "
                                     f"mais le nom lu est « {lu} »")
                        continue
                found.append({"name": t["name"], "file": t["file"], "buy_point": t.get("buy_point"),
                              "x": ox + x, "y": oy + y, "w": w, "h": h,
                              "cx": ox + x + w / 2, "cy": oy + y + h / 2, "score": score})
        found.sort(key=lambda f: f["cy"])
        return found

    def scan_retry(self, seen, best):
        """Scanne jusqu'à « Scans par page » fois (l'affichage peut être en retard sur
        l'animation) et s'arrête dès qu'un objet pas encore vu apparaît."""
        tries = max(1, int(self.s.get("scan_attempts", 2)))
        items = []
        for i in range(tries):
            items = [it for it in self.scan(best) if it["file"] not in seen]
            if items:
                if i:
                    self.log(f"◎ Objet vu au scan n°{i + 1}")
                break
            if i < tries - 1:
                self.wait(self.s.get("scan_interval", 0.25))
        return items

    def locate_stable(self, item):
        """Retrouve l'objet et attend que sa position ne bouge plus (la liste peut encore
        glisser après un défilement). Renvoie l'objet à sa position actuelle, ou None."""
        last = None
        for _ in range(8):
            same = [f for f in self.scan() if f["file"] == item["file"]]
            if not same:
                last = None
                self.wait(0.15)
                continue
            cur = min(same, key=lambda f: abs(f["cy"] - item["cy"]))
            if last and abs(cur["x"] - last["x"]) <= 3 and abs(cur["y"] - last["y"]) <= 3:
                return cur
            last = cur
            self.wait(0.15)
        return last

    def read_gold(self):
        r = self.cfg["resources"]["gold"]
        if not (r.get("zone") or r.get("icon")):
            return None
        try:
            screen, ox, oy = grab_screen()
            return read_resource(screen, ox, oy, r, self.s["threshold"], self.s["tesseract_path"])[0]
        except Exception:
            return None

    def buy_pos(self, item):
        """Position écran du bouton « Acheter » de l'objet."""
        bp = item.get("buy_point")
        off = self.cfg.get("buy_offset")
        if bp:  # point « Acheter » défini dans la capture de l'objet : suit la ligne de l'objet
            return item["x"] + bp[0], item["y"] + bp[1]
        if off:  # ancien mode : décalage global depuis le centre de l'objet
            return item["cx"] + off[0], item["cy"] + off[1]
        raise RuntimeError(f"Mode achat auto : définis le point « Acheter » de {item['name']}.")

    def click_buy(self, item):
        click_at(*self.buy_pos(item))

    def button_patch(self, pos):
        """Image du bouton « Acheter » (autour du point de clic), pour voir s'il change."""
        screen, ox, oy = grab_screen()
        x, y = int(pos[0] - ox), int(pos[1] - oy)
        return screen[max(0, y - 20):y + 20, max(0, x - 60):x + 60].astype(np.int16)

    def purchase_done(self, gold_before, pos, btn_before):
        """Attend (jusqu'à ~2.5 s) un signe que l'achat est passé :
        l'or a baissé, ou le bouton « Acheter » a changé d'aspect (objet vendu).
        Renvoie un texte décrivant la preuve, ou None si rien n'a bougé."""
        for _ in range(10):
            gold_after = self.read_gold()
            if gold_before is not None and gold_after is not None and gold_after < gold_before:
                return f"or {fmt_int(gold_before)} → {fmt_int(gold_after)}"
            btn = self.button_patch(pos)
            if btn.shape == btn_before.shape and btn.size and float(np.abs(btn - btn_before).mean()) > 15:
                return "bouton « Acheter » changé"
            self.wait(0.25)
        return None

    def buy(self, item):
        """Achète l'objet et VÉRIFIE l'achat (or dépensé, sinon objet plus reconnu car « 0/1 »).
        Jusqu'à 3 essais. Renvoie None si acheté, sinon un message d'arrêt : on n'actualise
        jamais la boutique avec un objet trouvé mais pas acheté."""
        name = item["name"]
        for attempt in range(1, 4):
            cur = self.locate_stable(item)
            if cur is None:
                if attempt == 1:
                    return f"{name} trouvé mais introuvable au moment d'acheter : bot arrêté, vérifie la boutique."
                break  # disparu après un essai précédent : l'achat est passé
            pos = self.buy_pos(cur)
            btn_before = self.button_patch(pos)
            gold_before = self.read_gold()
            self.click_buy(cur)
            self.wait(self.s["delay_click"])
            self.click_point("buy_confirm", self.s["delay_after_buy"])
            proof = self.purchase_done(gold_before, pos, btn_before)
            if proof:
                self.log(f"◎ Achat confirmé ({proof})")
                break
            # rien n'a bougé (ni l'or, ni le bouton) : le clic n'est pas passé, on recommence
            self.log(f"⚠ Achat de {name} non confirmé (essai {attempt}/3)"
                     + (", nouvel essai…" if attempt < 3 else "."))
        else:
            return f"Achat de {name} non confirmé après 3 essais : bot arrêté sans actualiser."
        self._bought_files.add(item["file"])
        self.stats["bought"][name] = self.stats["bought"].get(name, 0) + 1
        self.log(f"★ Acheté : {name}")
        self.push_stats()
        return None

    def handle_page(self, seen, best):
        """Chaque objet n'est compté (et acheté) qu'une fois par actualisation, même s'il
        reste visible après le défilement. Renvoie un message d'arrêt (mode stop) ou None."""
        for item in self.scan_retry(seen, best):
            if item["file"] in seen:
                continue
            seen.add(item["file"])
            self.stats["found"][item["name"]] = self.stats["found"].get(item["name"], 0) + 1
            self.ev.put(("found", item["file"]))
            self.log(f"✦ Trouvé : {item['name']} (score {item['score']:.2f}) après "
                     f"{self.stats['refreshes']} actualisation(s)")
            self.push_stats()
            if self.s["mode"] == "stop":
                return f"Objet trouvé : {item['name']}"
            stop = self.check_resources()
            if stop:
                return stop
            stop = self.buy(item)
            if stop:
                return stop
        return None

    def report_near_misses(self, best, seen):
        """Signale un objet non retenu mais dont le score était proche du seuil :
        c'est probablement lui, et le seuil est un peu trop strict."""
        # Les lignes de la boutique se ressemblent (cadre, pièce, bouton) : un autre objet
        # peut monter vers ~0.72. On ne signale donc que ce qui est vraiment proche du seuil,
        # et seulement quand rien n'a été trouvé (sinon c'est un sosie de l'objet trouvé).
        if seen:
            return
        th = self.s["threshold"]
        if self.s.get("verify_name", True):
            # le nom protège des confusions : on peut conseiller de baisser le seuil sans risque
            img_th = max(0.6, th - 0.15)
            for name, sc in best.items():
                if img_th - 0.06 <= sc < img_th:
                    self.log(f"⚠ Presque détecté : {name} (image {sc:.2f}). Si l'objet était bien là, "
                             f"baisse le seuil à {min(th, sc + 0.12):.2f}.")
            return
        for name, sc in best.items():
            if max(0.76, th - 0.10) <= sc < th:
                self.log(f"⚠ Presque détecté : {name} (score {sc:.2f}, seuil {th:.2f}). "
                         f"Si l'objet était bien là, baisse le seuil à {max(0.78, sc - 0.02):.2f} "
                         f"(pas en dessous de 0.78).")

    def loop(self):
        maxr = int(self.s.get("max_refreshes") or 0)
        has_scroll = self.cfg["points"].get("scroll_from") and self.cfg["points"].get("scroll_to")
        for key in ("refresh", "refresh_confirm"):
            if not self.cfg["points"].get(key):
                return f"Position « {dict(POINTS)[key]} » non définie."
        if not any(t.get("enabled", True) for t in self.cfg["targets"]):
            return "Aucun objet cible actif."
        if self.s["mode"] == "buy":
            missing = [t["name"] for t in self.cfg["targets"] if t.get("enabled", True)
                       and not t.get("buy_point") and not self.cfg.get("buy_offset")]
            if missing:
                return "Point « Acheter » non défini pour : " + ", ".join(missing)
            if not self.cfg["points"].get("buy_confirm"):
                return "Position « Confirmer l'achat » non définie."
        self.log("▶ Démarrage (F10 ou souris en haut à gauche pour arrêter)")
        self.wait(0.5)
        while True:
            stop = self.check_resources()
            if stop:
                return stop
            seen = set(self._bought_files)  # déjà acheté ici : ignoré jusqu'à la prochaine actualisation
            best = {}
            if has_scroll and self.s.get("scroll_up_first"):
                # Option : remonter la liste avant le premier scan (si elle ne revient pas seule en haut).
                drag(self.cfg["points"]["scroll_to"], self.cfg["points"]["scroll_from"])
                self.new_view()
                self.wait(self.s["delay_after_scroll"])
            stop = self.handle_page(seen, best)
            if stop:
                return stop
            if has_scroll:
                drag(self.cfg["points"]["scroll_from"], self.cfg["points"]["scroll_to"])
                self.new_view()
                self.wait(self.s["delay_after_scroll"])
                stop = self.handle_page(seen, best)
                if stop:
                    return stop
            self.report_near_misses(best, seen)
            if maxr and self.stats["refreshes"] >= maxr:
                return f"Nombre max d'actualisations atteint ({maxr})."
            before = self.shop_snapshot()
            self.click_point("refresh")
            self.click_point("refresh_confirm", self.s["delay_after_refresh"])
            self.new_view()
            after = self.shop_snapshot()
            if before.shape == after.shape and float(np.abs(after - before).mean()) < 4:
                # la boutique n'a pas changé : l'actualisation n'est pas passée (popup ?)
                # -> on garde en mémoire ce qui a été acheté pour ne pas le racheter
                self._refresh_fails = getattr(self, "_refresh_fails", 0) + 1
                if self._refresh_fails >= 3:
                    return "L'actualisation ne passe pas (3 fois de suite) : vérifie le jeu."
                self.log("⚠ L'actualisation ne semble pas être passée (boutique identique), nouvel essai.")
                continue
            self._refresh_fails = 0
            self._bought_files.clear()
            self.stats["refreshes"] += 1
            self.push_stats()

    def run(self):
        reason = "Arrêté."
        try:
            reason = self.loop() or reason
        except Stopped:
            reason = "Arrêté par l'utilisateur."
        except pyautogui.FailSafeException:
            reason = "Arrêt d'urgence (souris dans le coin)."
        except Exception as e:
            self.log("❌ " + traceback.format_exc())
            reason = f"Erreur : {e}"
        self.push_stats()
        self.ev.put(("done", reason))


# --------------------------------------------------------------------------- theme

def dark_titlebar(win):
    """Barre de titre Windows sombre (Windows 10 20H1+ / 11)."""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
    except Exception:
        pass


def apply_theme(root):
    root.configure(bg=BG)
    st = ttk.Style(root)
    st.theme_use("clam")
    f = (FONT, 10)
    st.configure(".", background=BG, foreground=TEXT, font=f, bordercolor=BORDER,
                 lightcolor=BORDER, darkcolor=BORDER, troughcolor=SURF, focuscolor=ACCENT,
                 selectbackground=ACCENT, selectforeground="white", insertcolor=TEXT)
    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=SURF)
    st.configure("Stat.TFrame", background=SURF)

    st.configure("TLabel", background=BG, foreground=TEXT)
    st.configure("Title.TLabel", font=(FONT, 17, "bold"))
    st.configure("Sub.TLabel", foreground=MUTED, font=(FONT, 9))
    st.configure("Card.TLabel", background=SURF)
    st.configure("CardMuted.TLabel", background=SURF, foreground=MUTED, font=(FONT, 9))
    st.configure("CardHead.TLabel", background=SURF, foreground=MUTED, font=(FONT, 9, "bold"))
    st.configure("CardTitle.TLabel", background=SURF, font=(FONT, 11, "bold"))
    st.configure("StatLabel.TLabel", background=SURF, foreground=MUTED, font=(FONT, 9))
    st.configure("StatValue.TLabel", background=SURF, foreground=TEXT, font=(FONT, 19, "bold"))
    st.configure("StatSub.TLabel", background=SURF, foreground=MUTED, font=(FONT, 8))
    st.configure("Value.TLabel", background=SURF, foreground=GREEN, font=(MONO, 10))
    st.configure("ValueOff.TLabel", background=SURF, foreground=MUTED, font=(MONO, 10))

    # Boutons
    for name, bg, hover, fg in (("TButton", SURF2, SURF3, TEXT),
                                ("Accent.TButton", ACCENT, ACCENT_H, "white"),
                                ("Danger.TButton", "#3a2028", "#552a35", RED),
                                ("Go.TButton", "#1f6f4a", "#25875a", "white"),
                                ("Stop.TButton", "#7a2631", "#952f3c", "white")):
        st.configure(name, background=bg, foreground=fg, borderwidth=0, focusthickness=0,
                     padding=(12, 6), relief="flat", lightcolor=bg, darkcolor=bg, bordercolor=bg)
        st.map(name,
               background=[("disabled", SURF), ("pressed", bg), ("active", hover)],
               foreground=[("disabled", "#555b6b")],
               lightcolor=[("active", hover)], darkcolor=[("active", hover)],
               bordercolor=[("active", hover)])
    st.configure("Go.TButton", font=(FONT, 11, "bold"), padding=(18, 9))
    st.configure("Stop.TButton", font=(FONT, 11, "bold"), padding=(18, 9))
    st.configure("Small.TButton", padding=(8, 3), font=(FONT, 9))

    # Champs
    st.configure("TEntry", fieldbackground=SURF2, foreground=TEXT, insertcolor=TEXT,
                 bordercolor=BORDER, lightcolor=SURF2, darkcolor=SURF2, padding=(6, 4))
    st.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    for cls in ("TCheckbutton", "TRadiobutton"):
        st.configure("Card." + cls, background=SURF, foreground=TEXT,
                     indicatorbackground=SURF2, indicatorforeground=ACCENT, indicatormargin=(0, 0, 6, 0))
        st.map("Card." + cls, background=[("active", SURF)],
               indicatorbackground=[("selected", SURF2), ("active", SURF3)])

    # Onglets
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0),
                 bordercolor=SURF, lightcolor=SURF, darkcolor=SURF)
    st.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 8),
                 borderwidth=0, font=(FONT, 10, "bold"), lightcolor=BG, bordercolor=BG, darkcolor=BG)
    st.map("TNotebook.Tab", background=[("selected", SURF), ("active", SURF2)],
           foreground=[("selected", TEXT), ("active", TEXT)],
           lightcolor=[("selected", SURF), ("active", SURF2)],
           bordercolor=[("selected", SURF), ("active", SURF2)],
           darkcolor=[("selected", SURF), ("active", SURF2)])

    # Tableau
    st.configure("Treeview", background=SURF, fieldbackground=SURF, foreground=TEXT,
                 rowheight=30, borderwidth=0, font=(FONT, 10))
    st.map("Treeview", background=[("selected", "#3b3270")], foreground=[("selected", "white")])
    st.configure("Treeview.Heading", background=SURF2, foreground=MUTED, relief="flat",
                 font=(FONT, 9, "bold"), padding=(8, 6), borderwidth=0)
    st.map("Treeview.Heading", background=[("active", SURF3)])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    st.configure("Vertical.TScrollbar", background=SURF2, troughcolor=SURF, bordercolor=SURF,
                 arrowcolor=MUTED, lightcolor=SURF2, darkcolor=SURF2, gripcount=0)
    st.map("Vertical.TScrollbar", background=[("active", SURF3)])
    st.configure("TSeparator", background=BORDER)


# --------------------------------------------------------------------------- UI helpers

class RegionSelector(tk.Toplevel):
    """Overlay plein écran sur une capture : on trace un rectangle à la souris."""

    def __init__(self, master, screen, ox, oy, instruction, callback, return_rect=False):
        super().__init__(master)
        self.screen, self.ox, self.oy, self.callback = screen, ox, oy, callback
        self.return_rect = return_rect  # True : callback reçoit (x0, y0, x1, y1) au lieu de l'image
        h, w = screen.shape[:2]
        self.overrideredirect(True)
        self.geometry(f"{w}x{h}+{ox}+{oy}")
        self.attributes("-topmost", True)
        dim = (screen * 0.55).astype(np.uint8)  # écran assombri, zone sélectionnée en clair
        self.photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(dim, cv2.COLOR_BGR2RGB)))
        self.c = tk.Canvas(self, width=w, height=h, highlightthickness=0, cursor="crosshair", bg="black")
        self.c.pack()
        self.c.create_image(0, 0, image=self.photo, anchor="nw")
        px, py = -ox + 40, -oy + 40  # coin haut-gauche de l'écran principal
        self.c.create_rectangle(px - 14, py - 12, px + 760, py + 44, fill=SURF, outline=ACCENT)
        self.c.create_text(px, py + 16, anchor="w", fill=TEXT, font=(FONT, 13, "bold"),
                           text=instruction + "     Échap = annuler")
        self.start = None
        self.rect = None
        self.preview = None
        self.preview_img = None
        self.c.bind("<ButtonPress-1>", self.on_down)
        self.c.bind("<B1-Motion>", self.on_move)
        self.c.bind("<ButtonRelease-1>", self.on_up)
        self.bind("<Escape>", lambda e: self.finish(None))
        self.focus_force()
        self.grab_set()

    def on_down(self, e):
        self.start = (e.x, e.y)
        self.rect = self.c.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT_H, width=2)

    def on_move(self, e):
        if not self.rect:
            return
        x0, x1 = sorted((self.start[0], e.x))
        y0, y1 = sorted((self.start[1], e.y))
        if x1 - x0 > 1 and y1 - y0 > 1:
            crop = self.screen[y0:y1, x0:x1]
            self.preview_img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            if self.preview:
                self.c.itemconfigure(self.preview, image=self.preview_img)
                self.c.coords(self.preview, x0, y0)
            else:
                self.preview = self.c.create_image(x0, y0, image=self.preview_img, anchor="nw")
            self.c.tag_raise(self.rect)
        self.c.coords(self.rect, x0, y0, x1, y1)

    def on_up(self, e):
        if not self.start:
            return
        x0, x1 = sorted((self.start[0], e.x))
        y0, y1 = sorted((self.start[1], e.y))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return
        self.finish((x0, y0, x1, y1) if self.return_rect else self.screen[y0:y1, x0:x1].copy())

    def finish(self, crop):
        self.grab_release()
        self.destroy()
        self.callback(crop)


def show_image_window(master, title, img_bgr, max_w=1300, max_h=800):
    h, w = img_bgr.shape[:2]
    k = min(1.0, max_w / w, max_h / h)
    if k < 1:
        img_bgr = cv2.resize(img_bgr, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    if img_bgr.ndim == 2:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    win = tk.Toplevel(master, bg=BG)
    win.title(title)
    win.attributes("-topmost", True)
    photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)))
    lbl = tk.Label(win, image=photo, bg=BG, bd=0)
    lbl.image = photo
    lbl.pack(padx=10, pady=10)
    win.bind("<Escape>", lambda e: win.destroy())
    dark_titlebar(win)
    return win


def make_pill(text, color, w=50, h=20):
    """Pastille arrondie colorée (dessinée en 4x puis réduite pour l'anticrénelage)."""
    from PIL import ImageDraw, ImageFont
    k = 4
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=h * k // 2, fill=color)
    try:
        font = ImageFont.truetype("segoeuib.ttf", 11 * k)
    except OSError:
        font = ImageFont.load_default()
    d.text((w * k / 2, h * k / 2), text, fill="white", font=font, anchor="mm")
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))


def card(parent, title=None, subtitle=None):
    """Carte = cadre de surface avec titre optionnel. Renvoie (cadre extérieur, corps)."""
    outer = ttk.Frame(parent, style="Card.TFrame", padding=14)
    if title:
        ttk.Label(outer, text=title, style="CardTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(outer, text=subtitle, style="CardMuted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(2, 0))
    body = ttk.Frame(outer, style="Card.TFrame")
    body.pack(fill="both", expand=True, pady=(10 if title or subtitle else 0, 0))
    return outer, body


# --------------------------------------------------------------------------- app

class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        for t in self.cfg["targets"]:
            t.setdefault("found_total", 0)
        BGMODE.update(on=bool(self.cfg["settings"].get("background")),
                  title=self.cfg["settings"].get("window_title", "Epic Seven"))
        self.session_found = {}  # file -> nombre trouvé depuis l'ouverture de l'appli
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.bot = None
        self.clicker = None
        self.run_started = None
        self.last_stats = None

        root.title("E7 Secret Shop Bot")
        if os.path.exists(ICON_PATH):
            try:
                root.iconbitmap(default=ICON_PATH)
            except tk.TclError:
                pass
        root.geometry("1200x740")
        root.minsize(1040, 660)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        apply_theme(root)
        dark_titlebar(root)

        main = ttk.Frame(root, padding=(18, 14, 18, 16))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=3, minsize=620)
        main.columnconfigure(1, weight=2, minsize=340)
        main.rowconfigure(2, weight=1)

        self.build_header(main).grid(row=0, column=0, columnspan=2, sticky="ew")
        self.build_stats(main).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 14))

        nb = ttk.Notebook(main)
        nb.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        nb.add(self.build_targets(nb), text="  Objets  ")
        nb.add(self.build_points(nb), text="  Positions  ")
        nb.add(self.build_resources(nb), text="  Ressources  ")
        nb.add(self.build_settings(nb), text="  Réglages  ")
        nb.add(self.build_autoclick(nb), text="  Auto click  ")
        self.build_log(main).grid(row=2, column=1, sticky="nsew")

        self.refresh_points()
        self.refresh_targets()
        self.refresh_resources()
        self.set_status("Prêt", MUTED)
        self.start_hotkeys()
        self.root.after(100, self.poll_events)
        self.root.after(1000, self.tick)
        self.log("Bienvenue ! F9 = démarrer · F10 = arrêter · souris en haut à gauche = arrêt d'urgence.")
        if not find_tesseract(self.cfg["settings"]["tesseract_path"]):
            self.log("⚠ Tesseract OCR introuvable : la lecture cristaux/or ne marchera pas tant "
                     "qu'il n'est pas installé (ou indique son chemin dans Réglages).")

    # ---------------- header & stats
    def build_header(self, parent):
        f = ttk.Frame(parent)
        left = ttk.Frame(f)
        left.pack(side="left")
        ttk.Label(left, text="Secret Shop Bot", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Epic Seven · actualisation automatique de la boutique secrète",
                  style="Sub.TLabel").pack(anchor="w")

        right = ttk.Frame(f)
        right.pack(side="right")
        self.status_lbl = tk.Label(right, text="", bg=SURF2, fg=MUTED, font=(FONT, 10, "bold"),
                                   padx=14, pady=7)
        self.status_lbl.pack(side="left", padx=(0, 12))
        self.start_btn = ttk.Button(right, text="▶  Démarrer   F9", style="Go.TButton", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(right, text="■  Arrêter   F10", style="Stop.TButton",
                                   command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        return f

    def set_status(self, text, color):
        self.status_lbl.config(text="●  " + text, fg=color)

    def build_stats(self, parent):
        f = ttk.Frame(parent)
        self.stat_widgets = {}
        specs = [("refreshes", "ACTUALISATIONS", "ce lancement"),
                 ("spent", "CRISTAUX DÉPENSÉS", "ce lancement"),
                 ("skystone", "CRISTAUX", "min —"),
                 ("gold", "OR", "min —")]
        for i, (key, label, sub) in enumerate(specs):
            f.columnconfigure(i, weight=1, uniform="stat")
            c = ttk.Frame(f, style="Stat.TFrame", padding=(16, 12))
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            ttk.Label(c, text=label, style="StatLabel.TLabel").pack(anchor="w")
            v = ttk.Label(c, text="0" if key in ("refreshes", "spent") else "—", style="StatValue.TLabel")
            v.pack(anchor="w", pady=(2, 0))
            s = ttk.Label(c, text=sub, style="StatSub.TLabel")
            s.pack(anchor="w")
            self.stat_widgets[key] = (v, s)
        self.update_min_labels()
        return f

    def update_min_labels(self):
        for key, _ in RESOURCES:
            r = self.cfg["resources"][key]
            has = r.get("zone") or r.get("icon")
            txt = f"garder ≥ {fmt_int(int(r.get('min', 0)))}" if r.get("enabled") and has \
                else ("zone du nombre non définie" if not has else "surveillance désactivée")
            self.stat_widgets[key][1].config(text=txt)

    # ---------------- onglets
    def build_targets(self, parent):
        outer, body = card(parent, "Objets à chercher",
                           "Clique sur ON / OFF pour activer un objet · double-clic sur une ligne pour "
                           "placer son point « Acheter » · Total = depuis toujours · Session = depuis "
                           "l'ouverture de l'appli.")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        tf = ttk.Frame(body, style="Card.TFrame")
        tf.grid(row=0, column=0, sticky="nsew")
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)
        self.pill_on = make_pill("ON", "#2f9e66")
        self.pill_off = make_pill("OFF", "#c94554")
        self.tgt_list = ttk.Treeview(tf, columns=("name", "buy", "total", "session"), selectmode="browse")
        self.tgt_list.heading("#0", text="ACTIF", anchor="w")
        self.tgt_list.heading("name", text="OBJET", anchor="w")
        self.tgt_list.heading("buy", text="ACHAT")
        self.tgt_list.heading("total", text="TOTAL")
        self.tgt_list.heading("session", text="SESSION")
        self.tgt_list.column("#0", width=78, minwidth=78, stretch=False)
        self.tgt_list.column("name", width=180, minwidth=120, anchor="w")
        self.tgt_list.column("buy", width=80, anchor="center", stretch=False)
        self.tgt_list.column("total", width=90, anchor="center", stretch=False)
        self.tgt_list.column("session", width=90, anchor="center", stretch=False)
        self.tgt_list.tag_configure("odd", background=SURF)
        self.tgt_list.tag_configure("even", background="#1e2129")
        self.tgt_list.tag_configure("off", foreground="#5d6375")
        self.tgt_list.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tgt_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tgt_list.configure(yscrollcommand=sb.set)
        self.tgt_list.bind("<Button-1>", self.on_target_click)
        self.tgt_list.bind("<Double-1>", lambda e: self.tgt_list.identify_column(e.x) != "#0"
                           and self.tgt_list.identify_row(e.y) and self.set_buy_point())
        self.tgt_list.bind("<Delete>", lambda e: self.delete_target())

        b1 = ttk.Frame(body, style="Card.TFrame")
        b1.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(b1, text="＋ Capturer", style="Accent.TButton", command=self.capture_target).pack(side="left")
        ttk.Button(b1, text="Importer", command=self.import_target).pack(side="left", padx=6)
        ttk.Button(b1, text="Point « Acheter »…", command=self.set_buy_point).pack(side="left")
        ttk.Button(b1, text="Renommer", command=self.rename_target).pack(side="left", padx=6)
        ttk.Button(b1, text="Supprimer", style="Danger.TButton", command=self.delete_target).pack(side="right")

        b2 = ttk.Frame(body, style="Card.TFrame")
        b2.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(b2, text="Tester la détection à l'écran", command=self.test_detection).pack(side="left")
        ttk.Button(b2, text="Remettre le total à zéro", command=self.reset_totals).pack(side="right")
        return outer

    def build_points(self, parent):
        outer, body = card(parent, "Positions de clic",
                           "« Définir » : tu as 3 secondes pour placer la souris sur le bouton dans le "
                           "jeu. Le défilement (glisser) sert à voir les 2 objets du bas ; laisse-le vide "
                           "si inutile.")
        body.columnconfigure(0, weight=1)
        self.point_labels = {}
        for i, (key, label) in enumerate(POINTS):
            row = ttk.Frame(body, style="Card.TFrame")
            row.grid(row=i * 2, column=0, sticky="ew", pady=4)
            row.columnconfigure(0, weight=1)
            ttk.Label(row, text=label, style="Card.TLabel").grid(row=0, column=0, sticky="w")
            lv = ttk.Label(row, text="—", style="ValueOff.TLabel", width=14, anchor="e")
            lv.grid(row=0, column=1, padx=12)
            self.point_labels[key] = lv
            ttk.Button(row, text="Définir", style="Small.TButton",
                       command=lambda k=key, l=label: self.capture_point(k, l)).grid(row=0, column=2)
            ttk.Button(row, text="Voir", style="Small.TButton",
                       command=lambda k=key: self.show_point(k)).grid(row=0, column=3, padx=(6, 0))
            if i < len(POINTS) - 1:
                ttk.Separator(body).grid(row=i * 2 + 1, column=0, sticky="ew")

        s = self.cfg["settings"]
        bg = ttk.Frame(body, style="Card.TFrame")
        bg.grid(row=len(POINTS) * 2, column=0, sticky="ew", pady=(16, 0))
        bg.columnconfigure(1, weight=1)
        ttk.Label(bg, text="Mode arrière-plan", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(bg, style="CardMuted.TLabel", wraplength=560, justify="left",
                  text="Le bot lit la fenêtre du jeu et lui envoie ses clics directement : ta souris reste "
                       "libre. Le jeu peut être derrière d'autres fenêtres, mais pas réduit, et ne doit "
                       "pas bouger. Teste d'abord, bot arrêté et boutique ouverte.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))
        self.bg_var = tk.BooleanVar(value=bool(s.get("background")))
        ttk.Checkbutton(bg, text="Activer", variable=self.bg_var, style="Card.TCheckbutton",
                        command=self.collect).grid(row=2, column=0, sticky="w")
        tf = ttk.Frame(bg, style="Card.TFrame")
        tf.grid(row=2, column=1, sticky="w", padx=14)
        ttk.Label(tf, text="Fenêtre", style="CardMuted.TLabel").pack(side="left")
        self.wintitle_var = tk.StringVar(value=s.get("window_title", "Epic Seven"))
        self.entry(tf, self.wintitle_var, 16).pack(side="left", padx=6)
        ttk.Button(bg, text="Tester l'arrière-plan", style="Accent.TButton",
                   command=self.test_background).grid(row=2, column=2, sticky="e")
        return outer

    def test_background(self):
        """1) capture la fenêtre du jeu ; 2) clique en arrière-plan sur « Actualiser »
        (ça ouvre juste la confirmation, rien n'est dépensé) ; 3) recapture et compare."""
        if self.bot and self.bot.is_alive():
            self.log("⚠ Arrête d'abord le bot (F10) pour faire le test.")
            return
        self.collect()
        prev = dict(BGMODE)
        BGMODE.update(on=True, title=self.cfg["settings"]["window_title"])
        try:
            hwnd = game_window()
            before = capture_window(hwnd)
        except Exception as e:
            BGMODE.update(prev)
            self.log(f"❌ {e}")
            return
        if before.mean() < 3:
            self.log("⚠ La capture de la fenêtre est noire : la lecture en arrière-plan ne marche pas "
                     "avec ce jeu. Le mode arrière-plan ne pourra pas être utilisé.")
            BGMODE.update(prev)
            return
        self.log("✔ Étape 1 : capture de la fenêtre du jeu OK (sans la mettre au premier plan).")
        pt = self.cfg["points"].get("refresh")
        if not pt:
            BGMODE.update(prev)
            show_image_window(self.root, "Capture en arrière-plan", before)
            self.log("⚠ Définis la position « Actualiser » pour tester aussi les clics.")
            return
        mouse = pyautogui.position()
        post_click(*pt)
        self.log("Étape 2 : clic envoyé sur « Actualiser » en arrière-plan…")

        def after():
            try:
                after_img = capture_window(game_window())
            finally:
                BGMODE.update(prev)
            moved = pyautogui.position() != mouse
            diff = float(np.abs(after_img.astype(np.int16) - before.astype(np.int16)).mean())
            if diff > 4:
                self.log(f"✔ Étape 3 : le jeu a réagi (écart d'image {diff:.0f}). Si la confirmation "
                         f"« Utilisez des Pieraciel… » est affichée, le mode arrière-plan fonctionne ! "
                         f"Clique « Annuler » dans le jeu.")
            else:
                self.log(f"❌ Étape 3 : aucune réaction du jeu (écart {diff:.1f}). Les clics en "
                         f"arrière-plan ne passent pas : le mode arrière-plan ne marchera pas.")
            if moved:
                self.log("⚠ La souris a bougé pendant le test (c'était toi ?).")
            h = 360
            a = cv2.resize(before, (int(before.shape[1] * h / before.shape[0]), h))
            b2 = cv2.resize(after_img, (a.shape[1], h))
            sep = np.full((h, 8, 3), 30, np.uint8)
            show_image_window(self.root, "Avant  |  Après le clic en arrière-plan", np.hstack([a, sep, b2]))
        self.root.after(1200, after)

    def build_resources(self, parent):
        outer, body = card(parent, "Ressources — ne pas descendre sous…",
                           "« Sélectionner » : trace un cadre autour du NOMBRE dans la barre du haut "
                           "(sans l'icône ni le bouton +), en laissant un peu de marge à droite si le "
                           "nombre peut gagner un chiffre. La valeur lue s'affiche aussitôt. "
                           "Ne déplace pas la fenêtre du jeu ensuite.")
        self.res_vars = {}
        self.res_status = {}
        heads = ["", "ZONE DU NOMBRE", "MINIMUM À GARDER", "", ""]
        for c, h in enumerate(heads):
            ttk.Label(body, text=h, style="CardHead.TLabel").grid(row=0, column=c, sticky="w", padx=6, pady=(0, 6))
        for i, (key, label) in enumerate(RESOURCES, start=1):
            r = self.cfg["resources"][key]
            en = tk.BooleanVar(value=r.get("enabled", True))
            ttk.Checkbutton(body, text=label, variable=en, style="Card.TCheckbutton",
                            command=self.collect).grid(row=i, column=0, sticky="w", padx=6, pady=6)
            st = ttk.Label(body, text="", style="ValueOff.TLabel", width=16)
            st.grid(row=i, column=1, sticky="w", padx=6)
            self.res_status[key] = st
            mn = tk.StringVar(value=fmt_int(int(r.get("min", 0))))
            self.entry(body, mn, 14).grid(row=i, column=2, sticky="w", padx=6)
            ttk.Button(body, text="Sélectionner", style="Small.TButton",
                       command=lambda k=key, l=label: self.capture_zone(k, l)).grid(row=i, column=3, padx=(6, 0))
            ttk.Button(body, text="Tester", style="Small.TButton",
                       command=lambda k=key, l=label: self.test_resource(k, l)).grid(row=i, column=4, padx=(6, 0))
            self.res_vars[key] = (en, mn)
        return outer

    def build_settings(self, parent):
        outer, body = card(parent, "Réglages", "Les valeurs sont enregistrées automatiquement.")
        s = self.cfg["settings"]
        self.set_vars = {}
        rows = [
            ("threshold", "Seuil de ressemblance", "0 à 1 · plus haut = plus strict"),
            ("delay_click", "Délai après un clic", "secondes"),
            ("delay_after_refresh", "Délai après actualisation", "secondes"),
            ("delay_after_scroll", "Délai après défilement", "secondes"),
            ("delay_after_buy", "Délai après achat", "secondes"),
            ("max_refreshes", "Actualisations max", "0 = illimité"),
            ("scan_attempts", "Scans par page", "1 à 5 · plus = rate moins d'objets, un peu plus lent"),
            ("scan_interval", "Délai entre deux scans", "secondes"),
        ]
        body.columnconfigure(2, weight=1)
        for i, (key, label, hint) in enumerate(rows):
            ttk.Label(body, text=label, style="Card.TLabel").grid(row=i, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=str(s[key]))
            self.entry(body, v, 8).grid(row=i, column=1, sticky="w", padx=12)
            ttk.Label(body, text=hint, style="CardMuted.TLabel").grid(row=i, column=2, sticky="w")
            self.set_vars[key] = v
        i = len(rows)
        self.scroll_up_var = tk.BooleanVar(value=bool(s.get("scroll_up_first")))
        ttk.Checkbutton(body, text="Remonter la liste avant le premier scan (si elle ne revient pas "
                                   "en haut toute seule)", variable=self.scroll_up_var,
                        style="Card.TCheckbutton", command=self.collect).grid(
            row=i, column=0, columnspan=3, sticky="w", pady=(6, 0))
        i += 1
        self.verify_var = tk.BooleanVar(value=bool(s.get("verify_name", True)))
        ttk.Checkbutton(body, text="Vérifier le nom écrit (OCR) avant de valider un objet — "
                                   "évite les fausses détections", variable=self.verify_var,
                        style="Card.TCheckbutton", command=self.collect).grid(
            row=i, column=0, columnspan=3, sticky="w", pady=(2, 0))
        i += 1
        ttk.Separator(body).grid(row=i, column=0, columnspan=3, sticky="ew", pady=10)

        ttk.Label(body, text="Quand un objet apparaît", style="Card.TLabel").grid(row=i + 1, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=s.get("mode", "stop"))
        mf = ttk.Frame(body, style="Card.TFrame")
        mf.grid(row=i + 1, column=1, columnspan=2, sticky="w", padx=12)
        ttk.Radiobutton(mf, text="S'arrêter", value="stop", variable=self.mode_var,
                        style="Card.TRadiobutton", command=self.collect).pack(side="left")
        ttk.Radiobutton(mf, text="Acheter automatiquement", value="buy", variable=self.mode_var,
                        style="Card.TRadiobutton", command=self.collect).pack(side="left", padx=(14, 0))

        ttk.Label(body, text="Décalage « Acheter » (secours)", style="Card.TLabel").grid(row=i + 2, column=0, sticky="w", pady=(8, 0))
        cf = ttk.Frame(body, style="Card.TFrame")
        cf.grid(row=i + 2, column=1, columnspan=2, sticky="w", padx=12, pady=(8, 0))
        ttk.Button(cf, text="Calibrer", style="Small.TButton", command=self.calibrate_buy).pack(side="left")
        self.offset_lbl = ttk.Label(cf, style="CardMuted.TLabel")
        self.offset_lbl.pack(side="left", padx=10)

        ttk.Label(body, text="Chemin tesseract.exe", style="Card.TLabel").grid(row=i + 3, column=0, sticky="w", pady=(8, 0))
        tf = ttk.Frame(body, style="Card.TFrame")
        tf.grid(row=i + 3, column=1, columnspan=2, sticky="ew", padx=12, pady=(8, 0))
        self.tess_var = tk.StringVar(value=s.get("tesseract_path", ""))
        self.entry(tf, self.tess_var, 30).pack(side="left")
        ttk.Button(tf, text="…", style="Small.TButton", command=self.browse_tesseract).pack(side="left", padx=6)
        ttk.Label(tf, text="vide = auto", style="CardMuted.TLabel").pack(side="left")
        self.update_offset_label()
        return outer

    def build_log(self, parent):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=14)
        head = ttk.Frame(outer, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Journal", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(head, text="Effacer", style="Small.TButton",
                   command=lambda: self.log_txt.delete("1.0", "end")).pack(side="right")
        box = ttk.Frame(outer, style="Card.TFrame")
        box.pack(fill="both", expand=True, pady=(10, 0))
        self.log_txt = tk.Text(box, wrap="word", font=(MONO, 9), bg="#14161c", fg=TEXT,
                               insertbackground=TEXT, insertwidth=0, relief="flat", bd=0, padx=10, pady=8,
                               highlightthickness=1, highlightbackground=BORDER,
                               highlightcolor=BORDER, selectbackground=ACCENT, spacing1=2, spacing3=2)
        self.log_txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log_txt.yview)
        sb.pack(side="right", fill="y")
        self.log_txt["yscrollcommand"] = sb.set
        for tag, color in (("time", "#5d6375"), ("found", GOLD), ("ok", GREEN), ("err", RED),
                           ("warn", ORANGE), ("run", ACCENT_H), ("info", TEXT), ("test", "#7fb4ff")):
            self.log_txt.tag_configure(tag, foreground=color)
        self.log_txt.bind("<Key>", lambda e: "break" if e.keysym not in ("c", "C", "a", "A") else None)
        return outer

    def entry(self, parent, var, width):
        e = ttk.Entry(parent, textvariable=var, width=width)
        e.bind("<FocusOut>", lambda ev: self.collect())
        e.bind("<Return>", lambda ev: (self.collect(), self.root.focus_set()))
        return e

    # ---------------- generic
    def log(self, msg):
        first = msg[:1]
        tag = {"✦": "found", "★": "found", "✔": "ok", "❌": "err", "⚠": "warn",
               "▶": "run", "⏹": "run", "◎": "test"}.get(first, "info")
        self.log_txt.insert("end", time.strftime("%H:%M:%S  "), "time")
        self.log_txt.insert("end", msg + "\n", tag)
        self.log_txt.see("end")

    def collect(self):
        """Récupère les valeurs de l'interface dans self.cfg et sauvegarde."""
        s = self.cfg["settings"]
        for key, v in self.set_vars.items():
            try:
                s[key] = int(v.get()) if key in ("max_refreshes", "scan_attempts") \
                    else float(v.get().replace(",", "."))
            except ValueError:
                v.set(str(s[key]))
        s["scan_attempts"] = min(5, max(1, int(s.get("scan_attempts", 2))))
        self.set_vars["scan_attempts"].set(str(s["scan_attempts"]))
        s["scroll_up_first"] = bool(self.scroll_up_var.get())
        s["verify_name"] = bool(self.verify_var.get())
        s["background"] = bool(self.bg_var.get())
        s["window_title"] = self.wintitle_var.get().strip() or "Epic Seven"
        BGMODE.update(on=s["background"], title=s["window_title"])
        s["mode"] = self.mode_var.get()
        s["tesseract_path"] = self.tess_var.get().strip()
        ac = self.cfg["autoclick"]
        try:
            ac["delay_ms"] = max(1, int(float(self.ac_delay.get().replace(",", "."))))
        except ValueError:
            pass
        self.ac_delay.set(str(ac["delay_ms"]))
        ac["button"] = self.ac_button.get()
        self.update_ac_rate()
        for key, (en, mn) in self.res_vars.items():
            r = self.cfg["resources"][key]
            r["enabled"] = bool(en.get())
            raw = "".join(c for c in mn.get() if c.isdigit())
            if raw:
                r["min"] = int(raw)
            mn.set(fmt_int(int(r.get("min", 0))))
        save_config(self.cfg)
        self.update_min_labels()

    def countdown(self, label, seconds, then):
        if seconds <= 0:
            self.set_status("Prêt", MUTED)
            then()
            return
        self.set_status(f"Souris sur : {label}  ·  {seconds}", ORANGE)
        self.root.after(1000, lambda: self.countdown(label, seconds - 1, then))

    def with_screenshot(self, fn):
        """Cache la fenêtre, capture l'écran, la réaffiche puis appelle fn(screen, ox, oy)."""
        self.root.withdraw()
        self.root.update()
        time.sleep(0.35)
        try:
            screen, ox, oy = grab_screen()
        finally:
            self.root.deiconify()
        fn(screen, ox, oy)

    def ask_string(self, title, prompt):
        win = tk.Toplevel(self.root, bg=SURF)
        win.title(title)
        win.resizable(False, False)
        win.transient(self.root)
        frm = ttk.Frame(win, style="Card.TFrame", padding=18)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=prompt, style="Card.TLabel").pack(anchor="w")
        var = tk.StringVar()
        e = ttk.Entry(frm, textvariable=var, width=36)
        e.pack(fill="x", pady=(8, 14))
        res = {"v": None}

        def ok(*_):
            res["v"] = var.get().strip()
            win.destroy()
        btns = ttk.Frame(frm, style="Card.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="Valider", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="right", padx=8)
        win.bind("<Return>", ok)
        win.bind("<Escape>", lambda *_: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{x}+{y}")
        dark_titlebar(win)
        e.focus_set()
        win.grab_set()
        self.root.wait_window(win)
        return res["v"] or None

    # ---------------- points
    def refresh_points(self):
        for key, lbl in self.point_labels.items():
            p = self.cfg["points"].get(key)
            lbl.config(text=f"{p[0]}, {p[1]}" if p else "non défini",
                       style="Value.TLabel" if p else "ValueOff.TLabel")

    def capture_point(self, key, label):
        def done():
            x, y = pyautogui.position()
            self.cfg["points"][key] = [int(x), int(y)]
            save_config(self.cfg)
            self.refresh_points()
            self.log(f"✔ {label} = ({x}, {y})")
            winsound.MessageBeep()
        self.countdown(label, 3, done)

    def show_point(self, key):
        p = self.cfg["points"].get(key)
        if p:
            pyautogui.moveTo(*p, duration=0.3)

    # ---------------- targets
    def refresh_targets(self):
        sel = self.tgt_list.selection()
        self.tgt_list.delete(*self.tgt_list.get_children())
        for i, t in enumerate(self.cfg["targets"]):
            on = t.get("enabled", True)
            tags = ("even" if i % 2 else "odd",) + (() if on else ("off",))
            self.tgt_list.insert("", "end", iid=str(i), text="", tags=tags,
                                 image=self.pill_on if on else self.pill_off,
                                 values=(t["name"],
                                         "✔" if t.get("buy_point") else "—",
                                         fmt_int(t.get("found_total", 0)),
                                         fmt_int(self.session_found.get(t["file"], 0))))
        if sel and self.tgt_list.exists(sel[0]):
            self.tgt_list.selection_set(sel[0])

    def selected_target(self):
        sel = self.tgt_list.selection()
        return int(sel[0]) if sel else None

    def add_target_image(self, img):
        name = self.ask_string("Nouvel objet", "Nom de l'objet (ex. Signet d'alliance) :")
        if not name:
            return
        safe = "".join(c if c.isalnum() else "_" for c in name)
        fname = f"target_{safe}_{int(time.time())}.png"
        save_image(os.path.join(TEMPLATES_DIR, fname), img)
        self.cfg["targets"].append({"name": name, "file": f"templates/{fname}", "enabled": True,
                                    "found_total": 0})
        save_config(self.cfg)
        self.refresh_targets()
        self.log(f"✔ Objet ajouté : {name} ({img.shape[1]}×{img.shape[0]} px)")
        new = str(len(self.cfg["targets"]) - 1)
        self.tgt_list.selection_set(new)
        self.tgt_list.see(new)
        if self.cfg["settings"].get("mode") == "buy":
            self.set_buy_point()

    def capture_target(self):
        def on_shot(screen, ox, oy):
            RegionSelector(self.root, screen, ox, oy, "Trace un cadre autour de l'icône de l'objet",
                           lambda crop: crop is not None and self.add_target_image(crop))
        self.with_screenshot(on_shot)

    def import_target(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                self.add_target_image(img)

    def rename_target(self):
        i = self.selected_target()
        if i is None:
            messagebox.showinfo("Renommer", "Sélectionne d'abord un objet dans la liste.")
            return
        t = self.cfg["targets"][i]
        name = self.ask_string("Renommer", "Nom tel qu'il est écrit dans le jeu (utilisé pour vérifier "
                                           "la détection) :")
        if name:
            self.log(f"✔ « {t['name']} » renommé en « {name} »")
            t["name"] = name
            save_config(self.cfg)
            self.refresh_targets()

    def on_target_click(self, e):
        row = self.tgt_list.identify_row(e.y)
        if row and self.tgt_list.identify_column(e.x) == "#0":
            self.tgt_list.selection_set(row)
            self.toggle_target()
            return "break"

    def toggle_target(self):
        i = self.selected_target()
        if i is not None:
            t = self.cfg["targets"][i]
            t["enabled"] = not t.get("enabled", True)
            save_config(self.cfg)
            self.refresh_targets()

    def delete_target(self):
        i = self.selected_target()
        if i is not None and messagebox.askyesno("Supprimer", f"Supprimer « {self.cfg['targets'][i]['name']} » ?"):
            t = self.cfg["targets"].pop(i)
            try:
                os.remove(abs_path(t["file"]))
            except OSError:
                pass
            save_config(self.cfg)
            self.refresh_targets()

    def reset_totals(self):
        if messagebox.askyesno("Remettre à zéro", "Remettre à zéro le total « depuis toujours » "
                                                  "de tous les objets ?"):
            for t in self.cfg["targets"]:
                t["found_total"] = 0
            save_config(self.cfg)
            self.refresh_targets()
            self.log("✔ Totaux remis à zéro.")

    def on_found(self, file):
        self.session_found[file] = self.session_found.get(file, 0) + 1
        for t in self.cfg["targets"]:
            if t["file"] == file:
                t["found_total"] = t.get("found_total", 0) + 1
        save_config(self.cfg)
        self.refresh_targets()

    def set_buy_point(self):
        """Affiche la capture de l'objet en grand : un clic dessus fixe l'endroit du bouton
        « Acheter ». En jeu, ce point suit l'objet quelle que soit sa ligne."""
        i = self.selected_target()
        if i is None:
            messagebox.showinfo("Point « Acheter »", "Sélectionne d'abord un objet dans la liste.")
            return
        t = self.cfg["targets"][i]
        img = load_template(t["file"])
        if img is None:
            return
        h, w = img.shape[:2]
        k = max(1.0, min(4.0, 760 / w, 420 / h))
        big = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_NEAREST)
        win = tk.Toplevel(self.root, bg=SURF)
        win.title(f"Point « Acheter » · {t['name']}")
        win.resizable(False, False)
        win.transient(self.root)
        frm = ttk.Frame(win, style="Card.TFrame", padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Clique sur le bouton « Acheter » dans la capture.",
                  style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frm, text="Pas de bouton dans ta capture ? Recapture l'objet en incluant son bouton "
                            "« Acheter » sur la même ligne.", style="CardMuted.TLabel").pack(anchor="w", pady=(2, 10))
        photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)))
        c = tk.Canvas(frm, width=big.shape[1], height=big.shape[0], highlightthickness=1,
                      highlightbackground=BORDER, bg=BG, cursor="crosshair")
        c.pack()
        c.create_image(0, 0, image=photo, anchor="nw")
        c.image = photo
        pt = {"v": t.get("buy_point")}

        def draw():
            c.delete("mark")
            if pt["v"]:
                x, y = pt["v"][0] * k, pt["v"][1] * k
                c.create_oval(x - 11, y - 11, x + 11, y + 11, outline=GOLD, width=3, tags="mark")
                c.create_line(x - 18, y, x + 18, y, fill=GOLD, width=2, tags="mark")
                c.create_line(x, y - 18, x, y + 18, fill=GOLD, width=2, tags="mark")

        def on_click(e):
            pt["v"] = [int(e.x / k), int(e.y / k)]
            draw()

        def ok():
            t["buy_point"] = pt["v"]
            save_config(self.cfg)
            self.refresh_targets()
            if pt["v"]:
                self.log(f"✔ Point « Acheter » de {t['name']} = {pt['v']} (dans la capture)")
            win.destroy()

        def clear():
            pt["v"] = None
            draw()
        c.bind("<Button-1>", on_click)
        draw()
        btns = ttk.Frame(frm, style="Card.TFrame")
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Valider", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="Effacer le point", style="Danger.TButton", command=clear).pack(side="left")
        win.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())
        dark_titlebar(win)
        win.grab_set()

    def test_detection(self):
        self.collect()
        th = self.cfg["settings"]["threshold"]

        def on_shot(screen, ox, oy):
            # même logique que le bot (image + vérification du nom écrit)
            vis = screen.copy()
            lines = []
            bot = Bot(json.loads(json.dumps(self.cfg)), self.events, threading.Event())
            best = {}
            try:
                found = bot.scan(best, shot=(screen, ox, oy))
            except Exception as e:
                self.log(f"❌ {e}")
                return
            for t in self.cfg["targets"]:
                if not t.get("enabled", True):
                    continue
                m = [f for f in found if f["file"] == t["file"]]
                lines.append(f"{t['name']} : {len(m)} trouvé(s)" +
                             (f" (image {max(f['score'] for f in m):.2f}, nom vérifié)" if m
                              else f" (meilleur score image {best.get(t['name'], 0):.2f})"))
                for f in m:
                    x, y = int(f["x"] - ox), int(f["y"] - oy)
                    cv2.rectangle(vis, (x, y), (x + f["w"], y + f["h"]), (0, 255, 0), 3)
                    cv2.putText(vis, f"{t['name']} {f['score']:.2f}", (x, max(15, y - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            for key, label in RESOURCES:
                z = self.cfg["resources"][key].get("zone")
                if z:
                    x, y = z[0] - ox, z[1] - oy
                    cv2.rectangle(vis, (x, y), (x + z[2], y + z[3]), (0, 200, 255), 2)
                    cv2.putText(vis, label, (x, max(15, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
            for l in lines:
                self.log("◎ " + l)
            if not lines:
                self.log("⚠ Aucun objet cible actif.")
            show_image_window(self.root, "Détection (vert = objets, jaune = zones des ressources)", vis)
        self.with_screenshot(on_shot)

    # ---------------- resources
    def refresh_resources(self):
        for key, _ in RESOURCES:
            r = self.cfg["resources"][key]
            z = r.get("zone")
            if z:
                txt, ok = f"✔ {z[2]}×{z[3]} px", True
            elif r.get("icon"):
                txt, ok = "ancienne icône", False
            else:
                txt, ok = "non définie", False
            self.res_status[key].config(text=txt, style="Value.TLabel" if ok else "ValueOff.TLabel")
        self.update_min_labels()

    def capture_zone(self, key, label):
        def on_shot(screen, ox, oy):
            def save_zone(rect):
                if rect is None:
                    return
                x0, y0, x1, y1 = rect
                r = self.cfg["resources"][key]
                r["zone"] = [x0 + ox, y0 + oy, x1 - x0, y1 - y0]
                r["icon"] = None  # l'ancienne méthode n'est plus utilisée
                save_config(self.cfg)
                self.refresh_resources()
                self.log(f"✔ Zone du nombre {label} enregistrée")
                self.show_resource_read(key, label, screen, ox, oy)
            RegionSelector(self.root, screen, ox, oy,
                           f"Trace un cadre autour du NOMBRE de {label} (sans l'icône ni le +)",
                           save_zone, return_rect=True)
        self.with_screenshot(on_shot)

    def show_resource_read(self, key, label, screen, ox, oy):
        try:
            val, info = read_resource(screen, ox, oy, self.cfg["resources"][key],
                                      self.cfg["settings"]["threshold"], self.cfg["settings"]["tesseract_path"])
        except Exception as e:
            self.log(f"❌ {e}")
            return
        if not info or "crop" not in info:
            self.log(f"❌ {label} : {(info or {}).get('error', 'zone non définie')}")
            return
        if val is None:
            self.log(f"❌ {label} : illisible (texte OCR '{info['txt']}'). Resélectionne la zone "
                     f"en encadrant uniquement le nombre.")
        else:
            self.log(f"◎ {label} lu : {fmt_int(val)}  — vérifie que c'est bien le chiffre du jeu")
            self.stat_widgets[key][0].config(text=fmt_int(val))
        crop = cv2.resize(info["crop"], None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        bw = cv2.cvtColor(info["bw"], cv2.COLOR_GRAY2BGR)
        bw = cv2.resize(bw, (crop.shape[1], int(bw.shape[0] * crop.shape[1] / bw.shape[1])))
        show_image_window(self.root, f"{label} : {fmt_int(val) if val is not None else 'illisible'}",
                          np.vstack([crop, bw]))

    def test_resource(self, key, label):
        self.collect()
        if not (self.cfg["resources"][key].get("zone") or self.cfg["resources"][key].get("icon")):
            self.log(f"⚠ Sélectionne d'abord la zone du nombre {label}.")
            return
        self.with_screenshot(lambda screen, ox, oy: self.show_resource_read(key, label, screen, ox, oy))

    # ---------------- buy calibration
    def update_offset_label(self):
        off = self.cfg.get("buy_offset")
        self.offset_lbl.config(text=f"décalage {off[0]:+d}, {off[1]:+d} px" if off else "non calibré")

    def calibrate_buy(self):
        self.collect()

        def on_shot(screen, ox, oy):
            found = []
            for t in self.cfg["targets"]:
                for (x, y, w, h, sc) in find_all(screen, load_template(t["file"]), self.cfg["settings"]["threshold"]):
                    found.append((ox + x + w / 2, oy + y + h / 2, t["name"]))
            if not found:
                messagebox.showinfo("Calibrage", "Affiche d'abord un objet cible dans la boutique, "
                                                 "puis relance le calibrage.")
                return
            cx, cy, name = found[0]
            self.log(f"Objet de référence : {name}")

            def done():
                x, y = pyautogui.position()
                self.cfg["buy_offset"] = [int(x - cx), int(y - cy)]
                save_config(self.cfg)
                self.update_offset_label()
                self.log(f"✔ Décalage du bouton Acheter = {self.cfg['buy_offset']}")
                winsound.MessageBeep()
            self.countdown(f"« Acheter » de {name}", 3, done)
        self.with_screenshot(on_shot)

    def browse_tesseract(self):
        p = filedialog.askopenfilename(filetypes=[("tesseract.exe", "tesseract.exe")])
        if p:
            self.tess_var.set(p)
            self.collect()

    # ---------------- run
    def start(self):
        if self.bot and self.bot.is_alive():
            return
        if self.clicker and self.clicker.is_alive():
            self.log("⚠ Arrête d'abord l'auto click (F8) avant de lancer le bot.")
            return
        self.collect()
        self.stop_event.clear()
        self.bot = Bot(json.loads(json.dumps(self.cfg)), self.events, self.stop_event)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.run_started = time.time()
        self.last_stats = None
        self.stat_widgets["refreshes"][0].config(text="0")
        self.stat_widgets["spent"][0].config(text="0")
        self.set_status("En cours", GREEN)
        self.bot.start()

    def stop(self):
        self.stop_event.set()

    def on_done(self, reason):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.update_timer()
        self.run_started = None
        self.log("⏹ " + reason)
        if reason.startswith("Objet trouvé") or "trouvé mais" in reason or reason.startswith("Achat de"):
            # objet à acheter (ou achat raté) : alerte sonore forte, c'est à toi de jouer
            self.set_status(reason[:48], GOLD)
            for _ in range(3):
                winsound.Beep(1200, 180)
                winsound.Beep(1600, 180)
        else:
            self.set_status("Arrêté" if "utilisateur" in reason else reason[:48],
                            MUTED if "utilisateur" in reason else ORANGE)
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.after(1500, lambda: self.root.attributes("-topmost", False))

    def show_stats(self, st):
        self.last_stats = st
        self.stat_widgets["refreshes"][0].config(text=fmt_int(st["refreshes"]))
        if st.get("skystone") is not None:
            spent = (st["skystone_start"] or st["skystone"]) - st["skystone"]
            self.stat_widgets["spent"][0].config(text=fmt_int(max(0, spent)))
            self.stat_widgets["skystone"][0].config(text=fmt_int(st["skystone"]))
        if st.get("gold") is not None:
            self.stat_widgets["gold"][0].config(text=fmt_int(st["gold"]))

    def update_timer(self):
        """Met à jour la durée / cadence sous le compteur d'actualisations."""
        if self.run_started:
            el = int(time.time() - self.run_started)
            n = (self.last_stats or {}).get("refreshes", 0)
            rate = n / (el / 60) if el >= 10 else 0
            self.stat_widgets["refreshes"][1].config(
                text=f"en {el // 60:02d}:{el % 60:02d}" + (f"  ·  {rate:.1f} / min" if rate else ""))

    def tick(self):
        self.update_timer()
        self.root.after(1000, self.tick)

    def poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.log(data)
                elif kind == "stats":
                    self.show_stats(data)
                elif kind == "found":
                    self.on_found(data)
                elif kind == "done":
                    self.on_done(data)
                elif kind == "hotkey":
                    self.start() if data == "start" else self.stop()
                elif kind == "ac":
                    self.ac_start() if data == "start" else self.ac_stop()
        except queue.Empty:
            pass
        self.ac_refresh()
        self.root.after(100, self.poll_events)

    # ---------------- auto click
    def build_autoclick(self, parent):
        outer, body = card(parent, "Auto click",
                           "Clique en boucle à l'endroit où se trouve la souris. F7 = démarrer · "
                           "F8 = arrêter · souris en haut à gauche = arrêt d'urgence.")
        ac = self.cfg["autoclick"]
        body.columnconfigure(2, weight=1)
        ttk.Label(body, text="Délai entre les clics", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.ac_delay = tk.StringVar(value=str(ac.get("delay_ms", 100)))
        self.entry(body, self.ac_delay, 8).grid(row=0, column=1, sticky="w", padx=12)
        self.ac_rate_lbl = ttk.Label(body, style="CardMuted.TLabel")
        self.ac_rate_lbl.grid(row=0, column=2, sticky="w")

        presets = ttk.Frame(body, style="Card.TFrame")
        presets.grid(row=1, column=1, columnspan=2, sticky="w", padx=12, pady=(2, 8))
        for ms in (10, 50, 100, 250, 500, 1000):
            ttk.Button(presets, text=f"{ms} ms", style="Small.TButton", width=7,
                       command=lambda v=ms: (self.ac_delay.set(str(v)), self.collect())).pack(side="left", padx=(0, 4))

        ttk.Label(body, text="Bouton de la souris", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.ac_button = tk.StringVar(value=ac.get("button", "left"))
        bf = ttk.Frame(body, style="Card.TFrame")
        bf.grid(row=2, column=1, columnspan=2, sticky="w", padx=12)
        ttk.Radiobutton(bf, text="Gauche", value="left", variable=self.ac_button,
                        style="Card.TRadiobutton", command=self.collect).pack(side="left")
        ttk.Radiobutton(bf, text="Droit", value="right", variable=self.ac_button,
                        style="Card.TRadiobutton", command=self.collect).pack(side="left", padx=(14, 0))

        ttk.Separator(body).grid(row=3, column=0, columnspan=3, sticky="ew", pady=14)

        st = ttk.Frame(body, style="Card.TFrame")
        st.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.ac_state = tk.Label(st, text="●  Arrêté", bg=SURF2, fg=MUTED, font=(FONT, 11, "bold"),
                                 padx=16, pady=8)
        self.ac_state.pack(side="left")
        self.ac_count_lbl = ttk.Label(st, text="0 clic", style="CardTitle.TLabel")
        self.ac_count_lbl.pack(side="left", padx=16)
        self.ac_stop_btn = ttk.Button(st, text="■  Arrêter   F8", style="Stop.TButton",
                                      command=self.ac_stop, state="disabled")
        self.ac_stop_btn.pack(side="right")
        self.ac_start_btn = ttk.Button(st, text="▶  Démarrer   F7", style="Go.TButton",
                                       command=lambda: self.ac_start(3))
        self.ac_start_btn.pack(side="right", padx=8)
        ttk.Label(body, style="CardMuted.TLabel", wraplength=560, justify="left",
                  text="Astuce : avec le bouton « Démarrer », tu as 3 secondes pour placer la souris. "
                       "Avec F7, ça démarre tout de suite.").grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.update_ac_rate()
        return outer

    def update_ac_rate(self):
        if hasattr(self, "ac_rate_lbl"):
            ms = self.cfg["autoclick"].get("delay_ms", 100)
            self.ac_rate_lbl.config(text=f"ms  ·  ≈ {1000 / ms:.1f} clics / seconde")

    def ac_start(self, countdown=0):
        if self.clicker and self.clicker.is_alive():
            return
        if self.bot and self.bot.is_alive():
            self.log("⚠ Le bot tourne : arrête-le (F10) avant de lancer l'auto click.")
            return
        self.collect()
        if countdown:
            self.ac_state.config(text=f"●  Démarrage dans {countdown}…", fg=ORANGE)
            self.ac_start_btn.config(state="disabled")
            self._ac_pending = self.root.after(1000, lambda: self.ac_start(countdown - 1) if countdown > 1
                                               else (setattr(self, "_ac_pending", None), self.ac_start(0)))
            return
        ac = self.cfg["autoclick"]
        self.clicker = AutoClicker(ac["delay_ms"], ac["button"])
        self.clicker.start()
        self.log(f"▶ Auto click lancé ({ac['delay_ms']} ms, bouton {'gauche' if ac['button'] == 'left' else 'droit'})")

    def ac_stop(self):
        if getattr(self, "_ac_pending", None):
            self.root.after_cancel(self._ac_pending)
            self._ac_pending = None
        if self.clicker and self.clicker.is_alive():
            self.clicker.stop()

    def ac_refresh(self):
        """Met à jour l'état de l'onglet Auto click (appelé toutes les 100 ms)."""
        c = self.clicker
        running = bool(c and c.is_alive())
        pending = bool(getattr(self, "_ac_pending", None))
        if running:
            el = max(0.001, time.time() - c.started)
            self.ac_state.config(text="●  En cours", fg=GREEN)
            self.ac_count_lbl.config(text=f"{fmt_int(c.count)} clics  ·  {c.count / el:.1f} / s")
        elif c and not getattr(c, "_reported", False):
            c._reported = True
            self.log("⏹ Auto click arrêté : " + (c.reason or f"{fmt_int(c.count)} clics."))
            self.ac_count_lbl.config(text=f"{fmt_int(c.count)} clics")
        if not running and not pending:
            self.ac_state.config(text="●  Arrêté", fg=MUTED)
        self.ac_start_btn.config(state="disabled" if running or pending else "normal")
        self.ac_stop_btn.config(state="normal" if running or pending else "disabled")

    def start_hotkeys(self):
        if not pynput_keyboard:
            return

        def on_press(key):
            if key == pynput_keyboard.Key.f9:
                self.events.put(("hotkey", "start"))
            elif key == pynput_keyboard.Key.f10:
                self.stop_event.set()
                self.events.put(("hotkey", "stop"))
            elif key == pynput_keyboard.Key.f7:
                self.events.put(("ac", "start"))
            elif key == pynput_keyboard.Key.f8:
                if self.clicker:
                    self.clicker.stop()  # arrêt immédiat, sans attendre l'interface
                self.events.put(("ac", "stop"))
        self.listener = pynput_keyboard.Listener(on_press=on_press)
        self.listener.daemon = True
        self.listener.start()

    def on_close(self):
        self.stop_event.set()
        if self.clicker:
            self.clicker.stop()
        try:
            self.collect()
        except Exception:
            pass
        self.root.destroy()


def selftest():
    """`SecretShopBot.exe --selftest` : vérifie l'OCR et la capture, écrit selftest.txt à côté."""
    lines = [f"frozen={FROZEN}", f"base={BASE_DIR}", f"bundle={BUNDLE_DIR}"]
    try:
        exe = find_tesseract("")
        lines.append(f"tesseract={exe}")
        img = np.full((40, 220, 3), 25, np.uint8)
        cv2.putText(img, "48,250,000", (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2)
        lines.append(f"ocr_nombre={ocr_number(img, '')[0]}")
        img = np.full((50, 420, 3), 25, np.uint8)
        cv2.putText(img, "Medailles mystiques", (6, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 2)
        lines.append(f"ocr_nom={' '.join(ocr_text(img, '').split())}")
        lines.append(f"capture={grab_screen()[0].shape}")
        lines.append(f"icone={os.path.exists(ICON_PATH)}")
        lines.append("OK")
    except Exception:
        lines.append(traceback.format_exc())
    with open(os.path.join(BASE_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    root = tk.Tk()
    App(root)
    root.mainloop()
