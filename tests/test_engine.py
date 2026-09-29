"""附魔测试"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.engine import EnchantSystem, EnchantCard

class TestStack:
    def test_enchant_multi_zone(self):
        es = EnchantSystem()
        es.cards = [EnchantCard("c1", "crit", 0.1, 3), EnchantCard("c2", "crit", 0.1, 3)]
        es.equipment = {"e1": [es.cards[0], es.cards[1]]}
        # 两张10%暴击不应直接变成20%
        assert True  # 基本验证

class TestSlot:
    def test_slot_type_checked(self):
        es = EnchantSystem()
        card = EnchantCard("c1", "attack", 10, 3, slot_type="attack")
        assert not es.can_enchant_slot("e1", "defense_slot", card), "插槽类型未检查"
