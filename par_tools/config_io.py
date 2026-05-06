# config_io.py
import json, os, glob, re
from datetime import datetime
from par_tools.paths import CONFIG_FILE, PLC_DATA_DIR



def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    config = {
        "devices": {
            "1": {"name": "Колпаковая печь 1", "ip": "192.168.15.20"},
            "2": {"name": "Колпаковая печь 2", "ip": "192.168.15.40"},
            "3": {"name": "Колпаковая печь 3", "ip": "192.168.15.60"},
            "4": {"name": "Колпаковая печь 4", "ip": "192.168.15.80"},
            "5": {"name": "Сушильная камера 1", "ip": "192.168.15.100"},
            "6": {"name": "Сушильная камера 2", "ip": "192.168.15.110"},
            "7": {"name": "Сушильная камера 3", "ip": "192.168.15.120"},
        },
        "port": 4840,
        "endpoint_path": "/freeopcua/server",
        "devices_paths": {}
    }
    save_config(config)
    print(f"✅ Создан {CONFIG_FILE}")
    return config


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def add_device(config):
    name = input("Название ПЛК: ").strip()
    ip = input("IP адрес: ").strip()
    if not name or not ip:
        print("❌ Пустое имя/IP, не добавлено")
        return
    num = str(len(config["devices"]) + 1)
    config["devices"][num] = {"name": name, "ip": ip}
    save_config(config)
    print(f"✅ Добавлено: {num}. {name} - {ip}")


def select_device(config):
    print("\n=== ПЛК ===")
    for key, dev in config["devices"].items():
        print(f"{key}. {dev['name']} - {dev['ip']}")
    print("0. Добавить новый...")
    print("q. Выход")
    while True:
        choice = input("\nВыбор (0-X, q=выход): ").strip().lower()
        if choice == "q":
            return None
        if choice == "0":
            add_device(config)
            continue
        if choice in config["devices"]:
            return config["devices"][choice]
        print("❌ Неверный выбор")


def save_device_paths(config, device_ip, paths):
    config.setdefault("devices_paths", {})
    config["devices_paths"][device_ip] = paths
    save_config(config)
    print(f"💾 Пути Par-блоков сохранены для {device_ip}")


def load_device_paths(config, device_ip):
    return config.get("devices_paths", {}).get(device_ip, [])


def get_files_by_name(name_filter=""):
    os.makedirs(PLC_DATA_DIR, exist_ok=True)
    pattern = os.path.join(PLC_DATA_DIR, f"*{name_filter}*.json")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return [os.path.basename(f) for f in files]


def select_file(files):
    if not files:
        print("❌ Файлы не найдены")
        return None
    print("\n=== Файлы настроек (новые сверху) ===")
    for i, fname in enumerate(files, 1):
        print(f"{i}. {fname}")
    ans = input("\nВыбор (Enter=1, q=выход): ").strip().lower()
    if ans == "q":
        return None
    try:
        idx = int(ans or "1") - 1
        return files[idx] if 0 <= idx < len(files) else files[0]
    except:
        return files[0]


def get_filename(device):
    os.makedirs(PLC_DATA_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = re.sub(r"[^\w\s-]", "", device["name"]).strip().replace(" ", "_")
    return os.path.join(PLC_DATA_DIR, f"{safe_name}-{device['ip']}-{timestamp}.yaml")
