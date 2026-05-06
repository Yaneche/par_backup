# opcua_client.py
from opcua import Client, ua
import os, json, time
from itertools import islice
from .utils import serialize_value
import yaml

# что пропускаем по имени browse_name
SKIP_NAMES = {
    "Dimensions",
    "AI_Par",
    "GasFlowCnt",
}

# что всегда включаем, даже если родитель в SKIP_NAMES
INCLUDE_ALWAYS = {
    "rKCount",
}

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

CUSTOM_TYPES = {
    (3, 3002): 'WORD',
    (3, 3005): 'TIME',
}


def make_variant_for_node(node, value, path):
    dt_nodeid = None
    try:
        dt_nodeid = node.get_data_type()
        ns = dt_nodeid.NamespaceIndex
        ident = dt_nodeid.Identifier

        custom_type = CUSTOM_TYPES.get((ns, ident))
        if custom_type == 'WORD':
            word_value = int(value)
            if not (0 <= word_value <= 65535):
                raise ValueError(f"WORD value out of range: {word_value} (must be 0–65535)")
            return ua.Variant(word_value, ua.VariantType.UInt16)

        if custom_type == 'TIME':
            ms = int(value)
            if not (0 <= ms <= 4294967295):
                raise ValueError(f"TIME value out of range: {ms}")
            return ua.Variant(ms)

        vtype = DT_TO_VTYPE.get(dt_nodeid)
        if vtype is not None:
            return ua.Variant(value, vtype)

        if isinstance(value, bool):
            vtype = ua.VariantType.Boolean
        elif isinstance(value, int):
            vtype = ua.VariantType.Int32
        elif isinstance(value, float):
            vtype = ua.VariantType.Double
        elif isinstance(value, str):
            vtype = ua.VariantType.String
        else:
            return ua.Variant(value)

        return ua.Variant(value, vtype)

    except Exception as e:
        print(f"❌ {path}: {e} (DataType={dt_nodeid})")
        return None


def safe_set_value(node, value, path):
    variant = make_variant_for_node(node, value, path)
    if variant is None:
        return False
    try:
        node.set_value(variant)
        return True
    except Exception as e:
        print(f"❌ {path}: {e}")
        return False


def make_endpoint(device, config, port_input):
    port = port_input or str(config["port"])
    return f"opc.tcp://{device['ip']}:{port}{config['endpoint_path']}"


def connect_client(endpoint):
    client = Client(endpoint)
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
        except Exception:
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
        except Exception:
            continue
    if device is None:
        return None

    resources = None
    for ch in device.get_children():
        try:
            if ch.get_browse_name().Name.lower().startswith("resources"):
                resources = ch
                break
        except Exception:
            continue
    if resources is None:
        return None

    app = None
    for ch in resources.get_children():
        try:
            if "application" in ch.get_browse_name().Name.lower():
                app = ch
                break
        except Exception:
            continue
    if app is None:
        return None

    gvars = None
    for ch in app.get_children():
        try:
            if "globalvars" in ch.get_browse_name().Name.lower():
                gvars = ch
                break
        except Exception:
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
        except Exception:
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
        except Exception:
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


def chunked(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk


def read_leaves_batch(client, leaf_nodes, leaf_meta, batch_size=200):
    all_tags = {}

    for chunk in chunked(list(zip(leaf_nodes, leaf_meta)), batch_size):
        nodes_chunk = [n for (n, _) in chunk]
        try:
            values = client.get_values(nodes_chunk)
        except Exception as e:
            print(f"⚠ Ошибка batch-read: {e}, пробую по одному")
            for (node, (full_key, _)) in chunk:
                try:
                    raw_value = safe_get_value(node, full_key)
                    value = serialize_value(raw_value)
                    node_id = node.nodeid.to_string()
                    all_tags[full_key] = {"value": value, "nodeid": node_id}
                    print(f"    ✅ {node_id}: type={type(raw_value)}, value={value}")
                except Exception as e2:
                    print(f"    ↪ {full_key} (не переменная / без value, {e2})")
            continue

        for (node, (full_key, _)), raw_value in zip(chunk, values):
            try:
                value = serialize_value(raw_value)
                node_id = node.nodeid.to_string()
                all_tags[full_key] = {"value": value, "nodeid": node_id}
                print(f"    ✅ {node_id}: type={type(raw_value)}, value={value}")
            except Exception as e:
                print(f"    ↪ {full_key} (не переменная / без value, {e})")

    return all_tags


def read_struct_recursive(node, prefix, client=None):
    """Рекурсивный обход: собираем листья"""
    all_tags = {}
    leaf_nodes = []
    leaf_meta = []

    children = safe_get_children(node, prefix)

    for ch in children:
        try:
            name = ch.get_browse_name().Name
        except Exception:
            continue

        full_key = f"{prefix}.{name}"

        if name == "Dimensions":
            print(f"  ⏭ пропускаю {full_key}")
            continue

        sub_children = safe_get_children(ch, full_key)

        if not sub_children:
            parent_name = prefix.split(".")[-1] if prefix else ""
            if parent_name in SKIP_NAMES and name not in INCLUDE_ALWAYS:
                print(f"  ⏭ пропускаю лист {full_key} (внутри {parent_name})")
                continue

            leaf_nodes.append(ch)
            leaf_meta.append((full_key, ch))
            continue

        if name in INCLUDE_ALWAYS:
            print(f"  ⭐ включаю структуру {full_key}")
            sub_tags = read_struct_recursive(ch, full_key, client)
            all_tags.update(sub_tags)
            continue

        if name in SKIP_NAMES and name not in INCLUDE_ALWAYS:
            print(f"  ⏭ пропускаю блок {full_key}")
            continue

        print(f"  🔎 раскрываю структуру {full_key}")
        sub_tags = read_struct_recursive(ch, full_key, client)
        all_tags.update(sub_tags)

    if leaf_nodes and client is not None:
        batch_tags = read_leaves_batch(client, leaf_nodes, leaf_meta)
        all_tags.update(batch_tags)

    return all_tags


def read_block_tags(client, block_node, block_label="SelectedBlock"):
    all_tags = {}
    children = block_node.get_children()
    print(f"\n📂 {block_label}: {len(children)} элементов")

    leaf_nodes = []
    leaf_meta = []

    for child in children:
        try:
            name = child.get_browse_name().Name
        except Exception:
            continue

        if name == "Dimensions":
            print(f"  ⏭ пропускаю {name}")
            continue

        if name in SKIP_NAMES and name not in INCLUDE_ALWAYS:
            print(f"  ⏭ пропускаю блок {block_label}.{name}")
            continue

        full_key = f"{block_label}.{name}"

        children2 = safe_get_children(child, full_key)
        if children2:
            print(f"  🔎 раскрываю структуру {full_key}")
            sub_tags = read_struct_recursive(child, prefix=full_key, client=client)
            all_tags.update(sub_tags)
        else:
            leaf_nodes.append(child)
            leaf_meta.append((full_key, child))

    if leaf_nodes:
        batch_tags = read_leaves_batch(client, leaf_nodes, leaf_meta)
        all_tags.update(batch_tags)

    print(f"📊 Всего прочитано: {len(all_tags)} тегов")
    return all_tags


# ---------- дерево <-> плоский словарь ----------

def insert_by_path(root, path, leaf_dict):
    parts = path.split(".")
    cur = root
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = leaf_dict


def build_tree_from_flat(flat_tags):
    """Строит дерево из плоского словаря"""
    tree = {}
    for full_key, data in flat_tags.items():
        insert_by_path(tree, full_key, data)
    return tree


def flatten_tree(tree, prefix=""):
    flat = {}

    def _walk(node, cur_path_parts):
        if (
            isinstance(node, dict)
            and "value" in node
            and "nodeid" in node
            and len(node) == 2
        ):
            full_key = ".".join(cur_path_parts)
            flat[full_key] = {"value": node["value"], "nodeid": node["nodeid"]}
            return

        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, cur_path_parts + [k])

    start_parts = [prefix] if prefix else []
    _walk(tree, start_parts)
    return flat


def simplify_path(full_path, block_name):
    """
    Упрощает путь тега, оставляя только имена блоков.
    Пример: "ns=4;s=|var|PLC210 OPC-UA.Application.Par210_1.M10_xxx"
    Станет: "Par210_1.M10_xxx"
    """
    # Ищем block_name в пути
    if block_name in full_path:
        # Берём всё после block_name
        parts = full_path.split(block_name)
        if len(parts) > 1:
            return block_name + parts[1]
    return full_path


def read_paths_tags(client, paths):
    """
    Возвращает дерево, где каждый блок - отдельный корневой узел.
    """
    all_tags = {}
    start = time.time()

    for idx, p in enumerate(paths, 1):
        path = p["path"]
        block_name = p.get("name", path.split('.')[-1])
        print(f"\n📂 [{idx}/{len(paths)}] {block_name}")
        
        try:
            node = client.get_node(path)
            block_tags = read_block_tags(client, node, block_label=block_name)
            
            # Упрощаем пути тегов
            for tag_path, tag_data in block_tags.items():
                # Извлекаем имя блока из пути
                # Ищем block_name в пути
                simplified = tag_path
                if block_name in tag_path:
                    # Берём часть после block_name
                    parts = tag_path.split(block_name)
                    if len(parts) > 1:
                        simplified = block_name + parts[1]
                
                all_tags[simplified] = tag_data
                
        except Exception as e:
            print(f"❌ Ошибка блока {path}: {e}")

    elapsed = time.time() - start
    print(f"⏱ Чтение завершено за {elapsed:.2f} с")

    # Строим дерево
    tree = build_tree_from_flat(all_tags)
    return tree


def save_tags_json(tree, data_dir, filename):
    os.makedirs(data_dir, exist_ok=True)
    filepath = os.path.join(data_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    count = len(flatten_tree(tree))
    print(f"💾 Сохранено {count} тегов → {os.path.basename(filepath)}")
    return filepath


def save_tags_yaml(tree, data_dir, filename):
    os.makedirs(data_dir, exist_ok=True)
    filepath = os.path.join(data_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.safe_dump(tree, f, allow_unicode=True, sort_keys=False)
    count = len(flatten_tree(tree))
    print(f"💾 Сохранено {count} тегов → {os.path.basename(filepath)}")
    return filepath


def load_tags_yaml(data_dir, filename):
    filepath = os.path.join(data_dir, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        tree = yaml.safe_load(f)
    flat = flatten_tree(tree)
    print(f"📂 Загружено из YAML {len(flat)} тегов")
    return flat


def write_tags(client, data_dir, filename, batch_size=50):
    """Запись тегов в ПЛК из YAML-файла"""
    try:
        flat_tags = load_tags_yaml(data_dir, filename)
    except FileNotFoundError:
        print(f"❌ Файл {filename} не найден в {data_dir}")
        return False

    items = list(flat_tags.items())
    total = len(items)
    written = 0
    start = time.time()

    for chunk in chunked(items, batch_size):
        nodes = []
        variants = []
        paths = []

        for path, data in chunk:
            nodeid = data.get("nodeid")
            if not nodeid:
                print(f"❌ {path}: нет nodeid в YAML")
                continue

            try:
                node = client.get_node(nodeid)
            except Exception as e:
                print(f"❌ {path}: не удалось получить узел {nodeid}: {e}")
                continue

            variant = make_variant_for_node(node, data.get("value"), path)
            if variant is None:
                continue

            nodes.append(node)
            variants.append(variant)
            paths.append(path)

        if not nodes:
            continue

        try:
            client.set_values(nodes, variants)
            for path in paths:
                print(f"✅ {path}")
                written += 1
        except Exception as e:
            print(f"⚠ Ошибка batch-write: {e}, пробую по одному")
            for node, var, path in zip(nodes, variants, paths):
                try:
                    node.set_value(var)
                    print(f"✅ {path}")
                    written += 1
                except Exception as e2:
                    print(f"❌ {path}: {e2}")

    elapsed = time.time() - start
    print(f"📊 Записано: {written}/{total} тегов")
    print(f"⏱ Запись завершена за {elapsed:.2f} с")
    return True