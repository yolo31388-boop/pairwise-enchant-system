"""附魔铭文 - 带7个bug"""
from dataclasses import dataclass, field
import random

@dataclass
class EnchantCard:
    cid: str
    stat: str
    value: float
    tier: int
    slot_type: str = "any"  # bug3: 无插槽类型

class EnchantSystem:
    def __init__(self):
        self.cards: list[EnchantCard] = []
        self.equipment = {}
        self.enchanter_level = 1

    def enchant(self, eid, card_id):
        card = next(c for c in self.cards if c.cid == card_id)
        # bug2: 只看主材料
        # bug4: 只看附魔师等级
        success = random.random() < 0.5 + self.enchanter_level * 0.05
        if success:
            if eid not in self.equipment:
                self.equipment[eid] = []
            self.equipment[eid].append(card)
            # bug1: 加法叠加
            return True
        return False

    def can_enchant_slot(self, eid, slot, card):
        # bug3: 不检查插槽类型
        return True

    def overwite(self, eid, old_card_id, new_card_id):
        # bug5: 不能覆盖
        return False

    def get_duration(self, card_id):
        # bug6: 全是永久
        return "permanent"

    def get_description(self, card):
        # bug7: 描述与实际不符
        return f"+{int(card.value)} {card.stat}"
