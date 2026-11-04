"""核心逻辑自检。不依赖真实服务端数据，可在 CI 中运行。

覆盖：
  · 道具可堆叠判定（复刻 CItemManager::AddItem 规则）
  · 商城字段范围（来自 CPacketManager::SendShopUpdate 写入宽度）
  · 账号/密码校验（复刻 CUserManager::RegisterUser）
  · 窗口几何解析（含副屏负坐标）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gm-tool"))
sys.path.insert(0, str(ROOT / "auth-server"))

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)


def test_item_rules() -> None:
    print("\n[Item stacking rules]")
    from core.itemdb import is_stackable

    check("cat9/use0 is stackable", is_stackable(9, 0))
    check("cat9/use1 is stackable", is_stackable(9, 1))
    check("cat9/use6 is not stackable", not is_stackable(9, 6))
    check("cat8/use0 is stackable", is_stackable(8, 0))
    check("cat8/use2 is stackable", is_stackable(8, 2))
    check("cat8/use1 is not stackable", not is_stackable(8, 1))
    check("cat1 is not stackable", not is_stackable(1, 1))


def test_shop_limits() -> None:
    print("\n[Shop field ranges]")
    from core.shop import FIELD_LIMITS, SHOP_JSON_VERSION

    check("Version constant is 1", SHOP_JSON_VERSION == 1)
    check("count limit is UInt16", FIELD_LIMITS["count"][1] == 65535)
    check("duration limit is Int16", FIELD_LIMITS["duration"][1] == 32767)
    check("price limit is UInt32", FIELD_LIMITS["price"][1] == 4294967295)
    check("adType limit is UInt8", FIELD_LIMITS["ad_type"][1] == 255)


def test_account_rules() -> None:
    print("\n[Account and password rules]")
    from core.accounts import AuthError, validate_credentials

    def rejected(u: str, p: str) -> bool:
        try:
            validate_credentials(u, p)
            return False
        except AuthError:
            return True

    check("numeric password rejected", rejected("abcde", "12345"))
    check("4-character password rejected", rejected("abcde", "1234"))
    check("16-character password rejected",
          rejected("abcde", "1234567890123456"))
    check("valid password accepted", not rejected("abcde", "abc12345"))
    check("4-character account rejected", rejected("abcd", "abc12345"))
    check("underscore in account rejected", rejected("abc_de", "abc12345"))
    check("Chinese account rejected", rejected("测试账号", "abc12345"))
    check("valid account accepted", not rejected("user001", "abc12345"))


def test_geometry_parse() -> None:
    print("\n[Window geometry parsing]")
    from ui.layout import parse_geometry

    check("positive coordinates",
          parse_geometry("1330x760+140+80") == (1330, 760, 140, 80))
    check("negative coordinates (secondary screen)",
          parse_geometry("1330x760-1920+80") == (1330, 760, -1920, 80))
    check("invalid string returns None", parse_geometry("garbage") is None)


def main() -> int:
    print("=" * 46)
    print("  CSNZ Server Toolkit self-test")
    print("=" * 46)
    test_item_rules()
    test_shop_limits()
    test_account_rules()
    test_geometry_parse()

    print("\n" + "=" * 46)
    if failures:
        print(f"  {len(failures)} failed")
        return 1
    print("  All checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
