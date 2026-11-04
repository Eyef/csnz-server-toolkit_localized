"""ServerConfig.json 的读取、受控编辑与校验。

只暴露工具真正该管的字段：整文件自由编辑容易被改成服务端无法解析的内容
（例如把 Port 改成非数字，CServerConfig::Load 失败 → 服启动失败）。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .i18n import t

# 字段 -> (标签 locale key, 类型, 说明 locale key[, 可选值])
# 第 4 项存在时，界面渲染为下拉框而不是输入框。
# 只有取值是「有限枚举」的字段才该有第 4 项——让用户手填数字是设计缺陷。
EDITABLE = {
    "HostName": ("cfg.field.HostName.label", str, "cfg.field.HostName.note"),
    "Port": ("cfg.field.Port.label", str, "cfg.field.Port.note"),
    "MaxPlayers": ("cfg.field.MaxPlayers.label", int, "cfg.field.MaxPlayers.note"),
    "WelcomeMessage": ("cfg.field.WelcomeMessage.label", str,
                       "cfg.field.WelcomeMessage.note"),
    "InventorySlotMax": ("cfg.field.InventorySlotMax.label", int,
                         "cfg.field.InventorySlotMax.note"),
    "MaxRegistrationsPerIP": ("cfg.field.MaxRegistrationsPerIP.label", int,
                             "cfg.field.MaxRegistrationsPerIP.note"),
    "BanListMaxSize": ("cfg.field.BanListMaxSize.label", int,
                       "cfg.field.BanListMaxSize.note"),
    # 取值来自客户端主菜单皮肤事件，源码只判断 > 0 后原样下发给客户端
    "MainMenuSkinEvent": ("cfg.field.MainMenuSkinEvent.label", int,
                          "cfg.field.MainMenuSkinEvent.note", {
        0: "cfg.skin.0",
        5: "cfg.skin.5",
        6: "cfg.skin.6",
        7: "cfg.skin.7",
        8: "cfg.skin.8",
    }),
    "CheckClientBuild": ("cfg.field.CheckClientBuild.label", bool,
                         "cfg.field.CheckClientBuild.note"),
    "AllowedClientTimestamp": ("cfg.field.AllowedClientTimestamp.label", int,
                               "cfg.field.AllowedClientTimestamp.note"),
    "AllowedLauncherVersion": ("cfg.field.AllowedLauncherVersion.label", int,
                               "cfg.field.AllowedLauncherVersion.note"),
    "SSL": ("cfg.field.SSL.label", bool, "cfg.field.SSL.note"),
    "Crypt": ("cfg.field.Crypt.label", bool, "cfg.field.Crypt.note"),
    "RestartOnCrash": ("cfg.field.RestartOnCrash.label", bool,
                       "cfg.field.RestartOnCrash.note"),
}

METADATA_LABELS = {
    "Maplist": "cfg.meta.Maplist", "ClientTable": "cfg.meta.ClientTable",
    "Item": "cfg.meta.Item", "ItemBox": "cfg.meta.ItemBox",
    "MatchOption": "cfg.meta.MatchOption",
    "ZombieWarWeaponList": "cfg.meta.ZombieWarWeaponList",
    "WeaponParts": "cfg.meta.WeaponParts",
    "GameModeList": "cfg.meta.GameModeList",
    "ProgressUnlock": "cfg.meta.ProgressUnlock",
    "WeaponPaints": "cfg.meta.WeaponPaints",
    "ReinforceMaxLvl": "cfg.meta.ReinforceMaxLvl",
    "ReinforceMaxEXP": "cfg.meta.ReinforceMaxEXP",
    "ReinforceItemsExp": "cfg.meta.ReinforceItemsExp",
    "ItemExpireTime": "cfg.meta.ItemExpireTime",
    "ScenarioTX_Common": "cfg.meta.ScenarioTX_Common",
    "ScenarioTX_Dedi": "cfg.meta.ScenarioTX_Dedi",
    "ShopItemList_Dedi": "cfg.meta.ShopItemList_Dedi",
    "ZBCompetitive": "cfg.meta.ZBCompetitive", "PPSystem": "cfg.meta.PPSystem",
    "CodisData": "cfg.meta.CodisData", "WeaponProp": "cfg.meta.WeaponProp",
    "RandomWeaponList": "cfg.meta.RandomWeaponList",
    "ModeEvent": "cfg.meta.ModeEvent",
    "HonorMoneyShop": "cfg.meta.HonorMoneyShop",
    "MileageShop": "cfg.meta.MileageShop", "EventShop": "cfg.meta.EventShop",
    "FamilyTotalWarMap": "cfg.meta.FamilyTotalWarMap",
    "FamilyTotalWar": "cfg.meta.FamilyTotalWar",
    "WeaponAscend": "cfg.meta.WeaponAscend", "PerkParam": "cfg.meta.PerkParam",
    "Synthesis": "cfg.meta.Synthesis", "VoxelList": "cfg.meta.VoxelList",
    "VoxelItem": "cfg.meta.VoxelItem",
    "VoxelConfigList": "cfg.meta.VoxelConfigList",
}


class ServerConfig:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        self.dirty = False

    def load(self) -> None:
        self.data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self.dirty = False

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.dirty = True

    @property
    def metadata(self) -> dict:
        return self.data.setdefault("Metadata", {})

    def set_metadata(self, key: str, enabled: bool) -> None:
        self.metadata[key] = bool(enabled)
        self.dirty = True

    def validate(self) -> list[str]:
        problems: list[str] = []
        port = str(self.data.get("Port", ""))
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            problems.append(t("cfg.validation.port", value=repr(port)))
        mp = self.data.get("MaxPlayers", 0)
        if not isinstance(mp, int) or not (1 <= mp <= 1000):
            problems.append(t("cfg.validation.maxplayers", value=repr(mp)))
        slot = self.data.get("InventorySlotMax", 0)
        if not isinstance(slot, int) or slot < 32:
            problems.append(t("cfg.validation.slots", value=repr(slot)))
        if self.data.get("CheckClientBuild"):
            ts = self.data.get("AllowedClientTimestamp", 0)
            if not isinstance(ts, int):
                problems.append(t("cfg.validation.timestamp"))
        skin = self.data.get("MainMenuSkinEvent", 0)
        choices = EDITABLE["MainMenuSkinEvent"][3]
        if skin not in choices:
            problems.append(
                t("cfg.validation.skin",
                  choices="/".join(str(k) for k in choices), value=skin)
            )
        if not isinstance(self.data.get("Metadata"), dict):
            problems.append(t("cfg.validation.metadata"))
        return problems

    def save(self, backup_dir: Path | None = None) -> Path | None:
        problems = self.validate()
        if problems:
            raise ValueError(t("cfg.validation.failed",
                               problems="\n".join(problems)))
        backup = None
        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"ServerConfig_{stamp}.json"
            if self.path.exists():
                shutil.copy2(self.path, backup)
        text = json.dumps(self.data, ensure_ascii=False, indent="\t")
        self.path.write_text(text + "\n", encoding="utf-8")
        self.dirty = False
        return backup


__all__ = ["ServerConfig", "EDITABLE", "METADATA_LABELS"]
