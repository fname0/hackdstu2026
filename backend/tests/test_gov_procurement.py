"""Regression cases discovered while matching actual programme objects to EIS."""
import unittest
from collections import Counter
from datetime import date

from backend.etl.gov_procurement import match
from backend.etl.gov_project_details import apply


class ObjectMatching(unittest.TestCase):
    def check_pair(self, title, subject, expected):
        p = {"title": title, "beneficiary_inn": None}
        c = {"subject": subject, "signed": "01.03.2024", "customer_name": "Заказчик", "customer_inn": "6100000000"}
        self.assertEqual(match(p, c, Counter()) is not None, expected)

    def test_same_school_same_address(self):
        self.check_pair('Капитальный ремонт МБОУ Кашарская СОШ, сл. Кашары, ул. Мира, 3',
                        'Капитальный ремонт МБОУ Кашарская СОШ, сл. Кашары, ул. Мира, 3', True)

    def test_road_near_school_is_not_school_repair(self):
        self.check_pair('Капитальный ремонт МБОУ СОШ № 7 г. Сальска, ул. Коломийцева, д. 128',
                        'Разработка ПСД: Капитальный ремонт автомобильной дороги по ул. Дзержинского от ул. Коломийцева в г. Сальске', False)

    def test_another_building_on_same_street(self):
        self.check_pair('Капитальный ремонт ГБПОУ РО КТТ, г. Константиновск, ул. Комсомольская, 61',
                        'Выполнение проектных и изыскательских работ: Капитальный ремонт общежития КТАУ, г. Константиновск, ул. Комсомольская, дом №115, корпус №2', False)

    def test_other_floor_and_current_repair(self):
        self.check_pair('Капитальный ремонт коридора 4 этажа ГБПОУ РО РСК, ул. Максима Горького, 30',
                        'Выполнение работ по текущему ремонту коридора 3 этажа ГБПОУ РО РСК, ул. Максима Горького, 30', False)

    def test_boards_are_not_a_building_contract(self):
        self.check_pair('Строительство школы на 1340 мест в Батайске, район Авиагородок, 44А',
                        'Рельсовые системы с классной доской на оснащение объекта Строительство школы на 1340 мест в Батайске, район Авиагородок, 44А', False)


class StageEvidence(unittest.TestCase):
    def test_terminated_contract_does_not_stop_entire_project(self):
        p = {"project_id": "p", "stage": "стадия не подтверждена", "source_detail": {}, "finish_year": None}
        c = {"number": "1", "customer_name": "Заказчик", "customer_inn": "6100000000", "status": "Исполнение прекращено", "url": "https://zakupki.gov.ru/contract", "signed": "01.01.2025", "updated": "01.09.2026"}
        apply([p], {"p": {"match": c, "verified": True, "searched_at": "2026-10-25"}})
        self.assertEqual(p["stage"], "стадия не подтверждена")
        self.assertIn("остановка всего проекта", p["stage_basis"])

    def test_completed_contract_conflicts_with_future_project_plan(self):
        p = {"project_id": "p", "stage": "стадия не подтверждена", "source_detail": {}, "finish_year": date.today().year + 2}
        c = {"number": "1", "customer_name": "Заказчик", "customer_inn": "6100000000", "status": "Исполнение завершено", "url": "https://zakupki.gov.ru/contract", "signed": "01.01.2025", "updated": "01.09.2026"}
        apply([p], {"p": {"match": c, "verified": True, "searched_at": "2026-10-25"}})
        self.assertEqual(p["stage"], "стадия не подтверждена")


if __name__ == "__main__":
    unittest.main()
