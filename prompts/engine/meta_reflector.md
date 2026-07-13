# Meta Reflector Strategies

**Версия:** 1.0
**Дата:** 2026-07-13
**Модель:** qwen3.6:35b (рефлектор) / qwen3-vl:30b (агент)
**Тип:** адаптивные модификаторы базовых промптов

---

## Стратегии

### syntax_fix
**Reflector prompt:** "Фокус на синтаксис и точность формулировок"
**Focus prompt:** "Исправь синтаксические ошибки: {reflection}"

### semantic_align
**Reflector prompt:** "Проверь семантическую согласованность"
**Focus prompt:** "Уточни семантические связи: {reflection}"

### structure_verification
**Reflector prompt:** "Проверь структурную целостность"
**Focus prompt:** "Уточни структуру результатов: {reflection}"