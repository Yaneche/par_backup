# utils.py
from opcua import ua

def ask_yes_no(prompt, default=False):
    yes_set = {"y", "yes", "1", "д", "да"}
    no_set = {"n", "no", "0", "н", "нет", "т"}  # 'т' = физическая N в русской раскладке
    while True:
        ans = input(prompt).strip().lower()
        if not ans:
            return default
        if ans in yes_set:
            return True
        if ans in no_set:
            return False
        print("Введите: y/n, д/н, 1/0 (в русской раскладке 'н'='да', 'т'='нет').")


def serialize_value(val):
    if isinstance(val, list):
        return [serialize_value(v) for v in val]
    if isinstance(val, ua.ExtensionObject):
        body = val.Body
        try:
            return serialize_value(body)
        except Exception:
            return str(val)
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    return str(val)
