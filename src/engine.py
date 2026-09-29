"""附魔铭文系统"""
from dataclasses import dataclass, field
import random
import time

SLOT_TYPES = ("attack", "defense", "special")

# 百分比属性（描述与实际效果共用的唯一事实来源）
PERCENT_STATS = {"crit", "crit_damage", "dodge", "hit", "attack_speed", "lifesteal"}

# 每个属性乘区的叠加上限
STAT_CAPS = {
    "crit": 0.30,
    "crit_damage": 0.50,
    "dodge": 0.30,
    "hit": 0.30,
    "attack_speed": 0.40,
    "lifesteal": 0.30,
}
DEFAULT_PERCENT_CAP = 1.0  # 未列出的百分比属性的默认上限（固定数值属性不设上限）

# 成功率参数
BASE_SUCCESS = 0.30
ENCHANTER_LEVEL_FACTOR = 0.05
MATERIAL_QUALITY_FACTOR = 0.30
EQUIPMENT_LEVEL_PENALTY = 0.02
MIN_SUCCESS = 0.05
MAX_SUCCESS = 0.95

# 覆盖附魔时未使用覆盖道具的材料返还比例
OVERWRITE_REFUND_RATIO = 0.5

THREE_DAYS = 3 * 24 * 3600


@dataclass
class EnchantCard:
    cid: str
    stat: str
    value: float
    tier: int
    slot_type: str = "any"  # attack / defense / special / any
    duration: float | None = None  # None=永久；秒数=限时（如 THREE_DAYS）
    quality_req: float = 0.0  # 材料最低品质(0.0~1.0)


@dataclass
class Material:
    mid: str
    level: int
    quality: float  # 0.0~1.0


@dataclass
class AppliedEnchant:
    card: EnchantCard
    applied_at: float
    materials: list = field(default_factory=list)

    def is_expired(self, now):
        return self.card.duration is not None and now >= self.applied_at + self.card.duration


def _slot_type_of(slot):
    """从插槽标识解析插槽类型：'defense_slot'->'defense'，或直接是类型名。"""
    name = str(slot)
    if name.endswith("_slot"):
        name = name[: -len("_slot")]
    return name


class EnchantSystem:
    def __init__(self, rng=None):
        self.cards: list[EnchantCard] = []
        self.equipment: dict[str, list] = {}
        self.equipment_levels: dict[str, int] = {}
        self.equipment_slots: dict[str, dict] = {}
        self.enchanter_level = 1
        self.rng = rng or random.Random()

    # ---- 配置校验（bug7：保证描述与实际效果一致的前提） ----

    def validate_card(self, card):
        if not card.cid:
            raise ValueError("卡片缺少 cid")
        if card.tier < 1:
            raise ValueError(f"卡片 {card.cid} tier 必须 >= 1")
        if card.value <= 0:
            raise ValueError(f"卡片 {card.cid} value 必须为正")
        if card.slot_type != "any" and card.slot_type not in SLOT_TYPES:
            raise ValueError(f"卡片 {card.cid} 非法插槽类型 {card.slot_type!r}")
        if card.duration is not None and card.duration <= 0:
            raise ValueError(f"卡片 {card.cid} 限时时长必须为正")
        cap = STAT_CAPS.get(card.stat, DEFAULT_PERCENT_CAP)
        if card.stat in PERCENT_STATS and card.value > cap:
            raise ValueError(f"卡片 {card.cid} 数值 {card.value} 超过 {card.stat} 上限 {cap}")
        if not 0.0 <= card.quality_req <= 1.0:
            raise ValueError(f"卡片 {card.cid} quality_req 必须在 0~1")
        return True

    def validate_config(self):
        for card in self.cards:
            self.validate_card(card)
        return True

    # ---- 装备注册 ----

    def register_equipment(self, eid, level=1, slots=None):
        self.equipment_levels[eid] = level
        if slots:
            self.equipment_slots[eid] = dict(slots)

    # ---- 材料检查（bug2：主辅材料全部检查等级与品质） ----

    def check_materials(self, card, materials):
        if not materials:
            raise ValueError("附魔需要至少一件材料")
        for m in materials:
            if m.level < card.tier:
                raise ValueError(
                    f"材料 {m.mid} 等级 {m.level} 低于卡片要求 {card.tier}"
                )
            if m.quality < card.quality_req:
                raise ValueError(
                    f"材料 {m.mid} 品质 {m.quality} 低于卡片要求 {card.quality_req}"
                )
        return True

    # ---- 成功率（bug4：附魔师等级 + 材料品质 + 装备等级） ----

    def success_rate(self, eid, card, materials):
        avg_quality = sum(m.quality for m in materials) / len(materials)
        equip_level = self.equipment_levels.get(eid, 1)
        rate = (
            BASE_SUCCESS
            + self.enchanter_level * ENCHANTER_LEVEL_FACTOR
            + avg_quality * MATERIAL_QUALITY_FACTOR
            - equip_level * EQUIPMENT_LEVEL_PENALTY
        )
        return max(MIN_SUCCESS, min(MAX_SUCCESS, rate))

    # ---- 插槽类型检查（bug3） ----

    def can_enchant_slot(self, eid, slot, card):
        if card.slot_type == "any":
            return True
        declared = self.equipment_slots.get(eid, {})
        slot_type = declared.get(slot, _slot_type_of(slot))
        return slot_type == card.slot_type

    # ---- 附魔 ----

    def enchant(self, eid, card_id, materials=None, slot=None, now=None):
        card = next(c for c in self.cards if c.cid == card_id)
        self.validate_card(card)
        materials = list(materials) if materials else [Material("default", card.tier, 1.0)]
        self.check_materials(card, materials)
        if slot is not None and not self.can_enchant_slot(eid, slot, card):
            raise ValueError(f"卡片 {card_id} 类型 {card.slot_type} 与插槽 {slot} 不匹配")
        success = self.rng.random() < self.success_rate(eid, card, materials)
        if success:
            self.equipment.setdefault(eid, []).append(
                AppliedEnchant(card, time.time() if now is None else now, materials)
            )
            return True
        return False

    # ---- 覆盖（bug5：需覆盖道具，否则返还部分材料） ----

    def overwrite(self, eid, old_card_id, new_card_id, materials=None,
                  overwrite_item=None, now=None):
        enchants = self.equipment.get(eid, [])
        index = next(
            (i for i, a in enumerate(enchants) if self._card_of(a).cid == old_card_id),
            None,
        )
        if index is None:
            raise ValueError(f"装备 {eid} 上没有附魔 {old_card_id}")
        old = enchants[index]
        old_materials = self._materials_of(old)
        if overwrite_item is None:
            # 没有覆盖道具：返还部分旧材料
            refunded = old_materials[: max(1, int(len(old_materials) * OVERWRITE_REFUND_RATIO))] \
                if old_materials else []
        else:
            refunded = []
        del enchants[index]
        ok = self.enchant(eid, new_card_id, materials=materials, now=now)
        if not ok:
            enchants.insert(index, old)  # 失败回滚
            return False
        return refunded

    # 兼容旧拼写
    overwite = overwrite

    # ---- 限时附魔（bug6） ----

    def get_duration(self, card_id):
        card = next(c for c in self.cards if c.cid == card_id)
        return "permanent" if card.duration is None else card.duration

    def _active(self, eid, now=None):
        now = time.time() if now is None else now
        result = []
        for a in self.equipment.get(eid, []):
            if isinstance(a, AppliedEnchant):
                if not a.is_expired(now):
                    result.append(a)
            else:  # 兼容直接放入的 EnchantCard（视为永久）
                result.append(a)
        return result

    def cleanup_expired(self, eid, now=None):
        now = time.time() if now is None else now
        kept = self._active(eid, now)
        removed = [a for a in self.equipment.get(eid, []) if a not in kept]
        self.equipment[eid] = kept
        return removed

    # ---- 属性结算（bug1：同类加法、异类乘法、有上限） ----

    def compute_stats(self, eid, now=None):
        zones: dict[str, float] = {}
        for a in self._active(eid, now):
            card = self._card_of(a)
            zones[card.stat] = zones.get(card.stat, 0.0) + card.value  # 同类加法
        capped = {}
        for stat, v in zones.items():
            if stat in PERCENT_STATS or stat in STAT_CAPS:
                capped[stat] = min(v, STAT_CAPS.get(stat, DEFAULT_PERCENT_CAP))  # 乘区上限
            else:
                capped[stat] = v  # 固定数值属性不设上限
        multiplier = 1.0
        for v in capped.values():
            multiplier *= 1.0 + v  # 异类乘法
        return {"zones": capped, "multiplier": multiplier}

    # ---- 描述（bug7：与实际结算共用同一数据源） ----

    def get_description(self, card):
        if card.stat in PERCENT_STATS:
            return f"+{card.value * 100:g}% {card.stat}"
        return f"+{card.value:g} {card.stat}"

    # ---- 内部工具 ----

    @staticmethod
    def _card_of(applied):
        return applied.card if isinstance(applied, AppliedEnchant) else applied

    @staticmethod
    def _materials_of(applied):
        return applied.materials if isinstance(applied, AppliedEnchant) else []
