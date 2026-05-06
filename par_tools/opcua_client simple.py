# opcua_client.py
from opcua import Client, ua
import os, json, csv
from .utils import serialize_value

# какие browse_name пропускать полностью
SKIP_BROWSE_NAMES = {
    "Dimensions",   # служебные свойства массивов
}

# какие ветки Par_Db не читать (по верхнему имени внутри Par_Db)
SKIP_TOP_PAR_BLOCKS = {
    "AI_Par",
    # сюда же можно добавить "ZonePar", "GenPar" и т.п. при желании
}

# маппинг стандартных DataType → VariantType
DT_TO_VTYPE = {
    ua.NodeId(ua.ObjectIds.Boolean): ua.VariantType.Boolean,
    ua.NodeId(ua.ObjectIds.SByte):   ua.VariantType.SByte,
    ua.NodeId(ua.ObjectIds.Byte):    ua.VariantType.Byte,
    ua.NodeId(ua.ObjectIds.Int16):   ua.VariantType.Int16,
    ua.NodeId(ua.ObjectIds.UInt16):  ua.VariantType.UInt16,
    ua.NodeId(ua.ObjectIds.Int32):   ua.VariantType.Int32,
    ua.NodeId(ua.ObjectIds.UInt32):  ua.VariantType.UInt32,
    ua.NodeId(ua.ObjectIds.Int64):   ua.VariantType.Int64,
    ua.NodeId(ua.ObjectIds.UInt64):  ua.VariantType.UInt64,
    ua.NodeId(ua.ObjectIds.Float):   ua.VariantType.Float,
    ua.NodeId(ua.ObjectIds.Double):  ua.VariantType.Double,
    ua.NodeId(ua.ObjectIds.String):  ua.VariantType.String,
}

# пользовательские типы: WORD и TIME
CUSTOM_TYPES = {
    (3, 3002): 'WORD',  # ns=3;i=3002 — пользовательский тип WORD
    (3, 3005): 'TIME',  # ns=3;i=3005 — пользовательский TIME-тип
}

def normalize_nodeid(nid):
    # приводим к (ns, i) для Numeric
    if isinstance(nid, ua.NodeId) and nid.IdentifierType == ua.NodeIdType.Numeric:
        return (nid.NamespaceIndex, nid.Identifier)
    return None


def safe_set_value(node, value, path):
    dt_nodeid = None
    try:
        dt_nodeid = node.get_data_type()
        ns = dt_nodeid.NamespaceIndex
        ident = dt_nodeid.Identifier

        # 1) Пользовательские типы: WORD и TIME
        custom_type = CUSTOM_TYPES.get((ns, ident))
        if custom_type:
            if custom_type == 'WORD':
                # Обработка WORD (UInt16) — проверяем диапазон 0–65535
                try:
                    word_value = int(value)
                    if not (0 <= word_value <= 65535):
                        raise ValueError(f"WORD value out of range: {word_value} (must be 0–65535)")
                    variant = ua.Variant(word_value, ua.VariantType.UInt16)
                    node.set_value(variant)
                    return True
                except (ValueError, TypeError) as e:
                    print(f"⚠ WORD-конверсия не удалась для {path}: value={value}, ошибка: {e}")
                    return False

            elif custom_type == 'TIME':
                # Обработка TIME (UInt32) — проверяем диапазон 0–4294967295
                try:
                    ms = int(value)
                    if not (0 <= ms <= 4294967295):
                        raise ValueError(f"TIME value out of range: {ms}")
                    variant = ua.Variant(ms)
                    node.set_value(variant)
                    return True
                except (ValueError, TypeError) as e:
                    print(f"⚠ TIME-конверсия не удалась для {path}: value={value}, ошибка: {e}")
                    return False

        # 2) Стандартные типы по DT_TO_VTYPE
        vtype = DT_TO_VTYPE.get(dt_nodeid)
        if vtype is not None:
            node.set_value(ua.Variant(value, vtype))
            return True

        # 3) Фолбэк по python‑типу
        if isinstance(value, bool):
            vtype = ua.VariantType.Boolean
        elif isinstance(value, int):
            vtype = ua.VariantType.Int32
        elif isinstance(value, float):
            vtype = ua.VariantType.Double
        elif isinstance(value, str):
            vtype = ua.VariantType.String
        else:
            node.set_value(value)
            return True

        node.set_value(ua.Variant(value, vtype))
        return True

    except Exception as e:
        print(f"❌ {path}: {e} (DataType={dt_nodeid})")
        return False


def make_endpoint(device, config, port_input):
    port = port_input or str(config["port"])
    return f"opc.tcp://{device['ip']}:{port}{config['endpoint_path']}"


def connect_client(endpoint):
    client = Client(endpoint)
    # при желании можно включить таймауты:
    # client.session_timeout = 20000
    # client.secure_channel_timeout = 20000
    try:
        client.connect()
        print("✅ Подключено к ПЛК")
        return client
    except Exception as e:
        print(f"❌ Не удалось подключиться к {endpoint}: {e}")
        return None


def jump_to_globalvars(client):
    root = client.get_root_node()
    try:
        objects = root.get_child(["0:Objects"])
    except Exception:
        return None

    dev_set = None
    for ch in objects.get_children():
        try:
            name = ch.get_browse_name().Name
            if name.lower().startswith("deviceset"):
                dev_set = ch
                break
        except:
            continue
    if dev_set is None:
        return None

    device = None
    for ch in dev_set.get_children():
        try:
            name = ch.get_browse_name().Name
            nid = ch.nodeid.to_string()
            if "cfurn" in name.lower() or "|plc|" in nid:
                device = ch
                break
        except:
            continue
    if device is None:
        return None

    resources = None
    for ch in device.get_children():
        try:
            if ch.get_browse_name().Name.lower().startswith("resources"):
                resources = ch
                break
        except:
            continue
    if resources is None:
        return None

    app = None
    for ch in resources.get_children():
        try:
            if "application" in ch.get_browse_name().Name.lower():
                app = ch
                break
        except:
            continue
    if app is None:
        return None

    gvars = None
    for ch in app.get_children():
        try:
            if "globalvars" in ch.get_browse_name().Name.lower():
                gvars = ch
                break
        except:
            continue
    return gvars


def browse_level(node, level_name="Уровень"):
    children = node.get_children()
    entries = []
    print(f"\n=== {level_name} ===")
    for idx, ch in enumerate(children, 1):
        try:
            bn = ch.get_browse_name()
            name = bn.Name
            nid = ch.nodeid.to_string()
            print(f"{idx}. {name}  [{nid}]")
            entries.append((ch, name, nid))
        except:
            continue
    print("0. Назад / выход")
    return entries


def interactive_tree_select_from_node(start_node):
    level = start_node
    stack = []
    first = True
    while True:
        entries = browse_level(level, "Дерево OPC UA")
        if first:
            print("\nПодсказка: выберите, например, Par_Db и нажмите 's', чтобы сохранить этот блок.")
            first = False
        choice = input("Номер (0=назад, q=выход): ").strip().lower()
        if choice == "q":
            print("Выход из выбора.")
            return None
        if choice == "0":
            if not stack:
                print("Выход из выбора.")
                return None
            level = stack.pop()
            continue
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(entries):
                print("❌ Неверный номер")
                continue
        except:
            print("Введите номер.")
            continue

        node, name, nid = entries[idx]
        print(f"\nВы выбрали: {name} [{nid}]")
        act = input("Enter = углубиться, 's' = выбрать этот узел как блок настроек: ").strip().lower()
        if act == "s":
            return node
        else:
            stack.append(level)
            level = node


# ---------- хелперы с ретраями ----------

def safe_get_children(node, prefix, retries=2):
    for attempt in range(retries):
        try:
            return node.get_children()
        except Exception as e:
            print(f"    CHILDREN ERROR для {prefix} попытка {attempt+1}: {repr(e)}")
    return []


def safe_get_value(node, prefix, retries=2):
    for attempt in range(retries):
        try:
            return node.get_value()
        except Exception as e:
            print(f"    RAW ERROR get_value для {prefix} попытка {attempt+1}: {repr(e)}")
    raise TimeoutError(f"get_value timeout for {prefix}")


def read_struct_recursive(node, prefix):
    """
    Рекурсивно читает структуру / массив:
    - обходит дочерние узлы;
    - для узлов с детьми вызывает себя рекурсивно;
    - для листьев читает value.
    """
    all_tags = {}

    # 1. Дочерние узлы
    children = safe_get_children(node, prefix)

    if children:
        for ch in children:
            # имя узла
            try:
                name = ch.get_browse_name().Name
            except Exception:
                continue

            # глобальные исключения по имени (например, Dimensions)
            if name in SKIP_BROWSE_NAMES:
                print(f"  ⏭ пропускаю {prefix}.{name}")
                continue

            # отладка browse_name
            try:
                bn = ch.get_browse_name()
                print(f"    DEBUG child of {prefix}: browse_name={repr(bn)}")
            except Exception:
                pass

            full_key = f"{prefix}.{name}"

            # 2. Если у узла есть свои дети – рекурсия
            sub_children = safe_get_children(ch, full_key)
            if sub_children:
                sub_tags = read_struct_recursive(ch, prefix=full_key)
                all_tags.update(sub_tags)
                continue

            # 3. Лист – читаем значение
            try:
                raw_value = safe_get_value(ch, full_key)
                value = serialize_value(raw_value)
                node_id = ch.nodeid.to_string()
                all_tags[full_key] = {"value": value, "nodeid": node_id}
                print(f"    ✅ {node_id}: type={type(raw_value)}, value={value}")
            except Exception:
                print(f"    ↪ {full_key} (не переменная / без value)")
                continue

    return all_tags


# ---------- чтение блоков ----------

def read_block_tags(client, block_node, block_label="SelectedBlock"):
    all_tags = {}
    children = block_node.get_children()
    print(f"\n📂 {block_label}: {len(children)} элементов")

    for child in children:
        try:
            name = child.get_browse_name().Name
        except Exception:
            continue

        # глобальные исключения по имени
        if name in SKIP_BROWSE_NAMES:
            print(f"  ⏭ пропускаю {name}")
            continue

        # исключения верхнего уровня внутри Par_Db
        if block_label.endswith("Par_Db") and name in SKIP_TOP_PAR_BLOCKS:
            print(f"  ⏭ пропускаю блок {block_label}.{name}")
            continue

        full_key = f"{block_label}.{name}"

        # если у узла есть дочерние узлы – раскрываем структуру
        children2 = safe_get_children(child, full_key)
        if children2:
            print(f"  🔎 раскрываю структуру {full_key}")
            sub_tags = read_struct_recursive(child, prefix=full_key)
            all_tags.update(sub_tags)
            continue

        # иначе это скаляр – читаем как раньше
        try:
            raw_value = safe_get_value(child, full_key)
            value = serialize_value(raw_value)
            node_id = child.nodeid.to_string()
            all_tags[full_key] = {"value": value, "nodeid": node_id}
            print(f"  ✅ {name}")
        except Exception:
            print(f"  ↪ {name} (не переменная / без value)")
            continue

    print(f"📊 Всего прочитано: {len(all_tags)} тегов")
    return all_tags


def read_paths_tags(client, paths):
    all_tags = {}
    for idx, p in enumerate(paths, 1):
        path = p["path"]
        print(f"\n📂 [{idx}/{len(paths)}] {path}")
        try:
            node = client.get_node(path)
            block_tags = read_block_tags(client, node, block_label=path)
            all_tags.update(block_tags)
        except Exception as e:
            print(f"❌ Ошибка блока {path}: {e}")
    return all_tags


def write_tags(client, data_dir, filename):
    filepath = os.path.join(data_dir, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            all_tags = json.load(f)
    except FileNotFoundError:
        print(f"❌ Файл {filepath} не найден")
        return False

    written = 0
    total = len(all_tags)

    for path, data in all_tags.items():
        nodeid = data.get("nodeid")
        if not nodeid:
            print(f"❌ {path}: нет nodeid в JSON")
            continue

        try:
            node = client.get_node(nodeid)
        except Exception as e:
            print(f"❌ {path}: не удалось получить узел {nodeid}: {e}")
            continue

        if safe_set_value(node, data.get("value"), path):
            print(f"✅ {path}")
            written += 1

    print(f"📊 Записано: {written}/{total} тегов")
    return True
