"""附魔铭文系统 - 7个bug已修复

修复清单:
1. 属性乘区: 同种卡加法、异种卡乘法, 每个属性有上限
2. 材料检查: 主/辅材料全部检查等级(tier)和品质(quality), 不达标拒绝附魔
3. 插槽类型: attack/defense/special, 类型不匹配不能镶嵌
4. 成功率: 附魔师等级 + 材料品质 + 装备等级 综合计算
5. 可覆盖: 消耗覆盖道具, 或返还旧卡部分材料
6. 持续时间: 支持永久和限时(秒), 限时到期自动消失
7. 描述一致: 描述与实际效果同源生成, 并有配置校验
"""
from dataclasses import dataclass, field
import random
import time

DAY = 86400  # 一天的秒数, 限时附魔用, 如 duration=3 * DAY

SLOT_TYPES = ("attack", "defense", "special")
ANY_SLOT = "any"

MAX_QUALITY = 5
# 各属性乘区上限(百分比属性的最终加成上限), 未列出的用 default_stat_cap
DEFAULT_STAT_CAPS = {"crit": 0.5}


@dataclass
class EnchantCard:
    cid: str
    stat: str
    value: float
    tier: int
    slot_type: str = ANY_SLOT      # attack/defense/special/any
    quality: int = 1               # 作为材料时的品质 1~5, 也是附魔要求的最低品质
    is_percent: bool = True        # True=百分比加成, False=固定值加成
    duration: float | None = None  # None=永久, 否则为持续秒数(限时附魔)


class EnchantSystem:
    def __init__(self):
        self.cards: list[EnchantCard] = []
        self.equipment: dict[str, list[EnchantCard]] = {}
        self.enchanter_level = 1
        self.overwrite_items = 0            # 覆盖道具数量
        self.inventory: list[EnchantCard] = []  # 覆盖返还的材料进入背包
        self.stat_caps = dict(DEFAULT_STAT_CAPS)
        self.default_stat_cap = 1.0
        self.refund_ratio = 0.5             # 无覆盖道具时返还旧卡材料的比例
        self._expiry: dict[tuple[str, str], float] = {}  # (eid, cid) -> 到期时间戳

    # ---------- bug7: 配置校验, 描述与实际效果同源 ----------

    def validate_config(self, card: EnchantCard):
        """配置不合法直接抛 ValueError, 保证描述和效果来自同一份合法配置。"""
        if card.slot_type != ANY_SLOT and card.slot_type not in SLOT_TYPES:
            raise ValueError(f"非法插槽类型: {card.slot_type}")
        if card.tier < 1:
            raise ValueError(f"非法等级: {card.tier}")
        if not 1 <= card.quality <= MAX_QUALITY:
            raise ValueError(f"非法品质: {card.quality}")
        if card.value <= 0:
            raise ValueError(f"非法数值: {card.value}")
        if card.is_percent and card.value > 1:
            raise ValueError(f"百分比加成数值超过100%: {card.value} (应使用固定值)")
        if not card.is_percent and card.value < 1:
            raise ValueError(f"固定值加成小于1: {card.value} (应使用百分比)")
        if card.duration is not None and card.duration <= 0:
            raise ValueError(f"非法持续时间: {card.duration}")

    def get_description(self, card: EnchantCard) -> str:
        """描述由驱动实际效果的同一字段(is_percent/value)生成, 保证一致。"""
        self.validate_config(card)
        if card.is_percent:
            return f"+{card.value * 100:g}% {card.stat}"
        return f"+{card.value:g} {card.stat}"

    def apply_effect(self, base: float, card: EnchantCard) -> float:
        """实际效果, 与 get_description 使用同一配置。"""
        self.validate_config(card)
        if card.is_percent:
            return base * (1 + card.value)
        return base + card.value

    # ---------- bug1: 乘区叠加 + 上限 ----------

    def compute_stats(self, eid: str, now: float | None = None) -> dict[str, float]:
        """同种卡(同cid)加法, 异种卡乘法; 百分比属性有上限; 固定值直接相加。"""
        flat: dict[str, float] = {}
        zones: dict[str, dict[str, float]] = {}  # stat -> cid -> 同种卡加法和
        for card in self.get_active_cards(eid, now):
            if card.is_percent:
                zones.setdefault(card.stat, {}).setdefault(card.cid, 0.0)
                zones[card.stat][card.cid] += card.value
            else:
                flat[card.stat] = flat.get(card.stat, 0.0) + card.value
        result = dict(flat)
        for stat, groups in zones.items():
            mult = 1.0
            for group_sum in groups.values():
                mult *= 1 + group_sum
            cap = self.stat_caps.get(stat, self.default_stat_cap)
            bonus = min(mult - 1, cap)
            result[stat] = result.get(stat, 0.0) + bonus
        return result

    # ---------- bug2: 所有材料检查等级和品质 ----------

    def check_materials(self, card: EnchantCard, materials: list[EnchantCard]):
        """主辅材料逐一检查: 等级>=卡等级 且 品质>=卡要求品质, 不达标抛 ValueError。"""
        for m in materials:
            if m.tier < card.tier:
                raise ValueError(
                    f"材料 {m.cid} 等级不足: {m.tier} < {card.tier}")
            if m.quality < card.quality:
                raise ValueError(
                    f"材料 {m.cid} 品质不足: {m.quality} < {card.quality}")

    # ---------- bug4: 成功率综合计算 ----------

    def success_rate(self, card: EnchantCard,
                     materials: list[EnchantCard] | None = None,
                     equipment_level: int = 1) -> float:
        rate = 0.5 + self.enchanter_level * 0.05
        if materials:
            avg_quality = sum(m.quality for m in materials) / len(materials)
            rate += (avg_quality - 1) * 0.05
        rate -= max(0, equipment_level - 1) * 0.02
        return min(0.95, max(0.05, rate))

    # ---------- bug3: 插槽类型检查 ----------

    @staticmethod
    def _slot_type_of(slot) -> str | None:
        s = str(slot).lower()
        for t in SLOT_TYPES:
            if t in s:
                return t
        return None

    def can_enchant_slot(self, eid, slot, card: EnchantCard) -> bool:
        if card.slot_type == ANY_SLOT:
            return True
        slot_type = self._slot_type_of(slot)
        return slot_type is not None and slot_type == card.slot_type

    # ---------- 附魔主流程 ----------

    def enchant(self, eid, card_id, materials=None, slot=None,
                equipment_level=1) -> bool:
        card = next(c for c in self.cards if c.cid == card_id)
        self.validate_config(card)
        if slot is not None and not self.can_enchant_slot(eid, slot, card):
            raise ValueError(f"插槽类型不匹配: {slot} 不能镶嵌 {card.slot_type}")
        if materials is not None:
            self.check_materials(card, materials)
        if random.random() < self.success_rate(card, materials, equipment_level):
            self.equipment.setdefault(eid, []).append(card)
            if card.duration is not None:  # bug6: 限时附魔记录到期时间
                self._expiry[(eid, card.cid)] = time.time() + card.duration
            return True
        return False

    # ---------- bug5: 可覆盖 ----------

    def overwrite(self, eid, old_card_id, new_card_id, materials=None,
                  slot=None, equipment_level=1) -> bool:
        """覆盖已附魔的卡: 有覆盖道具则消耗道具, 否则返还旧卡部分材料到背包。"""
        cards = self.equipment.get(eid, [])
        old = next((c for c in cards if c.cid == old_card_id), None)
        if old is None:
            raise ValueError(f"装备 {eid} 上没有附魔 {old_card_id}")
        if self.overwrite_items > 0:
            self.overwrite_items -= 1
        else:
            self._refund(old)
        cards.remove(old)
        self._expiry.pop((eid, old_card_id), None)
        return self.enchant(eid, new_card_id, materials=materials, slot=slot,
                            equipment_level=equipment_level)

    # 兼容旧拼写
    overwite = overwrite

    def _refund(self, old: EnchantCard):
        """按 refund_ratio 返还旧卡部分材料(用低一级的同属性卡表示)。"""
        if old.tier > 1 and self.refund_ratio > 0:
            self.inventory.append(EnchantCard(
                cid=f"{old.cid}_refund", stat=old.stat,
                value=old.value * self.refund_ratio,
                tier=old.tier - 1, slot_type=old.slot_type,
                quality=old.quality, is_percent=old.is_percent))

    # ---------- bug6: 永久 / 限时 ----------

    def get_duration(self, card_id):
        """永久返回 'permanent', 限时返回持续秒数。"""
        card = next(c for c in self.cards if c.cid == card_id)
        return "permanent" if card.duration is None else card.duration

    def is_expired(self, eid, cid, now: float | None = None) -> bool:
        expires_at = self._expiry.get((eid, cid))
        if expires_at is None:
            return False
        return (now if now is not None else time.time()) >= expires_at

    def get_active_cards(self, eid, now: float | None = None) -> list[EnchantCard]:
        return [c for c in self.equipment.get(eid, [])
                if not self.is_expired(eid, c.cid, now)]

    def cleanup_expired(self, now: float | None = None):
        """限时附魔到期自动消失。"""
        for eid in list(self.equipment):
            kept = []
            for c in self.equipment[eid]:
                if self.is_expired(eid, c.cid, now):
                    self._expiry.pop((eid, c.cid), None)
                else:
                    kept.append(c)
            self.equipment[eid] = kept
